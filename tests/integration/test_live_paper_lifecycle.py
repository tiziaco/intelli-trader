"""Lifecycle / command-surface coverage for the live-paper engine (COV-01 / FL-13, D-10).

Behavior: exercise the ACCT-05 thin engine command surface that survived Phase-1's
``TradingInterface`` deletion — ``start()`` / ``stop(timeout)`` / ``get_status()`` /
``is_running()`` — offline and deterministically. The system is constructed on the
``'paper'`` venue (the 04-02 replay arm), so NO OKX network I/O happens on this path;
the real-connector smoke against ``OkxDataProvider`` is a MANUAL/opt-in test (D-11),
never on the CI gate.

The three cases:
  (1) clean startup   — start() is True, is_running() is True, get_status() reports
                        RUNNING with the expected keys.
  (2) graceful stop   — stop(timeout) is True, the daemon thread joins (no dangling:
                        is_running() False and thread_alive False), a second stop() is
                        a safe no-op returning True.
  (3) status-before-start — a freshly constructed (never-started) system reports
                        STOPPED / is_running False without raising.

Every test stops the system (try/finally) so no daemon thread leaks across tests — a
leaked thread under ``filterwarnings=["error"]`` would fail the suite. The
``integration`` marker is applied AUTOMATICALLY by the ``tests/integration/`` path
(root-conftest folder-derived TYPE auto-marking) — it is NOT hand-added here.
"""

import time
from decimal import Decimal

from itrader.core.enums import SystemStatus
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.live_trading_system import LiveTradingSystem
from tests.support.replay_harness import build_paper_replay_system

# The expected key set the ACCT-05 command surface must report (D-10).
_EXPECTED_STATUS_KEYS = {"status", "is_running", "exchange", "queue_size", "statistics"}


def _build_paper_system() -> LiveTradingSystem:
    """Construct a paper-venue system wired with the golden strategy + a portfolio.

    Mirrors the worker composition: the golden SMA_MACD literals + a single
    ``'paper'``-exchange portfolio. Production paper re-points to the OKX live feed
    (D-21), so the offline replay DATA provider is injected via
    ``build_paper_replay_system`` — no OKX credentials or network needed (D-11).
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
        name="paper_pf",
        exchange="paper",
        cash=10_000,
    )
    strategy.subscribe_portfolio(portfolio_id)
    return system


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` up to ``timeout`` seconds; return True as soon as it holds.

    The processing thread sets ``SystemStatus.RUNNING`` asynchronously after
    ``start()`` returns, so status assertions poll rather than read once.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_clean_startup_reports_running():
    """(1) start() -> True, is_running() True, get_status() RUNNING with the expected keys."""
    system = _build_paper_system()
    try:
        assert system.start() is True
        assert system.is_running() is True

        # RUNNING is set on the processing thread — poll for it (bounded).
        assert _wait_until(
            lambda: system.get_status()["status"] == SystemStatus.RUNNING.value
        )

        status = system.get_status()
        assert _EXPECTED_STATUS_KEYS <= set(status.keys())
        assert status["exchange"] == "paper"
        assert status["is_running"] is True
        assert isinstance(status["statistics"], dict)
    finally:
        system.stop(timeout=5.0)


def test_graceful_stop_joins_thread():
    """(2) stop(timeout) -> True, thread joins (no dangling), second stop() is a no-op True."""
    system = _build_paper_system()
    assert system.start() is True
    assert _wait_until(lambda: system.is_running())

    # Graceful stop: returns True and the daemon thread joins within the timeout.
    assert system.stop(timeout=5.0) is True

    # No dangling thread: is_running() False and the status reports the thread dead.
    assert system.is_running() is False
    assert system.get_status()["thread_alive"] is False

    # A second stop() on an already-stopped system is a safe no-op returning True.
    assert system.stop(timeout=5.0) is True


def test_status_before_start_reports_stopped():
    """(3) a freshly constructed (never-started) system reports STOPPED / not running."""
    system = _build_paper_system()

    status = system.get_status()
    assert status["status"] == SystemStatus.STOPPED.value
    assert status["is_running"] is False
    assert system.is_running() is False
    # No thread was ever started, so thread_alive is False and nothing leaks.
    assert status["thread_alive"] is False
