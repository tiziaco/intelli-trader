"""Byte-exact SMA_MACD oracle through the FACTORY arm (``build_backtest_system``).

``test_backtest_oracle.py`` drives the LEGACY construction arm — the loose-parameter
``BacktestTradingSystem.__init__``, reached through ``scripts/run_backtest.py::main``.
Nothing asserted the golden artifacts through ``build_backtest_system``, so a change
confined to the factory / ``compose_engine`` path could diverge from the frozen oracle
while every existing gate stayed green.

That matters whenever composition is refactored: the byte-exact guarantee the project is
anchored on (134 trades / final_equity ``46189.87730727451``) was only enforced on the arm
a composition change is *least* likely to touch.

This module closes the gap. It runs the SAME pinned golden configuration — imported from
the oracle generator itself, never re-typed, so the two arms cannot drift apart — through
the factory, assembles artifacts with the SAME ``reporting`` builders, and asserts them
against the SAME committed ``tests/golden/`` reference with no tolerance.

The comparison round-trips the fresh frames through ``to_csv(float_format=FLOAT_FORMAT)``
before diffing, because that is how the golden was serialized: comparing full-precision
in-memory floats against a formatted CSV would fail on representation, not on behaviour.

Carries ``integration`` + ``slow`` automatically via the ``tests/integration/`` path.
"""

import json

import pandas as pd
import pandas.testing as pdt
import pytest

from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.reporting.summary import (
    FLOAT_FORMAT,
    SLIPPAGE_COLUMNS,
    attach_slippage,
    build_metrics_block,
    build_summary,
)
from itrader.trading_system.backtest.backtest_trading_system import build_backtest_system
from itrader.trading_system.system_spec import PortfolioSpec, SystemSpec
from tests.integration._oracle_harness import _REPO_ROOT, load_run_backtest_module

# Same deterministic columns/keys the legacy-arm oracle test diffs, so both arms are held
# to one standard. Duplicated as literals here rather than imported from the sibling test
# module: a test importing another test module couples their collection order.
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_TRADE_IDENTITY_COLUMNS = _TRADE_KEY_COLUMNS + ["pair"]
_EQUITY_KEY_COLUMNS = ["timestamp", "total_equity"]
_EQUITY_IDENTITY_COLUMNS = ["timestamp"]
_SUMMARY_IDENTITY_KEYS = ("trade_count",)
_SUMMARY_NUMERIC_KEYS = ("final_cash", "final_equity", "total_realised_pnl")


def _golden_config():
    """The pinned oracle configuration, read off the generator (never re-typed).

    Returns the ``scripts/run_backtest.py`` module so DATASET / START_DATE / END_DATE /
    CASH / TICKER / TIMEFRAME come from the one place that defines them. If the oracle is
    ever re-pinned, this arm follows automatically instead of silently testing a stale
    configuration against a fresh golden.
    """
    return load_run_backtest_module("run_backtest_factory_arm")


def _build_via_factory(oracle):
    """The golden run, composed through ``build_backtest_system``.

    Mirrors ``scripts/run_backtest.py::main`` field for field, with the ONE intended
    difference: the spec/factory seam replaces direct construction. The strategy is built
    from the generator's own constants; the factory adds it, creates the portfolio and
    wires the subscription.
    """
    from decimal import Decimal

    from itrader.core.sizing import FractionOfCash, TradingDirection
    from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMAMACDStrategy

    strategy = SMAMACDStrategy(
        timeframe=oracle.TIMEFRAME,
        tickers=[oracle.TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    spec = SystemSpec(
        start=oracle.START_DATE,
        end=oracle.END_DATE,
        timeframe=oracle.TIMEFRAME,
        ticker=oracle.TICKER,
        starting_cash=oracle.CASH,
        data={oracle.TICKER: oracle.DATASET},
        strategies=[strategy],
        portfolios=[PortfolioSpec(name="oracle_pf", cash=oracle.CASH)],
    )
    return build_backtest_system(spec)


def _serialize_roundtrip(frame, columns, tmp_path, name):
    """Write ``frame`` exactly as the oracle generator does, then read it back.

    The golden CSVs were produced with ``to_csv(float_format=FLOAT_FORMAT)`` and are read
    back with ``read_csv``. Putting the fresh frame through the identical round-trip makes
    the diff a behaviour comparison rather than a float-representation comparison.
    """
    path = tmp_path / name
    frame[columns].to_csv(path, index=False, float_format=FLOAT_FORMAT)
    return pd.read_csv(path)


@pytest.fixture(scope="module")
def factory_arm_run(tmp_path_factory):
    """Run the full 2018->2026 golden backtest ONCE through the factory arm.

    Module-scoped: the run is slow and both tests below read it. Nothing is written to
    ``output/`` — that directory belongs to the legacy-arm oracle generator, and writing
    there would make the two oracle modules order-dependent.
    """
    golden_dir = _REPO_ROOT / "tests" / "golden"
    if not golden_dir.exists():
        pytest.skip("tests/golden/ not yet frozen — nothing to compare against")

    oracle = _golden_config()
    system = _build_via_factory(oracle)
    system.run(print_summary=False)

    portfolio = list(system.portfolio_handler.get_active_portfolios())[0]
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)
    trades = attach_slippage(trades, system.store.read_bars(oracle.TICKER)["close"])

    summary = build_summary(
        portfolio,
        trades,
        ticker=oracle.TICKER,
        timeframe=oracle.TIMEFRAME,
        start_date=oracle.START_DATE,
        end_date=oracle.END_DATE,
        starting_cash=oracle.CASH,
    )
    summary["metrics"] = build_metrics_block(equity, trades)

    tmp_path = tmp_path_factory.mktemp("factory_arm_oracle")
    fresh_trades = _serialize_roundtrip(
        trades, TRADE_COLUMNS + SLIPPAGE_COLUMNS, tmp_path, "trades.csv")
    fresh_equity = _serialize_roundtrip(
        equity, EQUITY_COLUMNS, tmp_path, "equity.csv")

    golden_trades = pd.read_csv(golden_dir / "trades.csv")
    golden_equity = pd.read_csv(golden_dir / "equity.csv")
    with open(golden_dir / "summary.json") as handle:
        golden_summary = json.load(handle)

    return {
        "trades": (
            fresh_trades.sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True),
            golden_trades.sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True),
        ),
        "equity": (
            fresh_equity.sort_values(_EQUITY_KEY_COLUMNS).reset_index(drop=True),
            golden_equity.sort_values(_EQUITY_KEY_COLUMNS).reset_index(drop=True),
        ),
        "summary": (summary, golden_summary),
    }


def test_factory_arm_behavioral_identity(factory_arm_run):
    """The factory arm reproduces the golden trades/equity/summary IDENTITY exactly.

    Same behavioural law the legacy arm is held to: identical trade count, identical
    (entry_date, exit_date, side, pair) per trade, identical equity timestamp grid. A
    composition change that reorders dispatch, drops a fill, or shifts bar timing fails
    here — on the arm where such a change actually lands.
    """
    fresh_trades, golden_trades = factory_arm_run["trades"]
    fresh_equity, golden_equity = factory_arm_run["equity"]
    fresh_summary, golden_summary = factory_arm_run["summary"]

    assert len(fresh_trades) == len(golden_trades), (
        f"factory-arm trade count drift: fresh={len(fresh_trades)} "
        f"golden={len(golden_trades)}"
    )
    pdt.assert_frame_equal(
        fresh_trades[_TRADE_IDENTITY_COLUMNS],
        golden_trades[_TRADE_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    assert len(fresh_equity) == len(golden_equity), (
        f"factory-arm equity point count drift: fresh={len(fresh_equity)} "
        f"golden={len(golden_equity)}"
    )
    pdt.assert_frame_equal(
        fresh_equity[_EQUITY_IDENTITY_COLUMNS],
        golden_equity[_EQUITY_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    for key in _SUMMARY_IDENTITY_KEYS:
        assert fresh_summary[key] == golden_summary[key], (
            f"factory-arm summary identity drift on '{key}': "
            f"fresh={fresh_summary[key]} golden={golden_summary[key]}"
        )


def test_factory_arm_numeric_values(factory_arm_run):
    """The factory arm reproduces the golden numeric magnitudes exactly (no tolerance).

    Covers what a final-equity scalar check cannot: every per-trade numeric column
    (including the D-17 slippage attribution), the full equity path rather than its
    endpoint, and the derived-metrics block. Two runs can agree on final equity while
    disagreeing about how they got there — this is the assertion that notices.
    """
    fresh_trades, golden_trades = factory_arm_run["trades"]
    fresh_equity, golden_equity = factory_arm_run["equity"]
    fresh_summary, golden_summary = factory_arm_run["summary"]

    for column in SLIPPAGE_COLUMNS:
        assert column in golden_trades.columns, (
            f"frozen slippage column '{column}' missing from golden trades.csv header"
        )
    trade_numeric = [
        c for c in golden_trades.columns if c not in _TRADE_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_trades[trade_numeric],
        golden_trades[trade_numeric],
        check_exact=True,
        check_like=True,
    )

    equity_numeric = [
        c for c in golden_equity.columns if c not in _EQUITY_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_equity[equity_numeric],
        golden_equity[equity_numeric],
        check_exact=True,
        check_like=True,
    )

    for key in _SUMMARY_NUMERIC_KEYS:
        assert fresh_summary[key] == golden_summary[key], (
            f"factory-arm summary numeric drift on '{key}': "
            f"fresh={fresh_summary[key]} golden={golden_summary[key]}"
        )

    assert fresh_summary["metrics"] == golden_summary["metrics"], (
        f"factory-arm metrics drift: fresh={fresh_summary['metrics']} "
        f"golden={golden_summary['metrics']}"
    )
