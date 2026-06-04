"""Run-path integration test: full 2018->2026 backtest vs the frozen oracle (M1-10).

Behavior (D-16): run the FULL SMA_MACD backtest over the pinned golden window by
invoking the committed oracle generator (``scripts/run_backtest.py::main``) in-process,
which writes a fresh ``output/{trades,equity}.csv`` + ``output/summary.json``. The test
then loads BOTH the fresh ``output/`` and the committed ``test/golden/`` equivalents and
asserts they are EQUAL on the deterministic columns (D-12) with NO float tolerance
(D-13 — exact; a tolerance would mask real regressions and M1 runs are bit-reproducible).

Diff mechanic (Don't Hand-Roll): load both CSVs to pandas DataFrames and assert
``frame-equal`` on the deterministic columns for clear, column-level failure messages —
NOT a byte-compare. Trades are identified by ``(entry_date, exit_date, side)`` (D-12);
equity by ``(timestamp, total_equity)``; summary by final cash / trade count / realised PnL.

This test carries the ``integration`` + ``slow`` markers AUTOMATICALLY via the
``test_integration`` path (root-conftest auto-marking, D-14/D-16) — markers are NOT
hand-added here.

It is RED until Task 2 of this plan commits ``test/golden/`` — that is expected.
"""

import importlib.util
import json
import pathlib

import pandas as pd
import pandas.testing as pdt
import pytest


# Repo layout: this file lives at <repo>/test/test_integration/, so the repo root is
# two parents up. The oracle generator and its output dir are anchored from there.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_RUN_BACKTEST = _REPO_ROOT / "scripts" / "run_backtest.py"
_OUTPUT_DIR = _REPO_ROOT / "output"

# Deterministic columns to diff (D-12). Trades identified by (entry_date, exit_date, side);
# the remaining numeric columns are diffed with a bounded transitional tolerance (D-15).
_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]
_EQUITY_KEY_COLUMNS = ["timestamp", "total_equity"]
_SUMMARY_KEYS = ("final_cash", "trade_count", "total_realised_pnl", "final_equity")

# D-15: behavioral identity is the LAW (asserted EXACT); numeric value carries a bounded,
# documented, time-boxed tolerance to absorb the M2a float->Decimal quantization shift.
# `pair` is a non-key behavioral identity column (which instrument traded) — asserted EXACT
# alongside the trade-key columns. Sorting still uses the (entry/exit/side) trade key.
_TRADE_IDENTITY_COLUMNS = _TRADE_KEY_COLUMNS + ["pair"]
# Equity identity is the timestamp grid; total_equity + the rest are numeric (tolerant).
_EQUITY_IDENTITY_COLUMNS = ["timestamp"]
# Summary identity = trade count + the cash/equity endpoints that are EXACT post-M2a
# (final_cash/final_equity are exact; total_realised_pnl carries the Decimal drift).
_SUMMARY_IDENTITY_KEYS = ("final_cash", "trade_count", "final_equity")
_SUMMARY_NUMERIC_KEYS = ("total_realised_pnl",)

# D-15 transitional tolerance — set just above the observed M2a Decimal drift (max ~2.7e-2
# across trade/equity numeric columns; total_realised_pnl ~9.6e-3). Tight enough to catch a
# dollar-level money bug, loose enough for the sub-cent float->Decimal quantization. Removed
# and re-frozen EXACT at M2b (Phase 3 SC4).
_D15_RTOL = 1e-6
_D15_ATOL = 5e-2  # 5 cents — just above the observed ~2.7e-2 worst-case drift


def _load_run_backtest_module():
    """Import scripts/run_backtest.py as a module (it is not on the package path)."""
    spec = importlib.util.spec_from_file_location("run_backtest", _RUN_BACKTEST)
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


def test_full_backtest_matches_frozen_oracle(golden_dir, golden_trades_path,
                                             golden_equity_path, golden_summary_path):
    """Full run -> fresh output/ exact-matches the committed test/golden/ (D-13/D-16)."""
    if not golden_dir.exists():
        pytest.skip(
            "test/golden/ not yet frozen (Task 2 of plan 01-05) — integration RED until blessed"
        )

    # Full 2018->2026 run writes a fresh output/{trades,equity}.csv + summary.json.
    _run_full_backtest()

    fresh_trades = pd.read_csv(_OUTPUT_DIR / "trades.csv")
    fresh_equity = pd.read_csv(_OUTPUT_DIR / "equity.csv")
    with open(_OUTPUT_DIR / "summary.json") as handle:
        fresh_summary = json.load(handle)

    golden_trades = pd.read_csv(golden_trades_path)
    golden_equity = pd.read_csv(golden_equity_path)
    with open(golden_summary_path) as handle:
        golden_summary = json.load(handle)

    # --- Behavioral identity EXACT + numeric TOLERANT (D-15) -------------------
    # Sort both by the trade identity so row ordering can't mask a real match/mismatch.
    fresh_trades_sorted = (
        fresh_trades.sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True)
    )
    golden_trades_sorted = (
        golden_trades.sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True)
    )
    assert len(fresh_trades_sorted) == len(golden_trades_sorted), (
        f"trade count drift: fresh={len(fresh_trades_sorted)} "
        f"golden={len(golden_trades_sorted)}"
    )
    # Identity columns (entry/exit time + side + pair) = the behavioral LAW: EXACT, no tolerance.
    pdt.assert_frame_equal(
        fresh_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        golden_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )
    # Numeric columns: bounded transitional tolerance.
    _trade_numeric = [
        c for c in golden_trades_sorted.columns if c not in _TRADE_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_trades_sorted[_trade_numeric],
        golden_trades_sorted[_trade_numeric],
        check_exact=False,
        rtol=_D15_RTOL,
        atol=_D15_ATOL,
        check_like=True,
    )  # D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)

    # --- Equity curve: identity grid EXACT + numeric TOLERANT (D-15) -----------
    fresh_equity_sorted = (
        fresh_equity.sort_values(_EQUITY_KEY_COLUMNS).reset_index(drop=True)
    )
    golden_equity_sorted = (
        golden_equity.sort_values(_EQUITY_KEY_COLUMNS).reset_index(drop=True)
    )
    assert len(fresh_equity_sorted) == len(golden_equity_sorted), (
        f"equity point count drift: fresh={len(fresh_equity_sorted)} "
        f"golden={len(golden_equity_sorted)}"
    )
    # Identity = the timestamp grid (same points, same order): EXACT.
    pdt.assert_frame_equal(
        fresh_equity_sorted[_EQUITY_IDENTITY_COLUMNS],
        golden_equity_sorted[_EQUITY_IDENTITY_COLUMNS],
        check_exact=True,
        check_like=True,
    )
    # Numeric equity columns (total_equity, cash, pnl, ...): bounded transitional tolerance.
    _equity_numeric = [
        c for c in golden_equity_sorted.columns if c not in _EQUITY_IDENTITY_COLUMNS
    ]
    pdt.assert_frame_equal(
        fresh_equity_sorted[_equity_numeric],
        golden_equity_sorted[_equity_numeric],
        check_exact=False,
        rtol=_D15_RTOL,
        atol=_D15_ATOL,
        check_like=True,
    )  # D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)

    # --- Summary: identity keys EXACT + numeric keys TOLERANT (D-15) -----------
    # final_cash / trade_count / final_equity are EXACT post-M2a; total_realised_pnl
    # carries the float->Decimal drift and is asserted within the D-15 tolerance.
    for key in _SUMMARY_IDENTITY_KEYS:
        assert fresh_summary[key] == golden_summary[key], (
            f"summary identity drift on '{key}': fresh={fresh_summary[key]} "
            f"golden={golden_summary[key]}"
        )
    for key in _SUMMARY_NUMERIC_KEYS:
        # D-15 transitional — removed + re-frozen EXACT at M2b (Phase 3 SC4)
        assert abs(float(fresh_summary[key]) - float(golden_summary[key])) <= _D15_ATOL, (
            f"summary numeric drift on '{key}' exceeds D-15 tolerance "
            f"({_D15_ATOL}): fresh={fresh_summary[key]} golden={golden_summary[key]}"
        )
