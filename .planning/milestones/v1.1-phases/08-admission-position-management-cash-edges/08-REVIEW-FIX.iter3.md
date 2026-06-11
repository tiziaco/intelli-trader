---
phase: 08-admission-position-management-cash-edges
fixed_at: 2026-06-10T00:00:00Z
review_path: .planning/phases/08-admission-position-management-cash-edges/08-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 08: Code Review Fix Report

**Fixed at:** 2026-06-10
**Source review:** .planning/phases/08-admission-position-management-cash-edges/08-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-03: WR-01 re-freeze left the VERIFY hand-derivation tables out of sync with the goldens (`ORDER-1` vs `ORDER-001`)

**Files modified:** `tests/e2e/admission/scale_in/scenario.py`, `tests/e2e/cash/release_cancelled/scenario.py`, `tests/e2e/cash/release_refused/scenario.py`
**Commit:** 6b63bb3
**Applied fix:** Updated the three VERIFY hand-derivation docstring tables to the
zero-padded `ORDER-{n:03d}` form so the documented human oracle matches the
re-frozen goldens verbatim. Confirmed against the committed CSVs first:
`scale_in/golden/cash_operations.csv` carries `ORDER-001`..`ORDER-005`, and the
`release_cancelled` / `release_refused` cash leaves carry `ORDER-001`.
- `scale_in/scenario.py`: table rows `ORDER-1`..`ORDER-5` -> `ORDER-001`..`ORDER-005`;
  the `ORDER-{n}` format prose -> `ORDER-{n:03d}`.
- `release_cancelled/scenario.py`: table rows + load-bearing-fact prose
  `ORDER-1` -> `ORDER-001`; format prose `ORDER-{n}` -> `ORDER-{n:03d}`.
- `release_refused/scenario.py`: table rows + load-bearing-fact prose
  `ORDER-1` -> `ORDER-001`; format prose `ORDER-{n}` -> `ORDER-{n:03d}`.
Documentation-only change; AST syntax-checked clean and the full e2e suite
(37 passed) re-ran green with no regression.

### IN-04: serializer `_seq` tiebreak is intentionally absent from the harness `_CASH_OPS_SORT_KEYS`

**Files modified:** `tests/e2e/conftest.py`
**Commit:** 62ffd1a
**Applied fix:** Added a clarifying comment above `_CASH_OPS_SORT_KEYS` at
conftest:122 explaining that the serializer already imposes a total order via the
dropped-before-return `_seq` source-appearance tiebreak, so the harness sort
intentionally mirrors only the business keys. The comment explicitly warns a future
maintainer NOT to add `_seq` to the sort keys (it is not a column on the returned
frame and would crash). Documentation-only; AST syntax-checked clean.

---

_Fixed: 2026-06-10_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
