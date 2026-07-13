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
- D-07: takes an injected ``ErrorPolicy`` (the minimal live publish-and-continue
  seam). LiveRunner HOLDS it for the wiring layer; it does NOT itself install the
  ``EventHandler._on_handler_error`` monkeypatch — that wiring is 06-05/D-07.
- D-08: takes an injected ``dispatch_gate`` callback (wired in 06-05 to the
  facade's untouched ``_dispatch_live``; P7 repoints it to ``SafetyController`` —
  the D-04 method BODIES stay put).
- D-04: the per-tick post-dispatch side-effects (dispatch-stats, record-bar-metrics,
  resume-after-reconnect, halt-after-connector-fatal) are reached via INJECTED
  CALLABLES, so the facade's ``_dispatch_live``/``_maybe_resume_after_reconnect``/
  ``_maybe_halt_after_connector_fatal``/``_record_bar_metrics``/``_update_stats``
  method BODIES stay in ``live_trading_system.py`` (this plan does NOT touch them).

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

from itrader.events_handler.bus import EventBus
from itrader.logger import get_itrader_logger
from itrader.trading_system.error_policy import ErrorPolicy
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
        error_policy: ErrorPolicy,
        worker_supervisor: WorkerSupervisor,
        dispatch_gate: Callable[[Any], None],
        update_stats: Callable[[str], None],
        record_bar_metrics: Callable[[Any], None],
        resume_after_reconnect: Callable[[], None],
        halt_after_connector_fatal: Callable[[], None],
        queue_timeout: float,
        max_idle_time: float,
        on_loop_start: Optional[Callable[[], None]] = None,
        on_loop_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        """
        Parameters
        ----------
        bus : EventBus
            The shared event transport — ``get(timeout=)`` dequeues, drains the loop.
        stop_event : threading.Event
            The shared stop latch honoured by BOTH the drain loop and the composed
            ``WorkerSupervisor``. Cleared once here in ``start()``.
        error_policy : ErrorPolicy
            The minimal live publish-and-continue seam (D-07). HELD for the 06-05
            wiring layer (which installs ``error_policy.on_handler_error`` on the
            EventHandler); the loop itself does not install the monkeypatch.
        worker_supervisor : WorkerSupervisor
            The composed poll-timer worker (D-05, has-a). Started/stopped alongside
            the drain thread.
        dispatch_gate : Callable[[event], None]
            The D-08 injected dispatch gate (06-05 -> facade ``_dispatch_live``;
            P7 -> ``SafetyController``). Called per dequeued event.
        update_stats, record_bar_metrics, resume_after_reconnect,
        halt_after_connector_fatal : Callable
            The D-04 per-tick post-dispatch hooks — the facade method BODIES stay
            put; the loop calls them via these injected callables.
        queue_timeout, max_idle_time : float
            Injected config/spec values (D-06) — read from config by the caller.
        on_loop_start : Callable[[], None], optional
            Loop-entry hook (facade: ``_update_status(RUNNING)`` + ``uptime_start``
            stamp). Injected so the facade status/stats bookkeeping stays put.
        on_loop_error : Callable[[BaseException], None], optional
            Loop catch-all hook (facade: ``_stats['errors_count'] += 1``).
        """
        self.logger = get_itrader_logger().bind(component="LiveRunner")
        self._bus = bus
        self._stop_event = stop_event
        # HELD for 06-05 wiring (installs it on the EventHandler); not called here.
        self._error_policy = error_policy
        self._worker_supervisor = worker_supervisor
        self._dispatch_gate = dispatch_gate
        self._update_stats = update_stats
        self._record_bar_metrics = record_bar_metrics
        self._resume_after_reconnect = resume_after_reconnect
        self._halt_after_connector_fatal = halt_after_connector_fatal
        self._queue_timeout = queue_timeout
        self._max_idle_time = max_idle_time
        self._on_loop_start = on_loop_start
        self._on_loop_error = on_loop_error
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

                    # WR-09: dispatch the dequeued event DIRECTLY through the
                    # event handler's routing (the injected D-08 dispatch gate).
                    # 05-04 (D-02): the gate routes through the freeze-in-place halt
                    # gate so a HALTED engine suppresses NEW order submission
                    # (SIGNAL/ORDER) while BAR/FILL/ERROR streaming + reconciling +
                    # persisting continue to drain.
                    self._dispatch_gate(event)

                    # Update statistics (D-04: facade _update_stats body stays put).
                    self._update_stats(
                        event.type.name if hasattr(event, 'type') else 'UNKNOWN')

                    # 05-06 (D-16 / WR-01): record the per-bar equity curve keyed on
                    # EventType.BAR (the async/best-effort path). Facade body stays
                    # put; reached via the injected hook (D-04).
                    self._record_bar_metrics(event)

                    # 05-08 (D-19): resume submission on the ENGINE thread once a venue
                    # stream reconnected — a fresh REST snapshot then clears the pause.
                    # Facade body stays put; injected hook (D-04, Pitfall 9).
                    self._resume_after_reconnect()

                    # 05.3-08 (D-21 / WR-02): drain a pending connector-fatal escalation
                    # on the ENGINE thread — the blocking durable record_halt write runs
                    # in the facade body, never on the connector asyncio loop (Pitfall 9).
                    self._halt_after_connector_fatal()

                except queue.Empty:
                    # 05-08 (D-19): drain a pending resume even when the queue is idle —
                    # a reconnect during a quiet spell must still resume submission.
                    self._resume_after_reconnect()

                    # 05.3-08 (D-21 / WR-02): drain a pending connector-fatal even when
                    # the queue is idle — a fatal during a quiet spell must still halt.
                    self._halt_after_connector_fatal()

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
        self._worker_supervisor.stop(timeout=timeout)
