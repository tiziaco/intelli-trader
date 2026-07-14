"""WorkerSupervisor — the live poll-timer worker collaborator (RUN-02 / D-05).

The standalone §5 collaborator that owns the dynamic-universe poll-timer worker
lifecycle, extracted from ``LiveTradingSystem._run_poll_timer`` (the donor:
``live_trading_system.py:1852-1873``) plus its daemon-thread creation
(``:1836-1841``). ``LiveRunner`` COMPOSES this (has-a, constructor-injected) — it
does NOT inherit a shared runner base (D-05, composition-over-inheritance, the
live analog of ``compose_engine -> Engine -> BacktestRunner``).

The poll worker is the SOLE wall-clock event on the live path — control-plane
ONLY (Pitfall 3 / determinism): it stamps ONLY the control-plane
``UniversePollEvent``, and NEVER a bar/fill business ``time`` (business ``time``
stays venue-sourced). ``stop_event.wait(cadence)`` doubles as the interruptible
sleep so ``stop()`` unblocks it immediately. The cadence is INJECTED (read from
``monitoring.universe_poll_cadence_s`` by the caller), never a module literal.

Live-only and import-inert: imports only stdlib ``threading``/``datetime`` + the
events package + the ``EventBus`` seam (no ccxt.pro / no SQL on the backtest
import path — ``test_okx_inertness.py`` green). Unwired here; ``build_live_system``
(plan 06-05) composes it into ``LiveRunner``.

Indentation: 4 SPACES (matches the ``live_trading_system.py`` donor).
"""

import threading
from datetime import datetime, UTC
from typing import Optional

from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import UniversePollEvent
from itrader.logger import get_itrader_logger


class WorkerSupervisor:
    """Owns the dynamic-universe poll-timer daemon worker (D-05).

    Constructor injection only (no facade back-reference): the event bus/queue to
    ``.put`` the poll event onto, the shared ``stop_event`` (the same latch the
    ``LiveRunner`` drain loop honours), and the poll ``cadence`` in seconds (read
    from config by the caller — NOT hardcoded). ``start()``/``stop()`` manage the
    daemon thread; ``_run_poll_timer`` is the transplanted donor worker body.
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
        """Live-only dynamic-universe poll-timer daemon (Plan 06-05 / 07-07, D-02/D-06).

        Loops until ``stop_event`` is set, putting a control-plane ``UniversePollEvent``
        on the global queue every ``cadence`` seconds so the live
        ``UniverseHandler.on_poll`` polls its selection source DECOUPLED from bars
        (D-02) off its OWN dedicated ``UNIVERSE_POLL`` route (D-06/WR-06 — no longer the
        shared TIME route that also fans to screeners/bar-gen). This is the SOLE
        wall-clock event on the live path — it stamps ONLY the control-plane poll, and
        NEVER a bar/fill business time (Pitfall 3 / determinism: business ``time`` stays
        venue-sourced). Started only on the live daemon path, NEVER in the offline
        synchronous parity driver or the backtest. ``stop_event.wait(cadence)``
        doubles as the interruptible sleep so ``stop()`` unblocks it immediately.
        """
        while not self._stop_event.is_set():
            # Control-plane wall-clock UniversePollEvent ONLY (D-06/Pitfall 3): its own
            # discriminator, never a bar/fill business time, never the shared TIME route.
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
