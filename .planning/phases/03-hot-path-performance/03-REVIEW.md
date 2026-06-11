---
phase: 03-hot-path-performance
reviewed: 2026-06-11T16:10:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/order_handler/order_manager.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/store/csv_store.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - tests/unit/portfolio/test_metrics_manager.py
  - tests/unit/portfolio/test_on_fill_status_guard.py
  - tests/unit/portfolio/test_state_storage.py
  - tests/unit/price/test_bar_feed.py
findings:
  critical: 0
  warning: 0
  info: 3
  total: 3
status: issues_found
---

# Phase 3: Code Review Report (re-review)

**Reviewed:** 2026-06-11T16:10:00Z
**Depth:** standard
**Status:** issues_found (Info-only — no Critical, no Warning)

## Summary

Re-review of the Phase 3 hot-path-performance changeset after the prior BLOCKER
**CR-01** (mypy --strict regression introduced by the WR-02 fix) was fixed in
commit `829beed`. I verified the fix against its diff, the current file state,
the single caller, the regression tests, and both static gates the project's
Definition of Done pins (`mypy --strict` clean, deterministic).

**CR-01 verdict — RESOLVED, correct and complete.**

- The fix retypes `_calculate_drawdown_duration`'s `drawdowns` parameter from
  `List[float]` to `List[Decimal]`
  (`metrics_manager.py:650`). This is the minimal correct fix: it aligns the
  helper's declared type with the `list[Decimal]` that the WR-02 change
  (`drawdowns` built from Decimal `equity_values` at lines 329/343/344) now
  produces.
- The body needs no change — the only internal use of the parameter is the
  `drawdowns[i] < 0` comparison (lines 657, 664), which is valid for `Decimal`.
- There is exactly one caller (`metrics_manager.py:351`), which passes the
  `list[Decimal]` built at lines 334-344. The type contract is now consistent
  end-to-end; no other call sites exist (`grep` confirmed).
- The return type (`int`) and its downstream use (`max_dd_duration` →
  dict value) are unaffected.

**Static gates — both green:**

- `poetry run mypy itrader` → `Success: no issues found in 161 source files`.
  The package is back on the green `mypy --strict` DoD gate. The prior error
  (`metrics_manager.py:351 ... incompatible type "list[Any | Decimal]"; expected
  "list[float]"`) is gone.
- All 75 tests across the four in-scope test files pass
  (`test_metrics_manager.py` 26, `test_on_fill_status_guard.py` 6,
  `test_state_storage.py` 23, `test_bar_feed.py` 20). The fix is type-only and
  does not touch runtime behavior, so the previously-passing functional tests
  remain green.

No new Critical or Warning issues were introduced by the fix, and none were
surfaced on re-scan of the changed files. The three Info items below are
unchanged carry-forwards from the prior review (IN-01..IN-03); they were never
in the CR-01 / WR-fix scope and remain open. They are non-blocking.

## Info

### IN-01: Dead imports remain in `metrics_manager.py`

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:6,8,9,14`
**Issue:** Unused imports persist: `ROUND_HALF_UP` (line 6 — only `Decimal` is
referenced), `Tuple` (line 8), `asdict` (line 9), and `InvalidTransactionError`
(line 14 — never raised in this module). The CR-01 fix touched this file but
correctly kept its scope to the one-line type change, so the import block was
not cleaned.
**Fix:** Reduce line 6 to `from decimal import Decimal`; drop `Tuple` from the
typing import; drop `asdict` from the dataclasses import; remove the
`InvalidTransactionError` import line.

### IN-02: `_should_close_position` vs `_validate_position_consistency` zero-tolerance mismatch

**File:** `itrader/portfolio_handler/position/position_manager.py:88,188,211`
**Issue:** `self.tolerance = Decimal('0.00001')` (5 dp) gates closure while
`_validate_position_consistency` uses `Decimal("0.000001")` (6 dp) for its
negative-quantity guard. The order-of-magnitude difference is undocumented; a
residual quantity in `[1e-6, 1e-5)` is treated inconsistently between the two
methods. Not a live defect on the golden long-only single-ticker run, but a
latent inconsistency. Unchanged since the prior review.
**Fix:** Derive both from one named constant, or add a comment documenting why
they differ.

### IN-03: `get_return_distribution` percentiles degenerate on tiny samples

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:395-402`
**Issue:** Percentile lookups index by a fraction of the sample length; the
`len(snaps) < period_days + 1` guard prevents any IndexError, but for very small
samples the percentile values are degenerate (e.g. 2 returns → "5th" and "25th"
both equal `sorted_returns[0]`) and are reported without a minimum-sample
caveat. Not a crash; unchanged since the prior review.
**Fix:** Require a minimum sample size before reporting percentiles, or document
that they are nominal below N samples.

---

_Reviewed: 2026-06-11T16:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
