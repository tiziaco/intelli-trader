"""Root pytest configuration for the iTrader test suite.

This single root conftest (D-15) provides two things:

1. Path-based marker auto-marking (D-14) via ``pytest_collection_modifyitems``.
   Each collected item's directory is mapped to one of the eight declared markers
   so the 30 legacy ``unittest.TestCase`` files get markers applied at collection
   time with ZERO edits to those files. Marks apply to unittest items because
   pytest wraps their methods as collected items before this hook runs.

2. Shared fixtures: a fresh ``global_queue``, golden-file path fixtures, and a
   ``backtest_engine`` factory. The factory is LAZILY constructed: the TradingSystem
   (and any reference to the not-yet-existing ``csv`` exchange branch that lands in a
   later plan) is built INSIDE the inner factory body, so this module imports cleanly
   and ``pytest --collect-only`` succeeds for every legacy test today.
"""

import pathlib
import queue

import pytest

# Directory segment -> declared marker (must match the 8 markers in pyproject.toml:
# unit, integration, slow, portfolio, events, orders, execution, strategy).
DIR_MARKERS = {
    "test_portfolio_handler": "portfolio",
    "test_positions": "portfolio",
    "test_transaction": "portfolio",
    "test_events": "events",
    "test_order_handler": "orders",
    "test_execution_handler": "execution",
    "test_strategy": "strategy",
    "test_integration": "integration",
    "test_smoke": "unit",
}


def pytest_collection_modifyitems(config, items):
    """Apply markers by path segment (D-14).

    Works on legacy ``unittest.TestCase`` items because pytest has already wrapped
    them as collected items by the time this hook runs; ``item.add_marker`` applies
    regardless of whether the underlying test is unittest-native or pytest-native.
    """
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        for segment, marker in DIR_MARKERS.items():
            if segment in parts:
                item.add_marker(getattr(pytest.mark, marker))
        # Integration tests are also slow (D-16).
        if "test_integration" in parts:
            item.add_marker(pytest.mark.slow)


# --- Shared fixtures (D-15) -------------------------------------------------

# Repo root = parent of the ``test/`` directory holding this conftest.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_GOLDEN_DIR = pathlib.Path(__file__).resolve().parent / "golden"


@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test (constructor convention: ``queue.Queue``)."""
    return queue.Queue()


@pytest.fixture
def golden_dir():
    """Path to the committed frozen-oracle directory (test/golden/)."""
    return _GOLDEN_DIR


@pytest.fixture
def golden_trades_path():
    """Path to the frozen trade-log CSV."""
    return _GOLDEN_DIR / "trades.csv"


@pytest.fixture
def golden_equity_path():
    """Path to the frozen equity-curve CSV."""
    return _GOLDEN_DIR / "equity.csv"


@pytest.fixture
def golden_summary_path():
    """Path to the frozen summary JSON."""
    return _GOLDEN_DIR / "summary.json"


@pytest.fixture
def backtest_engine():
    """Factory that builds a CSV-fed backtest ``TradingSystem``.

    Returns a callable so construction is DEFERRED until a test actually invokes it.
    The TradingSystem import and any reference to the ``csv`` exchange branch (which
    lands in a later plan) live inside the inner function body — never at module
    import time and never in this fixture's outer body — so ``--collect-only``
    succeeds for all legacy tests even though the CSV feed does not exist yet.
    """

    def _make(
        ticker="BTCUSD",
        timeframe="1d",
        start_date="2018-01-01",
        end_date="2026-06-03",
        cash=10_000,
    ):
        # Deferred import: only executed when a test calls the factory.
        from itrader.trading_system.backtest_trading_system import TradingSystem

        return TradingSystem(
            exchange="csv",
            start_date=start_date,
            end_date=end_date,
        )

    return _make
