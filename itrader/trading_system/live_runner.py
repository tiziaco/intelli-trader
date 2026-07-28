"""LiveRunner — owns the live drain loop.

The live runtime engine: the daemon-thread loop that drains ``bus`` and dispatches
each event, composing a ``WorkerSupervisor`` (has-a, constructor-injected) for the
poll-timer worker rather than subclassing a shared runner base. It holds no facade
reference; every side-effect that must stay on ``LiveTradingSystem`` (the dispatch
gate, the pre-submit throttle, per-tick stats/metrics hooks, loop lifecycle hooks)
is reached through an injected callable.

Ordering constraint: the injected ``pre_submit`` throttle runs AHEAD of
``dispatch_gate`` for ORDER events. When it returns ``False`` (it already emitted
``FillEvent(REFUSED)``) the loop SKIPS the dispatch gate for that event — a
rejected order must never also clear the gate.

``queue_timeout``/``max_idle_time`` are injected config/spec values, read from
config by the caller, never re-derived here. Import-inert: imports only stdlib
``threading``/``queue``/``datetime`` + the ``EventBus`` seam + the two sibling
collaborators (no ccxt.pro / no SQL on the backtest import path).
``build_live_system`` composes and wires it.

Indentation: 4 spaces (matches ``live_trading_system.py``).
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
    """Owns the live daemon-thread drain loop; composes ``WorkerSupervisor``.

    Pure injection — no facade reference. Every side-effect that must stay on the
    facade (the dispatch gate, the pre-submit throttle, per-tick stats/metrics,
    loop lifecycle hooks) is reached through an injected callable.
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
            The composed poll-timer worker (has-a). Started/stopped alongside the
            drain thread.
        dispatch_gate : Callable[[event], None]
            The injected dispatch gate (``SafetyController.gate_and_dispatch`` in
            production). Called per dequeued event (unless ``pre_submit`` rejected
            an ORDER).
        pre_submit : Callable[[event], bool]
            The pre-submit throttle (``PreTradeThrottle.allow``), invoked for ORDER
            events AHEAD of the dispatch gate. ``False`` == rejected (the throttle
            already emitted ``FillEvent(REFUSED)``), so the runner SKIPS the gate for it.
        update_stats, record_bar_metrics : Callable
            Per-tick post-dispatch hooks — the facade method bodies stay put; the
            loop calls them via these injected callables.
        queue_timeout, max_idle_time : float
            Injected config/spec values, read from config by the caller.
        on_loop_start : Callable[[], None], optional
            Loop-entry hook (facade: status RUNNING stamp + ``uptime_start`` stamp).
        on_loop_error : Callable[[BaseException], None], optional
            Loop catch-all hook (facade: ``_stats['errors_count'] += 1``).
        on_order_throttle_rejected : Callable[[], None], optional
            A pre-submit-throttle-REFUSED ORDER hook. Called INSTEAD of
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

        Continuously drains events from the bus until ``stop_event`` is set,
        reaching every facade side-effect through the injected callables.
        """
        self.logger.info('Starting event processing loop')
        if self._on_loop_start is not None:
            self._on_loop_start()

        last_event_time = datetime.now(UTC)

        while not self._stop_event.is_set():
            try:
                try:
                    event = self._bus.get(timeout=self._queue_timeout)
                    last_event_time = datetime.now(UTC)

                    # The pre-submit throttle fires at the ORDER->execution boundary,
                    # AHEAD of the dispatch gate. It meters ONLY ORDER events (its
                    # shared classify predicate bypasses CANCEL/PROTECTIVE uncounted);
                    # a rejected ORDER already emitted a FillEvent(REFUSED), so the
                    # dispatch gate is SKIPPED for it. Non-ORDER events go straight to
                    # the gate.
                    rejected = (
                        getattr(event, 'type', None) is EventType.ORDER
                        and not self._pre_submit(event))
                    if not rejected:
                        # While HALTED/paused this suppresses NEW SIGNAL/ORDER
                        # submission while BAR/FILL/ERROR streaming + reconciling +
                        # persisting continue.
                        self._dispatch_gate(event)
                        self._update_stats(
                            event.type.name if hasattr(event, 'type') else 'UNKNOWN')
                    elif self._on_order_throttle_rejected is not None:
                        # A throttle-REFUSED ORDER never executed (only a
                        # FillEvent(REFUSED) was emitted); count it here as
                        # processed-not-executed so orders_executed is never
                        # over-reported. If the hook is absent the order is simply
                        # left uncounted, never mis-counted as executed.
                        self._on_order_throttle_rejected()

                    self._record_bar_metrics(event)

                except queue.Empty:
                    # STREAM_STATE / CONNECTOR_FATAL are ordinary queued events that
                    # wake bus.get() naturally; idle time is tracked only to warn on
                    # data silence, not to drain any control flag here.
                    current_time = datetime.now(UTC)
                    idle_time = (current_time - last_event_time).total_seconds()

                    if idle_time > self._max_idle_time:
                        self.logger.warning(
                            f'No events received for {idle_time:.1f} seconds')
                        last_event_time = current_time

                    continue

            except Exception as e:
                self.logger.error(f'Error in event processing loop: {e}')
                if self._on_loop_error is not None:
                    self._on_loop_error(e)
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
