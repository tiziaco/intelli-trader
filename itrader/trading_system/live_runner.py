"""LiveRunner — owns the live drain loop (RUN-02 / D-05/D-06/D-07/D-08).

The live runtime engine: the daemon-thread drain loop transplanted from
``LiveTradingSystem._event_processing_loop`` (``live_trading_system.py:1526-1608``,
which it replaces, D-06). This is the live analog of
``compose_engine -> Engine -> BacktestRunner`` — a composition-over-inheritance
runtime (``build_live_system -> ... -> LiveRunner -> facade``) with a STABLE
constructor P7/P8 fill in without re-touching.

Composition, not inheritance:
- D-05: COMPOSES ``WorkerSupervisor`` (has-a, constructor-injected) for the
  poll-timer worker — it does NOT subclass a shared runner base.
- D-06/D-07 (08-03): the handler-failure policy is NO LONGER carried here. It is
  injected at ``EventHandler.__init__`` in ``compose_engine`` (the live
  publish-and-continue policy on the daemon path); LiveRunner never held or
  installed it, so the dead handler-failure-policy constructor param was removed.
- D-08: takes an injected ``dispatch_gate`` callback (P7 repoints it to
  ``SafetyController.gate_and_dispatch``).
- D-06 (SAFE-03 / A3): takes an injected ``pre_submit(event) -> bool`` callable — the
  ``PreTradeThrottle`` at the ORDER->execution boundary, invoked AHEAD of the dispatch
  gate for ORDER events. When it returns ``False`` (the throttle rejected the order and
  already emitted ``FillEvent(REFUSED)``) the runner SKIPS the dispatch gate for that event.
- D-04: the surviving per-tick post-dispatch side-effects (dispatch-stats,
  record-bar-metrics) are reached via INJECTED CALLABLES, so the facade's
  ``_update_stats`` / ``_record_bar_metrics`` bodies stay in ``live_trading_system.py``.
  P7 DELETED the ``resume-after-reconnect`` / ``halt-after-connector-fatal`` per-tick
  drain hooks — the connector stream/fatal handoff is now CONTROL events (STREAM_STATE /
  CONNECTOR_FATAL) that wake ``bus.get()`` naturally and route on the engine thread, so
  the flag side-channel + its per-tick drains are gone (Pitfall 3).

``queue_timeout``/``max_idle_time`` are INJECTED config/spec values (D-06), read
from config by the caller — NOT constructor knobs the caller must remember /
re-derive. Import-inert: imports only stdlib ``threading``/``queue``/``datetime``
+ the ``EventBus`` seam + the two sibling collaborators (no ccxt.pro / no SQL on
the backtest import path — ``test_okx_inertness.py`` green). Unwired here;
``build_live_system`` (plan 06-05) composes and wires it, then removes the old
``_event_processing_loop``/``_run_poll_timer``/``_publish_and_continue``.

Indentation: 4 SPACES (matches the ``live_trading_system.py`` donor).
"""

import queue
import threading
from datetime import datetime, UTC
from typing import Any, Callable, Optional

from itrader.core.enums import EventType
from itrader.events_handler.bus import EventBus
from itrader.logger import get_itrader_logger
from itrader.trading_system.worker_supervisor import WorkerSupervisor


class LiveRunner:
    """Owns the live daemon-thread drain loop; composes WorkerSupervisor (D-05/D-06).

    Pure injection — NO facade God-object reference. The loop mirrors the donor
    ``_event_processing_loop`` verbatim, reaching every still-in-facade side-effect
    (the D-08 dispatch gate + the D-04 per-tick hooks + the loop-lifecycle status /
    stats bookkeeping) through injected callables so the facade bodies stay put.
    """

    def __init__(
        self,
        bus: EventBus,
        stop_event: threading.Event,
        worker_supervisor: WorkerSupervisor,
        dispatch_gate: Callable[[Any], None],
        update_stats: Callable[[str], None],
        record_bar_metrics: Callable[[Any], None],
        pre_submit: Callable[[Any], bool],
        queue_timeout: float,
        max_idle_time: float,
        on_loop_start: Optional[Callable[[], None]] = None,
        on_loop_error: Optional[Callable[[BaseException], None]] = None,
        on_order_throttle_rejected: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Parameters
        ----------
        bus : EventBus
            The shared event transport — ``get(timeout=)`` dequeues, drains the loop.
        stop_event : threading.Event
            The shared stop latch honoured by BOTH the drain loop and the composed
            ``WorkerSupervisor``. Cleared once here in ``start()``.
        worker_supervisor : WorkerSupervisor
            The composed poll-timer worker (D-05, has-a). Started/stopped alongside
            the drain thread.
        dispatch_gate : Callable[[event], None]
            The D-08 injected dispatch gate (P7 -> ``SafetyController.gate_and_dispatch``).
            Called per dequeued event (unless ``pre_submit`` rejected an ORDER).
        pre_submit : Callable[[event], bool]
            The D-06/A3 pre-submit throttle (``PreTradeThrottle.allow``), invoked for
            ORDER events AHEAD of the dispatch gate. ``False`` == rejected (the throttle
            already emitted ``FillEvent(REFUSED)``), so the runner SKIPS the gate for it.
        update_stats, record_bar_metrics : Callable
            The D-04 per-tick post-dispatch hooks — the facade method BODIES stay
            put; the loop calls them via these injected callables.
        queue_timeout, max_idle_time : float
            Injected config/spec values (D-06) — read from config by the caller.
        on_loop_start : Callable[[], None], optional
            Loop-entry hook (facade: ``_update_status(RUNNING)`` + ``uptime_start``
            stamp). Injected so the facade status/stats bookkeeping stays put.
        on_loop_error : Callable[[BaseException], None], optional
            Loop catch-all hook (facade: ``_stats['errors_count'] += 1``).
        on_order_throttle_rejected : Callable[[], None], optional
            WR-02 hook: a pre-submit-throttle-REFUSED ORDER. Called INSTEAD of
            ``update_stats`` for a rejected order so the facade counts it as processed
            but NOT executed (facade: ``_stats['orders_throttle_rejected'] += 1``),
            never bumping ``orders_executed`` for an order that never executed.
        """
        self.logger = get_itrader_logger().bind(component="LiveRunner")
        self._bus = bus
        self._stop_event = stop_event
        self._worker_supervisor = worker_supervisor
        self._dispatch_gate = dispatch_gate
        self._update_stats = update_stats
        self._record_bar_metrics = record_bar_metrics
        self._pre_submit = pre_submit
        self._queue_timeout = queue_timeout
        self._max_idle_time = max_idle_time
        self._on_loop_start = on_loop_start
        self._on_loop_error = on_loop_error
        self._on_order_throttle_rejected = on_order_throttle_rejected
        self._thread: Optional[threading.Thread] = None

    def _run_loop(self) -> None:
        """The main event processing loop that runs on the daemon thread.

        Continuously drains events from the bus until ``stop_event`` is set.
        Mirrors the donor ``_event_processing_loop`` verbatim, reaching the
        facade side-effects through the injected callables (D-04/D-08).
        """
        self.logger.info('Starting event processing loop')
        # Loop-entry facade bookkeeping (status RUNNING stamp + uptime_start),
        # reached via the injected hook so the facade body stays put (D-04).
        if self._on_loop_start is not None:
            self._on_loop_start()

        last_event_time = datetime.now(UTC)

        while not self._stop_event.is_set():
            try:
                # Check for events in the queue with timeout
                try:
                    event = self._bus.get(timeout=self._queue_timeout)
                    last_event_time = datetime.now(UTC)

                    # D-06 (SAFE-03 / A3): the pre-submit throttle fires at the
                    # ORDER->execution boundary, AHEAD of the dispatch gate. It meters
                    # ONLY ORDER events (the throttle's own shared classifier bypasses
                    # CANCEL/PROTECTIVE uncounted); a rejected ORDER already emitted a
                    # FillEvent(REFUSED), so SKIP the dispatch gate for it. Non-ORDER
                    # events go straight to the gate.
                    rejected = (
                        getattr(event, 'type', None) is EventType.ORDER
                        and not self._pre_submit(event))
                    if not rejected:
                        # WR-09: dispatch the dequeued event through the event handler's
                        # routing (the injected D-08 dispatch gate). 05-04 (D-02): the
                        # gate routes through the freeze-in-place halt gate so a HALTED
                        # engine suppresses NEW order submission (SIGNAL/ORDER) while
                        # BAR/FILL/ERROR streaming + reconciling + persisting continue.
                        self._dispatch_gate(event)
                        # Update statistics (D-04: facade _update_stats body stays put).
                        self._update_stats(
                            event.type.name if hasattr(event, 'type') else 'UNKNOWN')
                    elif self._on_order_throttle_rejected is not None:
                        # WR-02: a throttle-REFUSED ORDER never executed (it emitted only
                        # a FillEvent(REFUSED)); count it as processed-not-executed via the
                        # dedicated hook so orders_executed is NEVER over-reported. The
                        # hook is always wired by build_live_system; if absent, the order
                        # is simply left uncounted (never mis-counted as executed).
                        self._on_order_throttle_rejected()

                    # 05-06 (D-16 / WR-01): record the per-bar equity curve keyed on
                    # EventType.BAR (the async/best-effort path). Facade body stays
                    # put; reached via the injected hook (D-04).
                    self._record_bar_metrics(event)

                except queue.Empty:
                    # P7: the connector stream/fatal handoff is now CONTROL events
                    # (STREAM_STATE / CONNECTOR_FATAL) that wake bus.get() naturally, so
                    # there is no idle-spell flag to drain here (the old per-tick resume /
                    # halt drains are deleted — Pitfall 3).
                    # No events in queue, check if we've been idle too long
                    current_time = datetime.now(UTC)
                    idle_time = (current_time - last_event_time).total_seconds()

                    if idle_time > self._max_idle_time:
                        self.logger.warning(
                            f'No events received for {idle_time:.1f} seconds')
                        last_event_time = current_time

                    continue

            except Exception as e:
                self.logger.error(f'Error in event processing loop: {e}')
                # Facade _stats['errors_count'] += 1, reached via the injected hook.
                if self._on_loop_error is not None:
                    self._on_loop_error(e)
                # Continue processing even if there's an error
                continue

        self.logger.info('Event processing loop stopped')

    def start(self) -> None:
        """Spawn the drain-loop daemon thread AND start the composed worker.

        Clears the shared ``stop_event`` ONCE (both the drain loop and the
        ``WorkerSupervisor`` poll worker honour it), then spawns the drain thread
        and starts the supervisor.
        """
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name='LiveRunner-EventProcessor',
            daemon=True,
        )
        self._thread.start()
        self._worker_supervisor.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Set the stop latch, join the drain thread, then stop the composed worker."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                self.logger.warning(
                    "LiveRunner drain thread did not stop within %.1fs; "
                    "still alive after join",
                    timeout,
                )
        self._worker_supervisor.stop(timeout=timeout)
