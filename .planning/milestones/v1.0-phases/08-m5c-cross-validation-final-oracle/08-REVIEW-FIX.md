---
phase: 08-m5c-cross-validation-final-oracle
fixed_at: 2026-06-08T16:20:00Z
review_path: .planning/phases/08-m5c-cross-validation-final-oracle/08-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 11
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

**Fixed at:** 2026-06-08T16:20:00Z
**Source review:** .planning/phases/08-m5c-cross-validation-final-oracle/08-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (fix_scope=all — WR-01..WR-05, IN-01..IN-06)
- Fixed: 11
- Skipped: 0

## Fixed Issues

### WR-01: `annualized_return` uses a mathematically incoherent compounding formula

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** 243a06d (with WR-02 — co-located in the same function)
**Applied fix:** Replaced the linear-average-then-compound-365× formula with the correct geometric annualization `(1 + total_return) ** (365 / days) - 1`. The existing `if days > 0 and initial_equity > 0` guard was already present and retained.
**Status:** fixed — requires human verification (logic change to the annualization/Sharpe math per the verification_strategy logic-bug rule; the downstream `sharpe_ratio` consumes `annualized_return`).

### WR-02: Decimal money narrowed to float and back to Decimal in `daily_returns`

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** 243a06d (with WR-01 — co-located in the same function)
**Applied fix:** Compute the per-snapshot return directly in Decimal from the already-Decimal `total_equity` (`(curr - prev) / prev`), removing the `float(...) -> Decimal(str(float))` round-trip that baked a binary-float artifact into the canonical `List[Decimal] daily_returns`. Downstream volatility/win-rate/average-win statistics still narrow to float at their own call sites (unchanged), which is the legitimate D-06 ratio boundary.
**Status:** fixed — requires human verification (Decimal ratio computation change; the value type stored in `daily_returns` is now Decimal-exact rather than float-derived). All 25 metrics tests + 179 portfolio tests pass.

### WR-03: Truncation footer emits a malformed Markdown row (wrong column count)

**Files modified:** `scripts/crossval/reconcile.py`
**Commit:** 8d88dbf (with WR-04, WR-05, IN-02 — co-located in the same file)
**Applied fix:** Pad the truncation footer in `build_trade_table` to the full `cols` width (`cols - 2` empty trailing cells) so the "N aligned rows omitted" row renders as a well-formed N-column Markdown row in the committed `CROSS-VALIDATION.md` evidence artifact.

### WR-04: Cross-engine CAGR/Sharpe comparison not apples-to-apples (unequal equity lengths)

**Files modified:** `scripts/crossval/reconcile.py`
**Commit:** 8d88dbf (with WR-03, WR-05, IN-02 — co-located in the same file)
**Applied fix:** Applied the review's explicit minimum ("document explicitly in the report that length-sensitive metrics are informational only"). Added a `CAVEAT (WR-04)` block to `recompute_headline`'s docstring documenting the equity-series-length sensitivity of `cagr`/`sharpe`/`sortino`, that a flagged DIVERGE may be a harness artifact (unequal length) rather than a genuine engine divergence, that these metrics are informational only, that the D-02 trade-level table is the primary gate, and the path to a strict fix (normalize each engine's equity series to the same post-warm-up window). A full equity-series normalization across backtrader/nautilus/backtesting.py was deliberately NOT attempted to avoid introducing logic errors into the offline harness; the documented caveat is the review's stated floor fix.

### WR-05: `align_trades` aligns positionally by index — a single insert/drop cascades into SHIFT

**Files modified:** `scripts/crossval/reconcile.py`
**Commit:** 8d88dbf (with WR-03, WR-04, IN-02 — co-located in the same file)
**Applied fix:** Applied the review's explicit minimum ("when trade counts differ, note in the report that positional alignment makes downstream rows unreliable"). Added a `CAVEAT (WR-05)` block to `align_trades`'s docstring documenting that alignment is purely positional, that a single early insert/drop cascades every subsequent row into SHIFT, that on a count mismatch the per-row SHIFT flags are NOT reliable evidence (treat as one alignment artifact, lean on the trade-count divergence), and that a date-anchored / LCS alignment would localize the real divergence. A full re-implementation of the alignment algorithm was deliberately NOT attempted in the offline harness; the documented caveat is the review's stated floor fix.

### IN-01: Dead locals in cross-validation orchestrator

**Files modified:** `scripts/cross_validate.py`
**Commit:** b0ab1f2
**Applied fix:** Removed the unused `itrader_headline` and `engine_metrics` parameters from `build_report` and the corresponding positional arguments at the call site. `itrader_headline`/`engine_metrics` remain consumed elsewhere in `main()` (by `build_metric_table`/`align_trades`). The `_itrader_equity` unpacked local was already prefixed with `_` (the accepted unused-marker convention), so no change was needed there.

### IN-02: `_norm_ts` raises an exception type the caller does not guard

**Files modified:** `scripts/crossval/reconcile.py`
**Commit:** 8d88dbf (with WR-03, WR-04, WR-05 — co-located in the same file)
**Applied fix:** Wrapped the `pd.Timestamp(value)` parse in `_norm_ts` in a `try/except (ValueError, TypeError, pd.errors.OutOfBoundsDatetime)` that degrades to `None`, so a malformed/unparseable cell from a gating engine no longer propagates a traceback out of the pure reconcile layer into `cross_validate.main` (which only try-guards Nautilus).

### IN-03: Redundant `Decimal(str(...))` on a value documented to already be Decimal

**Files modified:** `itrader/portfolio_handler/portfolio.py`
**Commit:** ee0b970
**Applied fix:** In `_get_max_position_percentage`, replaced `abs(Decimal(str(pos.market_value)))` with `abs(pos.market_value)` — trusting the Decimal source consistently with the rest of the M5-10 edit, so a stray-float type regression would surface rather than being silently coerced. `Decimal` remains used throughout the file (27 occurrences), so no dead import.

### IN-04: `MockPortfolio` test fixture exercises only the fallback coercion path

**Files modified:** `tests/unit/portfolio/test_metrics_manager.py`
**Commit:** caf8968 (with IN-05 — co-located in the same file)
**Applied fix:** Added `test_as_decimal_passthrough_on_decimal_money`, asserting that `_as_decimal(Decimal(...))` returns the exact same object (`result is money`) — locking the production "already Decimal, pass-through" branch that the float-money mock never exercised.

### IN-05: Mixed int/float `update_values` literals in tests

**Files modified:** `tests/unit/portfolio/test_metrics_manager.py`
**Commit:** caf8968 (with IN-04 — co-located in the same file)
**Applied fix:** Converted the mixed integer literals (`100000 + i * 1000`, `i * 100`, `i * 500`, etc.) in the `update_values` calls flagged by the finding to consistent float literals (`100000.0 + i * 1000.0`, `i * 100.0`, `i * 500.0`). The unrelated `thread_id`-based call (not in the finding's scope) was left unchanged. All 25 tests still pass.

### IN-06: `nautilus_run.run()` docstring/signature drift vs orchestrator call

**Files modified:** `scripts/crossval/nautilus_run.py`
**Commit:** 37e1627
**Applied fix:** Applied the review's "add an assertion that the expected indicator columns are present before the remap" option. Added a fast-fail check in `run()` that raises a clear `RuntimeError` listing the missing/present columns if any of `sma_short`/`sma_long`/`macd_hist` is absent, instead of an opaque mid-remap `KeyError` if the shared `compute_indicators` column names ever change. Verified DataFrame `in`/`list()` membership semantics behave as required.

---

_Fixed: 2026-06-08T16:20:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
