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
_SUMMARY_IDENTITY_KEYS = ("trade_count",)
_SUMMARY_NUMERIC_KEYS = ("final_cash", "final_equity", "total_realised_pnl")


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
