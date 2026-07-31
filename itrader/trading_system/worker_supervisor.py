"""WorkerSupervisor — the live poll-timer worker collaborator.

Owns the dynamic-universe poll-timer worker lifecycle and its daemon thread.
``LiveRunner`` COMPOSES this (has-a, constructor-injected) rather than inheriting a
shared runner base — the live analog of ``build_handler_graph -> Engine ->
BacktestRunner``.

The poll worker is the SOLE wall-clock event on the live path, and control-plane ONLY:
it stamps the control-plane ``UniversePollEvent`` and NEVER a bar/fill business ``time``,
which stays venue-sourced. ``stop_event.wait(cadence)`` doubles as the interruptible
sleep so ``stop()`` unblocks it immediately. The cadence is INJECTED (read from
``config.universe.poll_cadence_s`` by the caller), never a module literal.

Live-only and import-inert: imports only stdlib ``threading``/``datetime`` plus the
events package and the ``EventBus`` seam, so no ccxt.pro and no SQL reach the backtest
import path.
"""

import threading
from datetime import datetime, UTC
from typing import Optional

from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import UniversePollEvent
from itrader.logger import get_itrader_logger


class WorkerSupervisor:
    """Owns the dynamic-universe poll-timer daemon worker.

    Constructor injection only, with no facade back-reference: the event bus to ``.put``
    the poll event onto, the shared ``stop_event`` (the same latch the ``LiveRunner``
    drain loop honours), and the poll ``cadence`` in seconds, read from config by the
    caller.
    """

    def __init__(
        self,
        bus: EventBus,
        stop_event: threading.Event,
        cadence: float,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="WorkerSupervisor")
        self._bus = bus
        self._stop_event = stop_event
        self._cadence = cadence
        self._thread: Optional[threading.Thread] = None

    def _run_poll_timer(self) -> None:
        """Live-only dynamic-universe poll-timer daemon.

        Loops until ``stop_event`` is set, putting a ``UniversePollEvent`` on the bus every
        ``cadence`` seconds so ``UniverseHandler.on_poll`` polls its selection source DECOUPLED
        from bars, off its OWN dedicated ``UNIVERSE_POLL`` route rather than the shared TIME
        route that also fans out to screeners and bar generation. Started only on the live
        daemon path — never in the offline synchronous parity driver or the backtest.
        """
        while not self._stop_event.is_set():
            # Control-plane wall-clock UniversePollEvent ONLY: its own discriminator, never a
            # bar/fill business time, never the shared TIME route.
            self._bus.put(UniversePollEvent(time=datetime.now(UTC)))
            self._stop_event.wait(self._cadence)

    def start(self) -> None:
        """Spawn the poll-timer daemon thread.

        The shared ``stop_event`` is cleared once by the composing ``LiveRunner``
        BEFORE this is called (both workers share the one latch), so ``start()``
        only creates and launches the daemon — it does not touch the event.
        """
        self._thread = threading.Thread(
            target=self._run_poll_timer,
            name='WorkerSupervisor-UniversePollTimer',
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the worker to stop and join its daemon thread.

        Setting ``stop_event`` is idempotent (the ``LiveRunner`` drain-loop stop
        typically sets it first); the ``stop_event.wait(cadence)`` sleep in
        ``_run_poll_timer`` unblocks immediately on the set, so the join returns
        promptly rather than waiting out a full cadence.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
