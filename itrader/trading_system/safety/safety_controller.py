"""Pure safety state machine for the live engine — the single owner of the safety latch.

Every collaborator is INJECTED and NO venue I/O lives here: missed-fill re-fetch, account
re-snapshotting, ring back-fill and connector-loop calls belong to
``StreamRecoveryHandler`` instead.
"""

import threading
from collections import deque
from datetime import datetime, UTC
from typing import Any, Callable, Optional

from itrader.core.enums import (
    ErrorSeverity,
    EventType,
    OrderCommand,
    OrderRiskRole,
    SystemStatus,
    VALID_STATUS_TRANSITIONS,
)
from itrader.events_handler.events import ErrorEvent
from itrader.logger import get_itrader_logger

# Bound on the pause-window queue of protective orders (bracket children, OCO/orphan
# cancels) deferred during a pause/halt and replayed on resume.
_DEFERRED_PROTECTIVE_REPLAY_MAX = 1000

# A fixed literal, never str(exc) or a connector payload, so no secret can leak when it
# crosses halt() -> record_halt / CRITICAL ErrorEvent.
_DEFERRED_PROTECTIVE_OVERFLOW_REASON = "deferred-protective-overflow"


def classify(event: Any) -> OrderRiskRole:
    """Classify an event's risk role — the ONE predicate shared by
    ``SafetyController.gate_and_dispatch`` and ``PreTradeThrottle``, so no divergent copy
    of "what counts as protective" can suppress a risk-reducing order.
    """
    if getattr(event, 'command', None) is OrderCommand.CANCEL:
        return OrderRiskRole.CANCEL
    if (getattr(event, 'type', None) is EventType.ORDER
            and getattr(event, 'parent_order_id', None) is not None):
        return OrderRiskRole.PROTECTIVE
    return OrderRiskRole.ENTRY


class SafetyController:
    """Pure live-engine safety state machine — no venue I/O.

    Constructed once inside ``build_live_system``, injected into the live facade + runner,
    and holds NO connector/exchange handle.

    Parameters
    ----------
    bus
        The engine ``global_queue`` — the CRITICAL ``ErrorEvent`` egress for ``halt``.
        Only ``.put`` is used.
    halt_record_store
        The durable ``HaltRecordStore``. ``None`` when the live run falls back to in-memory
        storage; every durable step then degrades to a no-op.
    dispatch_fn
        The canonical inner dispatch. ``build_live_system`` injects a LATE-BOUND
        ``lambda ev: event_handler._dispatch(ev)`` so a monkeypatched ``_dispatch`` is
        honoured.
    notify_status_change
        Optional callback ``(old_status, new_status, error_msg)`` invoked OUTSIDE
        ``_status_lock`` on a successful transition. The facade passes one that enriches
        with exchange/queue-size and fires the external ``status_callback``.
    system_store
        Optional durable KV sink for the ``state.status`` / ``state.halt_reason``
        read-model rows. ``None`` on the backtest / in-memory-fallback wirings.
    deferred_maxlen
        Bound on the deferred-protective replay queue. Overflow escalates to HALT.
    """

    def __init__(
        self,
        *,
        bus: Any,
        halt_record_store: Optional[Any] = None,
        dispatch_fn: Optional[Callable[[Any], None]] = None,
        notify_status_change: Optional[
            Callable[[SystemStatus, SystemStatus, Optional[str]], None]
        ] = None,
        system_store: Optional[Any] = None,
        deferred_maxlen: int = _DEFERRED_PROTECTIVE_REPLAY_MAX,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="SafetyController")
        self._bus = bus
        self._halt_record_store: Optional[Any] = halt_record_store
        self._dispatch_fn: Optional[Callable[[Any], None]] = dispatch_fn
        self._notify_status_change_cb = notify_status_change
        self._system_store: Optional[Any] = system_store
        self._deferred_maxlen = deferred_maxlen

        # -- Status latch state. --
        self._status = SystemStatus.STOPPED
        self._status_lock = threading.Lock()
        self._last_error: Optional[str] = None
        self._halt_reason: Optional[str] = None
        # REVERSIBLE pause-on-disconnect state, distinct from the terminal HALT.
        self._submission_paused = False
        self._paused_reason: Optional[str] = None
        self._deferred_protective: "deque[Any]" = deque(maxlen=deferred_maxlen)

    def halt(self, reason: str) -> None:
        """Freeze-in-place halt of the whole engine.

        The money-first response when the engine can no longer trust its own state
        (unexplained drift, unresolved reconciliation, a fatal connector error). Suppresses
        all NEW order submission (gated in ``gate_and_dispatch``) while BAR/FILL streaming,
        reconciling and persisting CONTINUE to drain, and emits ONE CRITICAL ``ErrorEvent``
        to the operator. It does NOT auto-flatten or auto-cancel: the engine just declared
        its own state untrustworthy, so it must not act on it. Idempotent — first halt wins.

        Parameters
        ----------
        reason : str
            Machine-readable halt reason. The intended vocabulary is the
            ``core.enums.HaltReason`` values plus
            ``_DEFERRED_PROTECTIVE_OVERFLOW_REASON``, but the parameter is a plain ``str``
            and nothing enforces it.
        """
        # The flip, the halt_reason and _last_error land under ONE _status_lock
        # acquisition, so two concurrent halt() callers cannot both clobber the reason and
        # both fire the alert. HALTED is reachable from every non-terminal state in
        # VALID_STATUS_TRANSITIONS, so this flip is never refused.
        transitioned = self.update_status(
            SystemStatus.HALTED,
            error_msg=f'halt: {reason}',
            halt_reason=reason,
        )
        if not transitioned:
            return  # already halted — first reason wins.
        # Winner only past here. Only declared ErrorEvent fields are bound, so no
        # connector secret can leak out through the ERROR route.
        self._bus.put(ErrorEvent(
            time=datetime.now(UTC),
            source='live_trading_system',
            error_type='EngineHalted',
            error_message=(
                f'Engine halted (reason={reason}) — new order submission frozen '
                'in place; streaming/reconciling/persisting continue, no '
                'auto-flatten/auto-cancel'),
            operation='halt',
            severity=ErrorSeverity.CRITICAL,
        ))
        # A DURABLE record so the latch survives a process restart (consumed by
        # check_durable_halt_on_start). Bind ONLY the reason literal + timestamp — never
        # str(exc) or a connector payload.
        if self._halt_record_store is not None:
            self._halt_record_store.record_halt(reason, datetime.now(UTC))

    def is_halted(self) -> bool:
        """Whether the engine is in the freeze-in-place HALTED state."""
        with self._status_lock:
            return self._status == SystemStatus.HALTED

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched HALTED state.

        The SOLE sanctioned exit from ``HALTED``, deliberately OUTSIDE the transition table
        (a ``force=True`` write through ``update_status``). It does NOT re-open the trading
        gate itself: a subsequent ``start()`` re-runs reconciliation + the baseline guard
        from the clean STOPPED baseline, so the halt cause is re-checked rather than
        assumed resolved.

        Returns
        -------
        bool
            ``True`` if a latched HALTED was cleared; ``False`` if the engine was not
            HALTED (no-op).
        """
        if not self.is_halted():
            self.logger.warning('reset_halt() ignored — engine is not HALTED')
            return False
        cleared = self.update_status(
            SystemStatus.STOPPED,
            error_msg='HALTED cleared by operator reset_halt()',
            force=True,
        )
        if cleared:
            # Resolve the DURABLE record too, or it re-refuses the next start().
            if self._halt_record_store is not None:
                self._halt_record_store.resolve_all()
            self.logger.warning(
                'HALTED cleared by operator reset_halt() — engine returned to STOPPED; '
                'a subsequent start() will re-run reconciliation + the baseline guard '
                'before trading (verify-then-trust)')
        return cleared

    def is_submission_paused(self) -> bool:
        """Whether NEW order submission is reversibly paused on a disconnect."""
        with self._status_lock:
            return self._submission_paused

    def status_snapshot(self) -> dict[str, Any]:
        """Read-only snapshot of the safety-owned status fields, for the facade's
        ``get_status``.

        Every field is read under ONE ``_status_lock`` acquisition, so the snapshot is
        internally consistent. ``status`` is the raw enum — the caller renders ``.value``.
        """
        with self._status_lock:
            return {
                'status': self._status,
                'halt_reason': self._halt_reason,
                'paused': self._submission_paused,
                'paused_reason': self._paused_reason,
                'last_error': self._last_error,
            }

    def pause_submission(self, reason: str) -> None:
        """Reversibly pause NEW order submission on a venue-stream disconnect.

        Distinct from ``halt()``: a REVERSIBLE quiesce cleared by ``resume_submission()``
        after reconnect + a fresh REST snapshot. A terminal HALT supersedes a pause, so this
        is a no-op while HALTED, and a second pause keeps the first reason. A locked flag
        flip only, no I/O, so the connector-loop reconnect callback can call it without
        blocking its loop.

        Parameters
        ----------
        reason : str
            Machine-readable pause reason, e.g. ``'paused-on-disconnect'``.
        """
        with self._status_lock:
            if self._status == SystemStatus.HALTED:
                return
            if self._submission_paused:
                return
            self._submission_paused = True
            self._paused_reason = reason
        self.logger.warning(
            'Order submission paused (reason=%s) — new SIGNAL/ORDER suppressed until '
            'reconnect + a fresh REST balance/position snapshot; positions/orders '
            'untouched', reason)

    def resume_submission(self) -> None:
        """Clear the reversible pause after reconnect + a fresh REST snapshot, then drain
        the protective-order replay queue.

        The pause flag is cleared FIRST, so a replayed order reaches ``_dispatch`` instead
        of being re-suppressed by the gate it just came through.
        """
        with self._status_lock:
            if not self._submission_paused:
                return
            self._submission_paused = False
            self._paused_reason = None
        self.logger.info(
            'Order submission resumed — venue stream reconnected + fresh REST '
            'balance/position snapshot complete')
        self._replay_deferred_protective()

    def _replay_deferred_protective(self) -> None:
        """Replay pause-deferred protective orders through the live gate on resume.

        The queue is snapshotted into a local batch and CLEARED BEFORE re-dispatching, so a
        re-dispatch that finds the engine HALTED (and re-defers) appends to the now-empty
        queue instead of spinning this drain forever.
        """
        if not self._deferred_protective:
            return
        batch = list(self._deferred_protective)
        self._deferred_protective.clear()
        self.logger.info(
            'Replaying %d deferred protective order(s) on resume (D-14)', len(batch))
        for deferred in batch:
            # Back through the gate, not raw dispatch, so a re-halt raised mid-replay
            # re-defers instead of sending blind.
            self.gate_and_dispatch(deferred)

    def gate_and_dispatch(
        self,
        event: Any,
        dispatch_fn: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Dispatch one event through the live halt/pause gate.

        While HALTED (terminal) OR paused-on-disconnect (reversible), the SIGNAL and ORDER
        routes are gated while BAR/FILL/ERROR streaming + reconciling + persisting keep
        draining — so the venue stays mirrored and the halt's own CRITICAL ErrorEvent is
        still consumed. Otherwise a transparent pass-through.

        A gated SIGNAL/ORDER is not blanket-suppressed; it branches by ``classify`` so
        risk-REDUCING commands are not silently dropped:

        (a) CANCEL always passes — a cancel only reduces risk;
        (b) PROTECTIVE (a bracket child, ``parent_order_id`` set) is DEFERRED onto the
            replay queue and replayed on resume, never left naked;
        (c) ENTRY (a parentless NEW order, or any SIGNAL) stays SUPPRESSED — opening new
            risk while blind to the venue is what the gate exists to prevent.

        Parameters
        ----------
        event
            The event to gate.
        dispatch_fn
            Override for the inner dispatch; defaults to the injected canonical fn. The
            runner passes the event only.
        """
        dispatch = dispatch_fn if dispatch_fn is not None else self._dispatch_fn
        if (self.is_halted() or self.is_submission_paused()) and getattr(
                event, 'type', None) in (EventType.SIGNAL, EventType.ORDER):
            event_type = getattr(getattr(event, 'type', None), 'name', 'UNKNOWN')
            role = classify(event)
            if role is OrderRiskRole.CANCEL:
                self.logger.info(
                    'CANCEL dispatched during pause/halt (D-14) — cancels always pass the '
                    'gate (risk-reducing)', event_type=event_type)
                if dispatch is not None:
                    dispatch(event)
                return
            if role is OrderRiskRole.PROTECTIVE:
                # A full queue is pathological, so it becomes a loud latched stop rather
                # than a near-unreachable silent drop-oldest that could un-protect a
                # position. The offending order is NOT appended.
                if len(self._deferred_protective) >= self._deferred_maxlen:
                    self.logger.error(
                        'Deferred-protective replay queue overflow (maxlen=%d) — escalating '
                        'to HALT (D-11); a silently dropped protective order would leave a '
                        'naked position', self._deferred_maxlen)
                    self.halt(_DEFERRED_PROTECTIVE_OVERFLOW_REASON)
                    return
                self._deferred_protective.append(event)
                self.logger.warning(
                    'Protective order deferred during pause/halt (D-14) — replays on resume',
                    event_type=event_type)
                return
            self.logger.warning(
                'New order submission suppressed (freeze-in-place / paused-on-disconnect)',
                event_type=event_type)
            return
        if dispatch is not None:
            dispatch(event)

    def update_status(
        self,
        new_status: SystemStatus,
        error_msg: Optional[str] = None,
        halt_reason: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """The SINGLE enforced status-mutation seam.

        The ONE point that writes ``self._status`` for a lifecycle transition. A transition
        outside ``VALID_STATUS_TRANSITIONS[old]`` is log-and-refused, not raised — the live
        event loop is publish-and-continue, so an illegal transition must never abort it.
        ``HALTED`` has NO legal exit in the table, so once the reconciler or baseline guard
        halts the engine no lifecycle transition (the processing loop's RUNNING stamp
        included) can clobber it; only ``reset_halt`` may, through ``force``.

        Parameters
        ----------
        new_status : SystemStatus
            The target lifecycle state.
        error_msg : str, optional
            Recorded as ``self._last_error`` on a successful transition.
        halt_reason : str, optional
            The machine-readable halt reason, set ATOMICALLY with the flip under the same
            ``_status_lock`` acquisition, so two concurrent ``halt()`` callers cannot both
            win.
        force : bool
            Bypass the transition-table check. RESERVED for ``reset_halt``'s HALTED exit —
            do NOT use elsewhere; it defeats the latch.

        Returns
        -------
        bool
            ``True`` iff the status actually changed (the winning caller); ``False`` on a
            same-state no-op or a refused illegal transition.
        """
        with self._status_lock:
            old_status = self._status
            if new_status == old_status:
                return False  # idempotent no-op — already in this state.
            if not force and new_status not in VALID_STATUS_TRANSITIONS[old_status]:
                # The message binds only fixed enum literals, no connector context, so no
                # secret can leak on a halt-adjacent refusal.
                self.logger.warning(
                    'Refused illegal status transition %s -> %s (D-05 latch); '
                    'status unchanged', old_status.value, new_status.value)
                return False
            self._status = new_status
            if error_msg:
                self._last_error = error_msg
            if new_status == SystemStatus.HALTED:
                if halt_reason is not None:
                    self._halt_reason = halt_reason
            else:
                # Leaving HALTED (only via reset_halt's forced exit) clears the reason so
                # get_status() no longer surfaces a stale one.
                self._halt_reason = None

        # Read-model KV for the winning transition only, OUTSIDE the lock
        # (last-write-wins). halt_reason gets its own key so a UI reads it directly.
        self._persist_state("state.status", {"status": new_status.value})
        if new_status == SystemStatus.HALTED and halt_reason is not None:
            self._persist_state("state.halt_reason", {"halt_reason": halt_reason})

        self._notify_status_change(old_status, new_status, error_msg)
        return True

    def _persist_state(self, key: str, value: dict[str, Any]) -> None:
        """Upsert a read-model ``state.*`` KV row — best-effort, never raises.

        A no-op with no injected ``SystemStore``. A write failure (e.g. an un-migrated
        schema) is swallowed-and-logged so a status transition — a halt above all — is
        never aborted by the read-model write. The timestamp is wall clock: a low-rate
        discrete KV write, not a determinism-sensitive money value.
        """
        if self._system_store is None:
            return
        try:
            self._system_store.upsert(key, value, at=datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 — read-model write must never abort a transition.
            self.logger.warning(
                "Failed to persist read-model %s (swallowed — transition proceeds): %s",
                key, exc)

    def _notify_status_change(
        self,
        old_status: SystemStatus,
        new_status: SystemStatus,
        error_msg: Optional[str],
    ) -> None:
        """Log + fire the injected status callback OUTSIDE ``_status_lock``.

        The callback and log must never run holding the lock. Exchange/queue-size
        enrichment and the external ``status_callback`` are facade concerns reached through
        the injected callback, so the pure state machine holds no facade handle.
        """
        self.logger.info(f'Status changed from {old_status.value} to {new_status.value}')

        if self._notify_status_change_cb is not None:
            try:
                self._notify_status_change_cb(old_status, new_status, error_msg)
            except Exception as e:
                self.logger.error(f'Error in status callback: {e}')

    def check_durable_halt_on_start(self) -> bool:
        """Refuse RUNNING on an unresolved durable halt record.

        Runs FIRST at ``start()`` — after STARTING, BEFORE any session init / venue
        connect / feed warmup / stream spawn / snapshot / reconcile. A supervised
        auto-restart builds a FRESH engine whose in-process ``_status`` is STOPPED, so a
        breaker halt whose cause is not re-detectable at start would otherwise be silently
        cleared. Re-latching goes through ``update_status``, NOT ``halt()``, which would
        write a SECOND durable record.

        Returns
        -------
        bool
            ``True`` if a durable halt re-latched this instance (caller must refuse
            RUNNING); ``False`` on a clean store, an absent store, or an already-HALTED
            engine (a no-op).
        """
        if not (self._halt_record_store is not None
                and not self.is_halted()
                and self._halt_record_store.has_unresolved()):
            return False
        durable_record = self._halt_record_store.get_unresolved()
        durable_reason = (
            durable_record.reason if durable_record is not None
            else 'durable-halt')
        self.logger.error(
            'start() refused RUNNING: an unresolved DURABLE halt record latches '
            'across the restart (reason=%s) — a supervised auto-restart cannot '
            'silently clear a breaker halt (T-05.2-17); resolve the cause then '
            'call reset_halt()', durable_reason)
        # Re-latch via update_status — halt() would write a second durable record.
        self.update_status(
            SystemStatus.HALTED,
            error_msg=f'durable halt latched on restart: {durable_reason}',
            halt_reason=durable_reason)
        return True
