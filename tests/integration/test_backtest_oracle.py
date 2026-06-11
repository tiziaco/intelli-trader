"""Run-path integration test: full 2018->2026 backtest vs the frozen oracle (M1-10).

Behavior (D-16): run the FULL SMA_MACD backtest over the pinned golden window by
invoking the committed oracle generator (``scripts/run_backtest.py::main``) in-process,
which writes a fresh ``output/{trades,equity}.csv`` + ``output/summary.json``. The test
then loads BOTH the fresh ``output/`` and the committed ``tests/golden/`` equivalents and
asserts they are EQUAL on the deterministic columns (D-12) with NO float tolerance
(D-13 — exact; a tolerance would mask real regressions and M1 runs are bit-reproducible).

Diff mechanic (Don't Hand-Roll): load both CSVs to pandas DataFrames and assert
``frame-equal`` on the deterministic columns for clear, column-level failure messages —
NOT a byte-compare. Trades are identified by ``(entry_date, exit_date, side)`` (D-12);
equity by ``(timestamp, total_equity)``; summary by final cash / trade count / realised PnL.

This test carries the ``integration`` + ``slow`` markers AUTOMATICALLY via the
``tests/integration/`` path (root-conftest folder-derived TYPE auto-marking, D-13) —
markers are NOT hand-added here.

It is RED until ``tests/golden/`` is frozen — that is expected.
"""

import importlib.util
import json
import pathlib

import pandas as pd
import pandas.testing as pdt
import pytest


# Repo layout: this file lives at <repo>/tests/integration/, so the repo root is
# two parents up. The oracle generator and its output dir are anchored from there.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_RUN_BACKTEST = _REPO_ROOT / "scripts" / "run_backtest.py"
_OUTPUT_DIR = _REPO_ROOT / "output"

# Deterministic columns to diff (D-12). Trades identified by (entry_date, exit_date, side);
# the remaining numeric columns are diffed EXACT (D-16 — M2b re-freeze, no tolerance).
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_EQUITY_KEY_COLUMNS = ["timestamp", "total_equity"]
_SUMMARY_KEYS = ("final_cash", "trade_count", "total_realised_pnl", "final_equity")

# Behavioral identity is the LAW (asserted EXACT). As of the M2b numerical re-freeze
# (D-16, plan 03-09) the numeric magnitudes are ALSO asserted EXACT (no tolerance): the
# D-15 transitional window and the DEF-02-08-A xfail are CLOSED. `pair` is a non-key
# behavioral identity column (which instrument traded) — asserted EXACT alongside the
# trade-key columns. Sorting still uses the (entry/exit/side) trade key.
_TRADE_IDENTITY_COLUMNS = _TRADE_KEY_COLUMNS + ["pair"]
# Equity identity is the timestamp grid; total_equity + the rest are numeric (now EXACT).
_EQUITY_IDENTITY_COLUMNS = ["timestamp"]
# Summary identity = trade_count (behavioral law). The numeric keys (final_cash/final_equity/
# total_realised_pnl) are re-frozen EXACT at the M2b re-baseline (D-16) — the M2a Decimal-end
# values are now the committed golden.
#
# M5b re-freeze 1 (D-08/D-11, plan 07-07 — owner-approved, see
# tests/golden/REFREEZE-M5B-DIRECTION.md): the LONG_ONLY direction guard at admission
# removes the 2 blessed golden shorts (−2 SHORT, +2 LONG; trade count unchanged at 134)
# and fraction-of-cash compounding shifts every downstream entry — final equity
# 53103.0155 → 46132.7668. Two NEW frozen artifacts ride this named re-freeze:
# the summary.json "metrics" block (D-15 — cagr/max_drawdown/profit_factor/sharpe/
# sortino/win_rate, asserted as one exact dict comparison below) and the trades.csv
# slippage_entry/slippage_exit columns (D-17 — auto-locked EXACT via the golden-derived
# ``_trade_numeric`` column mechanic, presence asserted explicitly).
_SUMMARY_IDENTITY_KEYS = ("trade_count",)
_SUMMARY_NUMERIC_KEYS = ("final_cash", "final_equity", "total_realised_pnl")
# D-17 slippage attribution columns — frozen at M5b re-freeze 1; their presence in the
# golden header is asserted so the _trade_numeric auto-lock cannot silently lose them.
_TRADE_SLIPPAGE_COLUMNS = ("slippage_entry", "slippage_exit")


def _load_run_backtest_module():
    """Import scripts/run_backtest.py as a module (it is not on the package path)."""
    # WR-05: fail loudly with a clear message if the oracle generator moved or
    # spec_from_file_location could not resolve a loader, rather than dying with
    # an opaque AttributeError on None.
    if not _RUN_BACKTEST.exists():
        pytest.fail(f"oracle generator missing: {_RUN_BACKTEST}")
    spec = importlib.util.spec_from_file_location("run_backtest", _RUN_BACKTEST)
    assert spec is not None and spec.loader is not None, f"cannot load {_RUN_BACKTEST}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_full_backtest():
    """Run the full 2018->2026 oracle generation in-process, writing a fresh output/.

    Calls the committed ``main()`` directly (rather than a subprocess) so the run stays
    in-process and fast to debug, while still exercising the exact pinned run path the
    oracle was frozen from.
    """
    module = _load_run_backtest_module()
    module.main()


@pytest.fixture(scope="module")
def oracle_run():
    """Run the full 2018->2026 backtest ONCE and load fresh output/ + frozen tests/golden/.

    Module-scoped so the (slow) full run is shared by the behavioral-identity test and the
    deferred numeric test. The golden paths are constants here (the conftest ``golden_*``
    fixtures are function-scoped and cannot feed a module-scoped fixture); they resolve to the
    same committed ``tests/golden/`` directory.
    """
    golden_dir = _REPO_ROOT / "tests" / "golden"
    if not golden_dir.exists():
        pytest.skip(
            "tests/golden/ not yet frozen (Task 2 of plan 01-05) — integration RED until blessed"
        )

    # Full 2018->2026 run writes a fresh output/{trades,equity}.csv + summary.json.
    _run_full_backtest()

    fresh_trades = pd.read_csv(_OUTPUT_DIR / "trades.csv")
    fresh_equity = pd.read_csv(_OUTPUT_DIR / "equity.csv")
    with open(_OUTPUT_DIR / "summary.json") as handle:
        fresh_summary = json.load(handle)

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
        "summary": (fresh_summary, golden_summary),
    }


def test_oracle_behavioral_identity(oracle_run):
    """The behavioral LAW (D-12/D-13): trade/equity/summary IDENTITY matches the golden EXACTLY.

    This is the regression guard that MUST stay green: same trades (count + entry/exit/side/pair),
    same equity timestamp grid, same trade count. It is asserted with NO tolerance — a real
    behavior change (different trades, timing, or count) fails here immediately. The numeric
    *magnitude* drift from the M2a Decimal fixes is deferred separately (see
    ``test_oracle_numeric_values`` / DEF-02-08-A) and does NOT weaken this assertion.
    """
    fresh_trades_sorted, golden_trades_sorted = oracle_run["trades"]
    fresh_equity_sorted, golden_equity_sorted = oracle_run["equity"]
    fresh_summary, golden_summary = oracle_run["summary"]

    # --- Trades: count + identity columns (entry/exit/side/pair) EXACT ---------
    assert len(fresh_trades_sorted) == len(golden_trades_sorted), (
        f"trade count drift: fresh={len(fresh_trades_sorted)} "
        f"golden={len(golden_trades_sorted)}"
    )
    pdt.assert_frame_equal(
        fresh_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        golden_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    # --- Equity: point count + timestamp grid EXACT ---------------------------
    assert len(fresh_equity_sorted) == len(golden_equity_sorted), (
        f"equity point count drift: fresh={len(fresh_equity_sorted)} "
        f"golden={len(golden_equity_sorted)}"
    )
    pdt.assert_frame_equal(
        fresh_equity_sorted[_EQUITY_IDENTITY_COLUMNS],
        golden_equity_sorted[_EQUITY_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )

    # --- Summary: identity keys (trade_count) EXACT ---------------------------
    for key in _SUMMARY_IDENTITY_KEYS:
        assert fresh_summary[key] == golden_summary[key], (
            f"summary identity drift on '{key}': fresh={fresh_summary[key]} "
            f"golden={golden_summary[key]}"
        )


def test_oracle_numeric_values(oracle_run):
    """Numeric magnitudes vs the frozen golden — EXACT (D-16, M2b re-freeze).

    As of the M2b numerical re-baseline (plan 03-09), the D-15 transitional tolerance and the
    DEF-02-08-A xfail are CLOSED: the golden was regenerated from the M2b-end Decimal run
    (final_equity 53229.68512642488, replacing the stale M1 float oracle 53229.75) and these
    numeric columns are now asserted EXACT (no rtol/atol). A deterministic Decimal run reproduces
    them bit-for-bit, so any drift is a real regression. This is one of PROJECT.md's two sanctioned
    numeric re-baseline points (after M2); the behavioral identity stays exact + active separately.
    """
    fresh_trades_sorted, golden_trades_sorted = oracle_run["trades"]
    fresh_equity_sorted, golden_equity_sorted = oracle_run["equity"]
    fresh_summary, golden_summary = oracle_run["summary"]

    # --- Trade numeric columns: EXACT (D-16) ----------------------------------
    # D-17 (M5b re-freeze 1): the slippage attribution columns are part of the frozen
    # header — assert their presence so the golden-derived auto-lock below covers them.
    for column in _TRADE_SLIPPAGE_COLUMNS:
        assert column in golden_trades_sorted.columns, (
            f"frozen slippage column '{column}' missing from golden trades.csv header"
        )
    _trade_numeric = [
        c for c in golden_trades_sorted.columns if c not in _TRADE_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_trades_sorted[_trade_numeric],
        golden_trades_sorted[_trade_numeric],
        check_exact=True,
        check_like=True,
    )

    # --- Equity numeric columns: EXACT (D-16) ---------------------------------
    _equity_numeric = [
        c for c in golden_equity_sorted.columns if c not in _EQUITY_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_equity_sorted[_equity_numeric],
        golden_equity_sorted[_equity_numeric],
        check_exact=True,
        check_like=True,
    )

    # --- Summary numeric keys: EXACT (D-16) -----------------------------------
    for key in _SUMMARY_NUMERIC_KEYS:
        assert fresh_summary[key] == golden_summary[key], (
            f"summary numeric drift on '{key}': "
            f"fresh={fresh_summary[key]} golden={golden_summary[key]}"
        )

    # --- Derived-metrics block: EXACT dict comparison (D-15, M5b re-freeze 1) --
    # One dict comparison of the whole "metrics" object (RESEARCH OQ3): exact
    # equality, consistent with the D-16 byte-exact discipline — a deterministic
    # run reproduces the floats bit-for-bit, so any drift is a real regression.
    assert fresh_summary["metrics"] == golden_summary["metrics"], (
        f"summary metrics drift: fresh={fresh_summary['metrics']} "
        f"golden={golden_summary['metrics']}"
    )


# --- SIG-02: post-run signal store on the golden SMA_MACD run -----------------
#
# Additive assertion (Plan 05-03): the golden SMA_MACD run produces a NON-empty,
# queryable SignalStore via the TradingSystem post-run accessor. This wires the
# same golden config the oracle generator uses (scripts/run_backtest.py::main —
# BTCUSD/1d/$10k/FractionOfCash(0.95)/LONG_ONLY over the pinned 2018->2026
# window), but holds the TradingSystem reference so the post-run accessor can be
# read. It does NOT touch the byte-exact oracle assertions above — capturing a
# sink record is side-effect-only (oracle-dark, HARD-04). The store is read AFTER
# the run (read-model sink, D-12) — the queue-only contract is preserved.

from decimal import Decimal  # noqa: E402

from itrader.core.sizing import FractionOfCash, TradingDirection  # noqa: E402
from itrader.strategy_handler.strategies.SMA_MACD_strategy import (  # noqa: E402
    SMA_MACDConfig,
    SMAMACDStrategy,
)
from itrader.trading_system.backtest_trading_system import TradingSystem  # noqa: E402


def test_golden_run_signal_store_is_non_empty_and_queryable():
    """SIG-02: the golden SMA_MACD run yields a non-empty, queryable SignalStore.

    Proves the post-run accessor returns >0 records, that the records are
    filterable by ticker and by strategy id, and that each record carries a
    ``config`` snapshot whose ``model_dump()`` is a dict (queryability +
    snapshot serialization). The byte-exact oracle assertions live in the
    sibling tests above and are NOT weakened here.
    """
    system = TradingSystem(
        exchange="csv",
        start_date="2018-01-01",
        end_date="2026-06-03",
    )
    config = SMA_MACDConfig(
        timeframe="1d",
        tickers=["BTCUSD"],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    strategy = SMAMACDStrategy(config)
    system.strategies_handler.add_strategy(strategy)
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1, name="sig02_pf", exchange="csv", cash=10_000,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # Suppress the end-of-run metrics printout (display-only, oracle-inert).
    system.run(print_summary=False)

    # Post-run accessor: non-empty (SMA_MACD fires intents on the golden window).
    records = system.get_signal_records()
    assert len(records) > 0

    # Queryable by ticker and by strategy id (no cross-strategy bleed, T-05-05).
    store = system.get_signal_store()
    assert len(store.by_ticker("BTCUSD")) > 0
    assert len(store.by_strategy(strategy.strategy_id)) > 0

    # Each record carries a serializable config snapshot (SIG-02 / D-11).
    assert isinstance(records[0].config.model_dump(), dict)
