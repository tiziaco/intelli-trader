"""Pure safety state machine for the live engine (SAFE-01/02, §11a).

``SafetyController`` is the single pure owner of the live-engine safety latch —
byte-moved out of ``LiveTradingSystem`` so the halt/pause/status machinery has a
focused, unit-testable home with NO venue I/O. It owns:

- the status latch (``_status`` + ``_status_lock`` + ``VALID_STATUS_TRANSITIONS``
  + the single ``update_status`` mutation seam, ``force=`` reserved for
  ``reset_halt``);
- ``halt(reason)`` — the winner-only check-and-set → CRITICAL ``ErrorEvent`` →
  durable ``HaltRecordStore.record_halt`` (D-01/D-05/D-06/WR-01);
- ``is_halted`` / ``reset_halt`` (the SOLE off-table exit, ``force=True`` +
  ``resolve_all``);
- ``pause_submission`` / ``resume_submission`` + the bounded deferred-protective
  replay queue (D-14/D-19);
- ``check_durable_halt_on_start()`` (SAFE-02, §11b) — runs first, before any
  venue I/O, re-latching from a persisted durable halt via ``update_status``
  (NOT ``halt()`` — no second durable write).

All collaborators are INJECTED (the bus for the CRITICAL ``ErrorEvent`` egress,
the durable ``HaltRecordStore``, the canonical dispatch fn, an optional
status-change notify callback, and the deferred-queue bound). NO venue I/O lives
here — missed-fill re-fetch, account re-snapshotting, ring back-fill, and every
connector-loop call belong to ``StreamRecoveryHandler`` (Plan 04). The bodies below are byte-identical
to their ``live_trading_system.py`` donors; Plan 06 removes the donors from the
facade. Plan 02's ``gate_and_dispatch`` + shared ``classify`` land in the sibling
task. 4-space indentation (matches ``live_trading_system.py`` / ``live_runner.py``).
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

# D-14 (V17-11): default bound on the pause-window protective-order replay queue.
# During a pause/halt, system-generated protective orders (bracket children,
# OCO/orphan cancels) are DEFERRED and replayed on resume; the bound guards a
# pathological stall. D-11 (Plan 02) changes the overflow policy from silent
# drop-oldest to escalate-to-HALT — the ONE behavior change in this extraction.
_DEFERRED_PROTECTIVE_REPLAY_MAX = 1000

# D-11: the fixed machine-readable halt reason literal for a deferred-protective
# queue overflow. A fixed literal (never str(exc) / connector payload) so the V7
# secret-scrub holds when it crosses halt() -> record_halt / CRITICAL ErrorEvent.
_DEFERRED_PROTECTIVE_OVERFLOW_REASON = "deferred-protective-overflow"


def classify(event: Any) -> OrderRiskRole:
    """Classify an event's risk role for the safety gate + throttle (D-05/D-16).

    The SINGLE shared predicate — extracted ONCE from the inline
    ``_dispatch_live`` classification so both ``SafetyController.gate_and_dispatch``
    (here) and the ``PreTradeThrottle`` (Plan 05) consume one source of truth; no
    divergent copy of "what counts as protective" can suppress a risk-reducing
    order. Mirrors the donor branch order exactly:

    - a ``CANCEL`` command → ``OrderRiskRole.CANCEL`` (only reduces risk);
    - an ``ORDER`` with ``parent_order_id`` set → ``OrderRiskRole.PROTECTIVE``
      (a bracket child / OCO leg — deferred, never dropped);
    - everything else (a parentless NEW order, a raw SIGNAL) →
      ``OrderRiskRole.ENTRY`` (opens new risk — metered/suppressed).
    """
    if getattr(event, 'command', None) is OrderCommand.CANCEL:
        return OrderRiskRole.CANCEL
    if (getattr(event, 'type', None) is EventType.ORDER
            and getattr(event, 'parent_order_id', None) is not None):
        return OrderRiskRole.PROTECTIVE
    return OrderRiskRole.ENTRY


class SafetyController:
    """Pure live-engine safety state machine — no venue I/O (SAFE-01/§11a).

    Constructed once inside ``build_live_system`` and injected into the live
    facade + runner. Owns the status latch, halt/reset, pause/resume + the
    deferred-protective queue, and the durable-halt startup check. Every
    collaborator is injected; the class holds NO connector/exchange handle.

    Parameters
    ----------
    bus
        The engine ``global_queue``/bus — the CRITICAL ``ErrorEvent`` egress for
        ``halt`` (D-06). Only ``.put`` is used.
    halt_record_store
        The durable ``HaltRecordStore`` (D-10) — ``record_halt`` /
        ``has_unresolved`` / ``get_unresolved`` / ``resolve_all``. ``None`` when
        the live run falls back to in-memory storage (degrade cleanly — no
        durable record).
    dispatch_fn
        The canonical inner dispatch (the runner injects ``event_handler._dispatch``,
        §11a). Used to replay deferred protective orders on resume; the Plan 02
        ``gate_and_dispatch`` also routes through it.
    notify_status_change
        Optional callback ``(old_status, new_status, error_msg)`` invoked OUTSIDE
        ``_status_lock`` on a successful transition. The facade passes a callback
        that enriches with exchange/queue-size and fires the external
        ``status_callback`` (facade concerns kept out of the pure machine).
    deferred_maxlen
        Bound on the deferred-protective replay queue (``config.safety`` or the
        default). Overflow escalates to HALT (D-11, Plan 02).
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
        # D-19 (RTCFG-06): the durable read-model KV sink. On a successful status
        # transition ``state.status`` is upserted here, and ``state.halt_reason`` on a
        # HALTED flip — the read-model surface the (future FastAPI) UI reads lock-free,
        # alongside the ErrorHandler's ``state.last_error``. Optional/None so the
        # backtest + in-memory-fallback wirings degrade cleanly (no durable sink).
        self._system_store: Optional[Any] = system_store
        self._deferred_maxlen = deferred_maxlen

        # -- Status latch state (byte-moved from the facade's per-instance runtime). --
        self._status = SystemStatus.STOPPED
        self._status_lock = threading.Lock()
        self._last_error: Optional[str] = None
        # 05-04 (D-07): machine-readable halt reason surfaced on get_status().
        self._halt_reason: Optional[str] = None
        # 05-08 (D-19): REVERSIBLE pause-on-disconnect state (distinct from HALT).
        self._submission_paused = False
        self._paused_reason: Optional[str] = None
        # D-14 (V17-11): bounded pause-window protective-order replay queue.
        self._deferred_protective: "deque[Any]" = deque(maxlen=deferred_maxlen)

    def halt(self, reason: str) -> None:
        """Freeze-in-place halt of the whole engine (D-01/D-02/D-06/D-07).

        The conservative money-first response when the engine can no longer trust
        its own state (unexplained drift, unresolved reconciliation, a fatal
        connector error, a disconnect). Sets ``SystemStatus.HALTED`` with a
        machine-readable ``halt_reason`` and SUPPRESSES all NEW order submission
        (the SIGNAL/ORDER routes, gated in ``gate_and_dispatch``) while BAR/FILL
        streaming, reconciling and persisting CONTINUE to drain. It does NOT
        auto-flatten or auto-cancel: existing positions and resting orders stay
        exactly as they are (the engine just declared its own state untrustworthy,
        so it must not act on it). Idempotent — the first halt wins; a later halt
        with a different reason is a no-op.

        Emits ONE CRITICAL ``ErrorEvent`` so the halt reaches the operator through
        the injected alert sink (D-06); only declared ErrorEvent fields are bound,
        so no connector secret can leak (Pitfall 16, T-05-01).

        Parameters
        ----------
        reason : str
            Machine-readable halt reason (D-07) ∈ {drift,
            reconciliation-unresolved, connector-fatal, paused-on-disconnect}.
        """
        # WR-01 + D-05: atomic check-and-set routed through the SINGLE update_status
        # seam. update_status flips the status, sets the halt_reason and records
        # _last_error all under ONE _status_lock acquisition, and returns True ONLY for
        # the winning caller that actually flips a non-HALTED status to HALTED (a
        # re-entrant halt is a same-state no-op -> False). Two concurrent halt() callers
        # can therefore never BOTH pass the guard, both clobber halt_reason and both fire
        # the CRITICAL alert — only the winner reaches the emit below. HALTED is reachable
        # from every non-terminal state in VALID_STATUS_TRANSITIONS, so this flip is never
        # refused. The notify/callback runs OUTSIDE the lock, inside update_status.
        transitioned = self.update_status(
            SystemStatus.HALTED,
            error_msg=f'halt: {reason}',
            halt_reason=reason,
        )
        if not transitioned:
            return  # already halted — first reason wins (idempotent).
        # Winner only past here. Emit the SINGLE CRITICAL alert.
        # D-06: CRITICAL egress — routed through the EventHandler's ERROR route to
        # the injected alert sink. Only declared ErrorEvent fields are bound.
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
        # 05.2-06 (D-10 / ARCH-4 Layer 2): persist a DURABLE halt record so the HALTED
        # latch survives a process restart — a supervised auto-restart builds a FRESH
        # engine (in-process _status STOPPED) that would otherwise silently clear a
        # breaker halt whose cause is not re-detectable at start(). Reached ONLY by the
        # winning transition above, so a re-entrant (idempotent) halt never double-writes.
        # Bind ONLY the machine-readable reason literal + timestamp (V7 secret-scrub,
        # T-05.2-18; mirrors the ErrorEvent field-bind discipline) — never str(exc) or a
        # connector payload. Guarded on the store being present (in-memory fallback ->
        # no durable record, degrade cleanly).
        if self._halt_record_store is not None:
            self._halt_record_store.record_halt(reason, datetime.now(UTC))

    def is_halted(self) -> bool:
        """Whether the engine is in the freeze-in-place HALTED state (D-02)."""
        with self._status_lock:
            return self._status == SystemStatus.HALTED

    def reset_halt(self) -> bool:
        """Operator-only clear of the latched HALTED state (D-05, F/U-9).

        ``HALTED`` has NO legal exit in ``VALID_STATUS_TRANSITIONS`` — it is a latched
        safety state. This method is the SOLE sanctioned exit, deliberately OUTSIDE the
        transition table (a ``force=True`` write through the single ``update_status``
        seam) that returns the engine to ``STOPPED``. It does NOT re-open the trading
        gate itself: verify-then-trust means a subsequent ``start()`` re-runs
        reconciliation + the session-start baseline guard from a clean STOPPED baseline,
        so the halt cause is re-checked, never implicitly assumed resolved. Clearing the
        halt also clears the machine-readable ``halt_reason`` (handled in
        ``update_status`` when leaving HALTED). A no-op returning ``False`` when the
        engine is not currently HALTED.

        Returns
        -------
        bool
            ``True`` if a latched HALTED was cleared; ``False`` if the engine was not
            HALTED (no-op).
        """
        if not self.is_halted():
            self.logger.warning('reset_halt() ignored — engine is not HALTED')
            return False
        # force=True is the ONLY sanctioned bypass of the latch table (the HALTED exit).
        cleared = self.update_status(
            SystemStatus.STOPPED,
            error_msg='HALTED cleared by operator reset_halt()',
            force=True,
        )
        if cleared:
            # 05.2-06 (D-10): resolve the DURABLE halt record too, so the durable latch
            # does not re-refuse the next start() (F/U-9 verify-then-trust: that next
            # start() still re-runs reconciliation + the baseline guard from a clean
            # STOPPED baseline, so the halt cause is re-checked, never assumed resolved).
            # Guarded on the store being present (in-memory fallback -> no-op).
            if self._halt_record_store is not None:
                self._halt_record_store.resolve_all()
            self.logger.warning(
                'HALTED cleared by operator reset_halt() — engine returned to STOPPED; '
                'a subsequent start() will re-run reconciliation + the baseline guard '
                'before trading (verify-then-trust)')
        return cleared

    def is_submission_paused(self) -> bool:
        """Whether NEW order submission is reversibly paused on a disconnect (D-19)."""
        with self._status_lock:
            return self._submission_paused

    def status_snapshot(self) -> dict[str, Any]:
        """Read-only snapshot of the safety-owned status fields (D-07/D-19).

        The single read seam the facade's ``get_status`` merges with its stats + throttle
        breach counter. Returns the raw ``SystemStatus`` (the caller renders ``.value``),
        the machine-readable halt reason (``None`` unless HALTED), the reversible
        pause-on-disconnect flag + reason (surfaced DISTINCTLY from a terminal halt), and
        the last error string — all read under one ``_status_lock`` acquisition so the
        snapshot is internally consistent.
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
        """Reversibly pause NEW order submission on a venue-stream disconnect (D-19).

        Distinct from ``halt()``: this is a REVERSIBLE quiesce — streaming, reconciling
        and persisting continue, existing positions/orders are untouched, and
        ``resume_submission()`` (after reconnect + a fresh REST balance/position
        snapshot) clears it. A
        terminal HALT supersedes a pause, so this is a no-op while HALTED. Idempotent
        (a second pause with a new reason keeps the first). Thread-safe (a locked flag
        flip) so the connector-loop reconnect callback can call it without blocking I/O.

        Parameters
        ----------
        reason : str
            Machine-readable pause reason (D-07), e.g. ``'paused-on-disconnect'``.
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
        """Clear the reversible pause after reconnect + a fresh REST snapshot (D-19).

        D-14: once the pause flag is cleared, DRAIN the protective-order replay queue —
        each deferred protective order (bracket child / OCO / orphan cancel) is
        re-dispatched through the live gate. The pause flag is cleared FIRST
        (below), so the re-dispatch proceeds to ``_dispatch`` and is NOT re-suppressed
        (Assumption A4 — the drain runs after the flag clears).
        """
        with self._status_lock:
            if not self._submission_paused:
                return
            self._submission_paused = False
            self._paused_reason = None
        self.logger.info(
            'Order submission resumed — venue stream reconnected + fresh REST '
            'balance/position snapshot complete')
        # D-14: replay the protective orders deferred during the pause window.
        self._replay_deferred_protective()

    def _replay_deferred_protective(self) -> None:
        """Replay pause-deferred protective orders through the live gate on resume (D-14).

        Snapshots the replay queue into a local batch and CLEARS it before re-dispatching,
        so a re-dispatch that finds the engine HALTED (and re-defers) appends to the now-empty
        queue rather than spinning this drain forever. Each protective order is re-dispatched
        through the injected dispatch fn; with the pause flag already cleared it reaches
        ``_dispatch`` (Assumption A4). Bracket children / OCO cancels reach the venue so the
        just-filled position is no longer left naked.
        """
        if not self._deferred_protective:
            return
        batch = list(self._deferred_protective)
        self._deferred_protective.clear()
        self.logger.info(
            'Replaying %d deferred protective order(s) on resume (D-14)', len(batch))
        for deferred in batch:
            # Route back through the gate (not raw dispatch): with the pause flag
            # already cleared it passes to _dispatch, but a re-halt raised during the
            # replay re-defers onto the now-empty queue rather than sending blind (D-14).
            self.gate_and_dispatch(deferred)

    def gate_and_dispatch(
        self,
        event: Any,
        dispatch_fn: Optional[Callable[[Any], None]] = None,
    ) -> None:
        """Dispatch one event through the live halt/pause gate (D-02/D-14/D-19).

        The freeze-in-place gate: while HALTED (terminal) OR paused-on-disconnect
        (reversible), NEW order submission (the SIGNAL and ORDER routes) is gated, while
        BAR/FILL/ERROR streaming + reconciling + persisting continue to drain normally
        (so the venue stays mirrored and the halt itself — a CRITICAL ErrorEvent — is
        still consumed). Otherwise → a transparent pass-through.

        D-14 (V17-11): the gate does not blanket-suppress SIGNAL+ORDER. It branches by
        the shared ``classify`` risk role so risk-REDUCING commands are not silently
        dropped during the pause:
        (a) a CANCEL role ALWAYS passes through (a cancel only reduces risk);
        (b) a PROTECTIVE order (a bracket child — ``parent_order_id`` set) is DEFERRED
            onto the replay queue and replayed on resume (never left naked);
        (c) an ENTRY role (a fresh parentless NEW order, or any SIGNAL) stays SUPPRESSED
            — opening new risk while blind to the venue is what the pause exists to prevent.

        D-11: when the deferred-protective replay queue is FULL, an overflow escalates to
        ``halt`` + a CRITICAL alert (a 1000-deep backlog means something is deeply wrong)
        instead of the pre-D-11 silent drop-oldest (which could un-protect a position).

        ``dispatch_fn`` is the inner dispatch (the runner injects
        ``event_handler._dispatch``, §11a); it defaults to the injected canonical fn.
        """
        dispatch = dispatch_fn if dispatch_fn is not None else self._dispatch_fn
        if (self.is_halted() or self.is_submission_paused()) and getattr(
                event, 'type', None) in (EventType.SIGNAL, EventType.ORDER):
            event_type = getattr(getattr(event, 'type', None), 'name', 'UNKNOWN')
            role = classify(event)
            # (a) CANCEL always passes — a cancel only reduces risk (D-14).
            if role is OrderRiskRole.CANCEL:
                self.logger.info(
                    'CANCEL dispatched during pause/halt (D-14) — cancels always pass the '
                    'gate (risk-reducing)', event_type=event_type)
                if dispatch is not None:
                    dispatch(event)
                return
            # (b) a PROTECTIVE order (bracket child — parent set) is deferred for replay
            # on resume, not dropped (D-14) — the just-filled position stays protected.
            if role is OrderRiskRole.PROTECTIVE:
                # D-11: overflow escalates to HALT + CRITICAL instead of silent drop-oldest.
                # A full 1000-deep queue is pathological — convert the near-unreachable
                # silent drop (which could leave a position un-protected) into a loud,
                # latched stop. The offending order is NOT appended (no drop-oldest).
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
            # (c) fresh ENTRY order + SIGNAL stay suppressed (don't open new risk blind).
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
        """The SINGLE enforced status-mutation seam (D-05 / V17-03).

        This is the ONE point that writes ``self._status`` for a lifecycle transition
        (``__init__`` sets the initial STOPPED at construction; ``reset_halt`` is the
        one sanctioned off-table exit, routed here with ``force=True``). It enforces
        ``VALID_STATUS_TRANSITIONS``: a transition not in the current state's legal set
        is REFUSED (log-and-refuse, status left unchanged) rather than raised — the live
        event loop follows publish-and-continue (D-17), so an illegal transition must
        never abort it. ``HALTED`` has NO legal exit in the table, so once the reconciler
        or baseline guard halts the engine, no lifecycle transition (including the
        processing loop's RUNNING stamp) can clobber it — only ``reset_halt`` may.

        A same-state call is an idempotent no-op (returns ``False`` without notifying).

        Parameters
        ----------
        new_status : SystemStatus
            The target lifecycle state.
        error_msg : str, optional
            Recorded as ``self._last_error`` on a successful transition.
        halt_reason : str, optional
            The machine-readable halt reason (D-07), set ATOMICALLY with the flip under
            the same ``_status_lock`` acquisition. ``halt()`` routes its reason through
            here so the reason and the HALTED flip share one lock (WR-01 atomic
            check-and-set) — two concurrent ``halt()`` callers can never both win.
        force : bool
            Bypass the transition-table check. RESERVED for ``reset_halt``'s sanctioned
            HALTED exit only — do NOT use elsewhere (it defeats the latch).

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
                # F/U-8: log-and-refuse (never raise from the live loop). The message
                # binds only fixed enum literals — no connector context — so no secret
                # can leak on a halt-adjacent refusal (T-05.1-10, ASVS V7).
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
                # Leaving HALTED (only possible via reset_halt's forced exit) clears the
                # machine-readable reason so get_status() no longer surfaces a stale one.
                self._halt_reason = None

        # D-19 (RTCFG-06): persist the read-model ``state.*`` KV at THIS event source —
        # the winning transition only, OUTSIDE the lock (last-write-wins). ``state.status``
        # on every transition; ``state.halt_reason`` on a HALTED flip (its own key so the
        # UI reads the latched reason directly). Best-effort: a durable-write failure must
        # NEVER abort a status transition (a halt above all), so it is swallowed-and-logged.
        self._persist_state("state.status", {"status": new_status.value})
        if new_status == SystemStatus.HALTED and halt_reason is not None:
            self._persist_state("state.halt_reason", {"halt_reason": halt_reason})

        self._notify_status_change(old_status, new_status, error_msg)
        return True

    def _persist_state(self, key: str, value: dict[str, Any]) -> None:
        """Upsert a read-model ``state.*`` KV row (D-19) — best-effort, never raises.

        A no-op when no durable ``SystemStore`` is injected (backtest / in-memory
        fallback). A SQL-write failure (e.g. an un-migrated durable config schema) is
        swallowed-and-logged so a status transition — a halt above all — is never aborted
        by the read-model write (mirrors the ErrorHandler ``state.last_error`` discipline).
        The caller-free timestamp is the wall clock at the event source (a low-rate,
        discrete KV write, not a determinism-sensitive money value).
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
        """Log + fire the injected status callback OUTSIDE ``_status_lock`` (WR-01).

        Split out of ``update_status`` so ``halt()`` can flip the status UNDER the
        lock (atomic check-and-set) and still reuse the exact notification path once,
        for the winning caller only — the callback/log must never run holding the lock.
        The exchange/queue-size enrichment + the external ``status_callback`` are facade
        concerns, invoked through the injected ``notify_status_change`` callback so the
        pure state machine holds no facade handle.
        """
        self.logger.info(f'Status changed from {old_status.value} to {new_status.value}')

        if self._notify_status_change_cb is not None:
            try:
                self._notify_status_change_cb(old_status, new_status, error_msg)
            except Exception as e:
                self.logger.error(f'Error in status callback: {e}')

    def check_durable_halt_on_start(self) -> bool:
        """Refuse RUNNING on an unresolved durable halt record (SAFE-02, §11b).

        Runs FIRST at ``start()`` — right after STARTING and BEFORE any session init /
        venue connect / feed warmup / stream spawn / snapshot / reconcile. A supervised
        auto-restart builds a FRESH engine whose in-process ``_status`` is STOPPED, so a
        breaker halt whose cause is not re-detectable at start would be silently cleared.
        When an unresolved DURABLE record exists, RE-LATCH this fresh instance HALTED
        from the persisted reason via ``update_status`` (NOT ``halt()`` — ``halt()`` would
        write a SECOND durable record) and return ``True`` so the caller refuses RUNNING
        and stays INERT. A clean store (or in-memory fallback, or an already-HALTED
        engine) is a no-op returning ``False``. The full first-run wiring at the top of
        ``start()`` lands in Plan 06.

        Returns
        -------
        bool
            ``True`` if a durable halt re-latched this instance (caller must refuse
            RUNNING); ``False`` on a clean/absent store (a no-op).
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
        # Re-latch via update_status (NOT halt() — no second durable record write).
        self.update_status(
            SystemStatus.HALTED,
            error_msg=f'durable halt latched on restart: {durable_reason}',
            halt_reason=durable_reason)
        return True
