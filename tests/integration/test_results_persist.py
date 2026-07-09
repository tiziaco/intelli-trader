"""Results persistence end-to-end + oracle/import inertness (RESULT-01 / GATE-01).

Proves the Wave-3 wiring closes RESULT-01 end-to-end while keeping the default
``persist=False`` path byte-exact and SQL-import-inert:

1. **End-to-end persist** — a small SMA_MACD backtest with an injected
   ``SqlResultsStore`` (in-process SQLite) run with ``persist=True`` writes a
   ``runs`` row, one ``run_portfolios`` row per active portfolio, and
   equity_curve/trade_log artifact frames that round-trip value-equal through the
   store codec (RESULT-01/RESULT-02).
2. **D-03 guard** — ``run(persist=True)`` on a system with no store injected raises
   ``ConfigurationError``.
3. **Oracle inertness (D-04/GATE-01)** — the SMA_MACD oracle stays byte-exact
   (134 / 46189.87730727451) under the default ``persist=False`` path.
4. **Import inertness (GATE-01)** — importing the backtest module in a fresh
   subprocess does NOT pull SQLAlchemy, proving the store-free path stays SQL-free.

The ``integration`` marker is applied AUTOMATICALLY via the ``tests/integration/``
path (root-conftest folder-derived TYPE auto-marking) — not hand-added here. The
``SqlResultsStore`` + spine are imported HERE (the persistence path), never on the
backtest module's import path — that is exactly what test 4 asserts. 4-space
indentation (tests house style).

Worktree note: run via ``PYTHONPATH="$PWD" poetry run pytest`` (make test aborts in
worktrees on a missing .env).
"""

import os
import subprocess
import sys
from decimal import Decimal

import pandas.testing as pdt
import pytest

from tests.integration._oracle_harness import _REPO_ROOT

from itrader.core.exceptions import ConfigurationError
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.reporting.frames import build_equity_curve, build_trade_log
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy
from itrader.trading_system.backtest_trading_system import (
    BacktestTradingSystem,
    build_backtest_system,
)
from itrader.trading_system.system_spec import PortfolioSpec, SystemSpec

# The SQL surface is imported HERE (the persistence path) — NEVER on the backtest
# module's import path (test 4 below asserts that). The store is constructed
# DIRECTLY as SqlResultsStore(SqlEngine(SqlSettings())) — no factory (D-19).
from itrader.config.sql import SqlSettings
from itrader.results.sql_storage import SqlResultsStore
from itrader.storage import SqlEngine

# The committed golden oracle values (tests/golden/summary.json) — the byte-exact
# SMA_MACD reference the default persist=False path must preserve (D-04 / GATE-01).
_GOLDEN_FINAL_EQUITY = 46189.87730727451
_GOLDEN_TRADE_COUNT = 134

_GOLDEN_CSV = "data/BTCUSD_1d_ohlcv_2018_2026.csv"


def _make_strategy() -> SMAMACDStrategy:
    """The golden SMA_MACD construction (verbatim from scripts/run_backtest.py)."""
    return SMAMACDStrategy(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )


def _make_store() -> SqlResultsStore:
    """A fresh in-process SQLite results store (direct construction, no factory)."""
    return SqlResultsStore(SqlEngine(SqlSettings()))


def test_persist_end_to_end_writes_runs_portfolios_and_artifacts() -> None:
    """run(persist=True) writes runs + run_portfolios + round-trippable artifacts."""
    store = _make_store()
    spec = SystemSpec(
        start="2018-01-01",
        end="2021-01-01",  # a short window — enough closed trades, fast loop
        timeframe="1d",
        ticker="BTCUSD",
        starting_cash=10_000,
        data={"BTCUSD": _GOLDEN_CSV},
        strategies=[_make_strategy()],
        portfolios=[PortfolioSpec(name="persist_pf", cash=10_000)],
        results_store=store,
    )
    system = build_backtest_system(spec)
    # build_backtest_system forwards spec.results_store straight onto the engine (D-04).
    assert system.engine.results_store is store

    system.run(persist=True, print_summary=False)

    # (a) a runs row exists ...
    runs = store.top_runs("final_equity", 10)
    assert len(runs) == 1
    run_id = runs[0].run_id

    # (b) ... one run_portfolios row per active portfolio ...
    active = list(system.portfolio_handler.get_active_portfolios())
    assert len(active) == 1
    portfolios = store.top_portfolios("final_equity", 10)
    assert len(portfolios) == len(active)

    # (c) ... and the artifact frames round-trip value-equal through the codec.
    artifacts = store.get_artifact(run_id)
    portfolio = active[0]
    pid = portfolio.portfolio_id
    assert (pid, "equity_curve") in artifacts
    assert (pid, "trade_log") in artifacts
    assert (None, "equity_curve") in artifacts  # the aggregate-level frame (D-07)

    # Both sides pass through the SAME gzip/json codec, so value-equality is exact
    # (decode(stored) == decode(encode(rebuilt)) iff persist wrote the right frame).
    rebuilt_equity = build_equity_curve(portfolio)
    expected_equity = store._decode_frame(store._encode_frame(rebuilt_equity))
    pdt.assert_frame_equal(artifacts[(pid, "equity_curve")], expected_equity)
    assert not artifacts[(pid, "equity_curve")].empty

    rebuilt_trades = build_trade_log(portfolio)
    expected_trades = store._decode_frame(store._encode_frame(rebuilt_trades))
    pdt.assert_frame_equal(artifacts[(pid, "trade_log")], expected_trades)
    # The short window produces real round trips — the trade log is non-empty.
    assert not artifacts[(pid, "trade_log")].empty

    store.dispose()


def test_persist_true_without_store_raises_configuration_error() -> None:
    """D-03: run(persist=True) with no store injected raises ConfigurationError."""
    system = BacktestTradingSystem(
        exchange="csv",
        start_date="2018-01-01",
        end_date="2018-06-01",  # tiny window — the guard raises post-loop regardless
    )
    strategy = _make_strategy()
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="guard_pf", exchange="csv", cash=10_000)
    strategy.subscribe_portfolio(portfolio_id)

    assert system.engine.results_store is None
    with pytest.raises(ConfigurationError):
        system.run(persist=True, print_summary=False)


def test_oracle_byte_exact_under_persist_false() -> None:
    """D-04 / GATE-01: the default persist=False path keeps the oracle byte-exact."""
    system = BacktestTradingSystem(
        exchange="csv",
        start_date="2018-01-01",
        end_date="2026-06-03",
    )
    strategy = _make_strategy()
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="oracle_pf", exchange="csv", cash=10_000)
    strategy.subscribe_portfolio(portfolio_id)

    # persist defaults False — NO dump code executes, so the numbers are byte-exact.
    system.run(print_summary=False)

    portfolio = list(system.portfolio_handler.get_active_portfolios())[0]
    assert float(portfolio.total_equity) == _GOLDEN_FINAL_EQUITY
    assert len(build_trade_log(portfolio)) == _GOLDEN_TRADE_COUNT
    # The store-free path never touched a results store.
    assert system.engine.results_store is None


def test_backtest_module_import_is_sql_import_inert() -> None:
    """GATE-01: importing the backtest module does NOT pull SQLAlchemy.

    A fresh subprocess imports the store-free backtest module and asserts
    ``sqlalchemy`` is absent from ``sys.modules`` — proving the default
    (``persist=False``) import path stays SQL-free.
    """
    code = (
        "import sys\n"
        "import itrader.trading_system.backtest_trading_system\n"
        "assert 'sqlalchemy' not in sys.modules, "
        "'GATE-01: sqlalchemy imported on the store-free backtest path'\n"
        "print('inert')\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "inert" in result.stdout
