---
phase: 08-admission-position-management-cash-edges
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/08-admission-position-management-cash-edges/08-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 08: Code Review Fix Report

**Fixed at:** 2026-06-10
**Source review:** .planning/phases/08-admission-position-management-cash-edges/08-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope = all — includes Info findings)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### WR-01: `correlation` ordinal uses string sort — ORDER-10 sorts before ORDER-2

**Files modified:** `itrader/reporting/cash_operations.py`, `tests/e2e/cash/release_refused/golden/cash_operations.csv`, `tests/e2e/cash/release_cancelled/golden/cash_operations.csv`, `tests/e2e/admission/scale_in/golden/cash_operations.csv`
**Commit:** 15904b0
**Applied fix:** Changed the derived correlation label from `f"ORDER-{n}"` to `f"ORDER-{n:03d}"` so a lexical sort on the string column equals numeric order. Regenerated the three committed `cash_operations.csv` goldens (`ORDER-1`..`ORDER-5` → `ORDER-001`..`ORDER-005`) so the frozen rows match the new padded format. Both producers (serializer sort + harness `_CASH_OPS_SORT_KEYS`) consume the same string column, so they stay in agreement. All affected scenarios re-pass.

### WR-02: `build_cash_operations` reads duck-typed attributes with no guard

**Files modified:** `itrader/reporting/cash_operations.py`
**Commit:** e6df7bb
**Applied fix:** Extracted the row builder into a `_row(op)` helper that first checks all required fields (`reference_id`, `operation_type`, `amount`, `balance_before`, `balance_after`) with `hasattr` and raises a `TypeError` naming the offending operation and missing fields. Added a dedicated check that `operation_type` exposes `.name` (named-cause failure if it is a plain string instead of an enum). mypy --strict clean; cash scenarios re-pass.

### IN-01: `amount` is the only tiebreak after (correlation, operation_type) — relies on stable sort, not a unique key

**Files modified:** `itrader/reporting/cash_operations.py`
**Commit:** 62007f2
**Applied fix:** Carried a source-appearance index (`frame["_seq"] = range(len(frame))`) as the final sort tiebreak, making the sort key total, then dropped the column before returning (not a business column, never reaches the golden). Updated the determinism-contract docstring to describe the total key. mypy --strict clean; cash + scale_in scenarios re-pass.

### IN-02: `float_format=FLOAT_FORMAT` is silently inert on Decimal-object columns

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 7a0bd6e
**Applied fix:** Per the reviewer's guidance ("Out of this phase's strict scope — inherited Phase-4 harness behavior — but worth a tracking note"), added a tracking note to the `_freeze` docstring documenting that `float_format` is inert on `Decimal`-object columns (e.g. inherited `trades.avg_sold`), that the cash serializer is unaffected because it casts `float(op.amount)` at the edge, and that the proper cast-to-float fix is deferred because it would re-freeze inherited Phase-4 trade goldens. No behavioral change — diff behavior is identical; scale_out re-passes.

### IN-03: `release_refused` VERIFY note understates the harness seam it depends on

**Files modified:** `tests/e2e/cash/release_refused/scenario.py`
**Commit:** 907e253
**Applied fix:** Added the recommended clarifying line to the VERIFY note: the harness seam (conftest:290-291) re-derives BOTH `_min_order_size` and `_max_order_size` from `spec.exchange`; this leaf relies on the default min (0.001) and only moves `max_order_size`, but a future min-driven REFUSED leaf can lean on the same live min cache. Docstring-only; release_refused re-passes.

---

_Fixed: 2026-06-10_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
