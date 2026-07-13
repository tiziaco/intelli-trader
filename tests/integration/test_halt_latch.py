"""A3 (D-05 / V17-03) RED gate — a reconcile-time HALT must LATCH across ``start()``.

CONF-A spine (D-19), Wave-1 slice 2. This is an EXPECTED-FAILING regression test: it
pins the V17-03 HALTED-latch-bypass bug and turns GREEN only once the D-05 status-latch
lands in plan 05.1-05. It MUST be RED against current code — that is the success
condition of a CONF-A spine plan, NOT a broken build.

The bug (V17-03)
----------------
On the real OKX arm, ``start()`` runs ``VenueReconciler.reconcile()`` on the engine
thread BEFORE the processing thread spawns (live_trading_system.py:1147-1155). When the
reconciler cannot trust venue state it calls its injected ``halt_signal`` — i.e.
``self.halt("reconciliation-unresolved")`` — which sets ``SystemStatus.HALTED``. But
``start()`` never checks ``_is_halted()`` afterward, and the processing loop's FIRST
action is an UNCONDITIONAL ``self._update_status(SystemStatus.RUNNING)`` at
live_trading_system.py:993. That blind stamp CLOBBERS the halt: the engine opens the
SIGNAL/ORDER gate and trades on state the reconciler already declared untrustworthy.

Offline reproduction (no OKX network / credentials)
---------------------------------------------------
The system is built on the ``'paper'`` venue (the 04-02 replay arm), which skips the
OKX reconcile branch entirely, so we inject the reconcile-time halt at the equivalent
point: ``_initialize_live_session`` runs in ``start()`` immediately before the OKX
reconcile branch would, so wrapping it to call ``halt("reconciliation-unresolved")``
lands the halt during ``start()`` with the IDENTICAL ordering the real reconciler
produces — before the thread spawns and before the loop's RUNNING stamp. No network,
no credentials, no OKX client is touched.

Expected today (RED): the loop clobbers HALTED -> RUNNING, so ``get_status()["status"]``
reports ``"running"`` while ``halt_reason`` is still ``"reconciliation-unresolved"``.
Expected after 05.1-05 (D-05): ``_update_status`` refuses HALTED->RUNNING and ``start()``
checks ``_is_halted()`` post-reconcile, so the status LATCHES at ``"halted"``.

The ``integration`` marker is applied AUTOMATICALLY by the ``tests/integration/`` path
(folder-derived TYPE auto-marking). The system is always stopped in a ``finally`` so no
daemon thread leaks across tests — a leaked thread under ``filterwarnings=["error"]``
would fail the suite.
"""

import time
from decimal import Decimal

from itrader.core.enums import SystemStatus
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.replay_harness import build_paper_replay_system


def _build_paper_system() -> LiveTradingSystem:
    """A fully offline paper-venue system (mirrors test_live_paper_lifecycle wiring).

    Production paper re-points to the OKX live feed (D-21), so the offline replay DATA
    provider is injected via ``build_paper_replay_system`` (the paper↔replay pairing now
    lives ONLY in the test harness).
    """
    system, _ = build_paper_replay_system()
    strategy = SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="halt_latch_pf",
        exchange="simulated",
        cash=10_000,
    )
    strategy.subscribe_portfolio(portfolio_id)
    return system


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` up to ``timeout`` seconds; return its final truth value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def _inject_reconcile_halt(system: LiveTradingSystem, reason: str) -> None:
    """Wrap ``_initialize_live_session`` so a reconcile-time ``halt(reason)`` fires
    during ``start()`` — before the processing thread spawns and stamps RUNNING.

    This stands in for the OKX ``VenueReconciler.reconcile()`` halt_signal call
    (live_trading_system.py:1152-1155). ``_initialize_live_session`` is the last step
    ``start()`` runs before the OKX reconcile branch, so the halt lands with the exact
    ordering the real reconciler produces on the OKX arm.
    """
    original_init = system._initialize_live_session

    def _init_then_reconcile_halt() -> None:
        original_init()
        system.halt(reason)

    system._initialize_live_session = _init_then_reconcile_halt  # type: ignore[method-assign]


def test_start_after_reconcile_halt_stays_halted() -> None:
    """A reconcile-time ``halt`` during ``start()`` must LATCH — status stays 'halted'.

    RED today: the loop's unconditional RUNNING stamp (:993) clobbers the halt, so the
    status reports 'running'. GREEN after D-05 (05.1-05) latches HALTED.
    """
    system = _build_paper_system()
    _inject_reconcile_halt(system, "reconciliation-unresolved")
    try:
        system.start()

        # The processing loop's FIRST action is _update_status(RUNNING) at :993; give
        # it a bounded window to run so we observe the clobber deterministically rather
        # than reading the transient pre-clobber HALTED (which would false-pass). On
        # the D-05-fixed engine this wait simply times out (status never leaves HALTED).
        _wait_until(
            lambda: system.get_status()["status"] == SystemStatus.RUNNING.value,
            timeout=3.0,
        )

        status = system.get_status()
        # A reconcile declared the engine's state untrustworthy — HALTED must latch.
        assert status["status"] == SystemStatus.HALTED.value, (
            "D-05 latch missing (V17-03): the reconcile-time halt was clobbered by the "
            f"loop's RUNNING stamp — status={status['status']!r}, "
            f"halt_reason={status['halt_reason']!r} (expected a latched 'halted')"
        )
        # The machine-readable reason survives regardless of the clobber.
        assert status["halt_reason"] == "reconciliation-unresolved"
    finally:
        system.stop(timeout=5.0)
