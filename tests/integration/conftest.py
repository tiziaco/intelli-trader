"""Integration-layer fixtures (D-13/D-15).

These fixtures serve the cross-component cascade, the run-path smoke test, and the
golden-master oracle — all of which exercise MORE than one collaborating component
(the D-15 integration boundary). They live here, not at the root, because the unit
layer never needs the frozen-oracle assets or a full ``TradingSystem``.

Golden assets moved with the tree (D-13): ``tests/golden/{trades,equity}.csv`` +
``summary.json``. The path fixtures below resolve to that moved location.
"""

import pathlib

import pytest

# This file lives at <repo>/tests/integration/, so the golden dir is one level up
# under tests/golden/.
_GOLDEN_DIR = pathlib.Path(__file__).resolve().parent.parent / "golden"


@pytest.fixture
def golden_dir():
    """Path to the committed frozen-oracle directory (tests/golden/)."""
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
    The TradingSystem import lives inside the inner function body so ``--collect-only``
    succeeds even if a referenced branch is not yet wired.
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
