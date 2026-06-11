---
phase: 08-admission-position-management-cash-edges
reviewed: 2026-06-10T00:00:00Z
depth: standard
iteration: 2
files_reviewed: 14
files_reviewed_list:
  - itrader/reporting/cash_operations.py
  - tests/e2e/conftest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/admission/max_positions/scenario.py
  - tests/e2e/admission/max_positions/test_scenario.py
  - tests/e2e/admission/re_entry/scenario.py
  - tests/e2e/admission/re_entry/test_scenario.py
  - tests/e2e/admission/scale_in/scenario.py
  - tests/e2e/admission/scale_in/test_scenario.py
  - tests/e2e/admission/scale_out/scenario.py
  - tests/e2e/admission/scale_out/test_scenario.py
  - tests/e2e/cash/release_cancelled/scenario.py
  - tests/e2e/cash/release_refused/scenario.py
  - tests/e2e/cash/release_rejected/scenario.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Iteration:** 2 (--auto re-review after fixes for WR-01, WR-02, IN-01, IN-02, IN-03)
**Files Reviewed:** 14
**Status:** issues_found

## Summary

This is iteration-2 re-review confirming the prior-iteration fixes hold and hunting
for regressions introduced by those fixes. I re-ran the phase suite: all 7 scenarios
pass (`7 passed in 0.21s`).

**Prior fixes — confirmed applied and correct:**

- **WR-01 (zero-pad ordinal):** `cash_operations.py:93` now emits `f"ORDER-{n:03d}"`.
  Verified the committed goldens were re-frozen to the padded form
  (`ORDER-001`..`ORDER-005` in `scale_in/golden/cash_operations.csv` and the cash
  leaves). Lexical sort now equals numeric order.
- **WR-02 (duck-typed field guard):** `cash_operations.py:102-119` pins the required
  fields up front and raises an explanatory `TypeError` naming the missing fields /
  the non-enum `operation_type`. I confirmed the real `CashOperation`
  (`portfolio_handler/cash/cash_manager.py`) exposes all five required attributes, so
  the guard is inert on the happy path and only fires on genuine shape drift — no
  regression. A `Bad()` object correctly raises with `"missing fields"`.
- **IN-01 (`_seq` total-order tiebreak):** `cash_operations.py:140-143` carries a
  source-appearance index as the final sort key, then drops it. I confirmed `_seq`
  does NOT leak into the returned frame (columns exactly match
  `CASH_OPERATION_COLUMNS`) and the empty-safe path still returns the header-only
  frame.
- **IN-02 / IN-03 (doc-only):** the `_freeze`/`_roundtrip` FLOAT_FORMAT-on-Decimal
  tracking note (conftest:472-483) and the `release_refused` min/max-cache seam note
  (`release_refused/scenario.py:49-53`) are now documented as recommended.

**Regression introduced by the WR-01 fix (one WARNING).** Re-freezing the goldens to
`ORDER-001` form was correct, but the WR-01 fix did NOT update the VERIFY
hand-derivation tables inside the scenario docstrings, which still print the old
unpadded `ORDER-1`..`ORDER-5`. Under this project's golden-master discipline the
VERIFY note is the documented human oracle the frozen golden is asserted to MATCH
("a human confirmed the frozen goldens MATCH the hand-derivation below"), so the note
and the golden are now contradictory — see WR-03 below.

The IN-01 `_seq` tiebreak lives in the serializer while the harness diff sort
(`_CASH_OPS_SORT_KEYS`, conftest:122) still omits `_seq`. I traced this: it is NOT a
regression — `_diff_frame` re-sorts BOTH fresh and golden by the same keys on the
same row set, so any residual tie resolves identically on both sides and cannot
spuriously fail. The `_seq` correctly belongs only in the serializer (cross-run
golden reproducibility), and the divergence is benign. Noted as IN-04 for the record.

## Warnings

### WR-03: WR-01 re-freeze left the VERIFY hand-derivation tables out of sync with the goldens (`ORDER-1` vs `ORDER-001`)

**File:** `tests/e2e/admission/scale_in/scenario.py:98-105`,
`tests/e2e/cash/release_cancelled/scenario.py:80-82`,
`tests/e2e/cash/release_refused/scenario.py:83-85`
**Issue:** The WR-01 fix zero-padded the derived correlation to `ORDER-{n:03d}` and
the goldens were correctly re-frozen — `scale_in/golden/cash_operations.csv` now
contains `ORDER-001` through `ORDER-005`, and the cash leaves contain `ORDER-001`.
But the VERIFY hand-derivation tables in the same scenarios' docstrings were not
updated and still print the unpadded labels:
- `scale_in/scenario.py:99-105` lists `ORDER-1`, `ORDER-2`, `ORDER-3`, `ORDER-4`,
  `ORDER-5` (plus prose at line 87/107 referencing `ORDER-{n}`).
- `release_cancelled/scenario.py:81-82,84` and `release_refused/scenario.py:84-85,87`
  list `ORDER-1`.

This project's golden-master discipline (CLAUDE.md; the VERIFY blocks themselves:
"HAND-VERIFIED & LOCKED ... a human confirmed the frozen goldens MATCH the
hand-derivation below") makes the VERIFY table the documented human oracle that the
frozen golden is asserted equal to. A reviewer re-verifying the golden against the
note now sees `ORDER-001` in the CSV and `ORDER-1` in the note — a direct
contradiction in the load-bearing audit trail. The test still passes (the harness
diffs golden-vs-fresh, never golden-vs-note), so this is a documentation-integrity
defect, not a test failure, but it defeats the entire purpose of freezing a
hand-verified note alongside the golden.
**Fix:** Update the three VERIFY tables and surrounding prose to the padded form to
match the re-frozen goldens, e.g. in `scale_in/scenario.py`:
```text
    correlation  operation_type        amount    balance_before  balance_after
    ORDER-001    RELEASE_RESERVATION    4000.00   6000.00         6000.00
    ORDER-001    RESERVATION            4000.00  10000.00        10000.00
    ORDER-002    TRANSACTION_DEBIT     -4000.00  10000.00         6000.00
    ORDER-003    RELEASE_RESERVATION    4000.00   2000.00         2000.00
    ORDER-003    RESERVATION            4000.00   6000.00         6000.00
    ORDER-004    TRANSACTION_DEBIT     -4000.00   6000.00         2000.00
    ORDER-005    TRANSACTION_CREDIT     8000.00   2000.00        10000.00
```
and `ORDER-1` -> `ORDER-001` in the two cash-leaf notes (and the `ORDER-{n}` prose
mentions). Alternatively, document the format explicitly ("the serializer pads to
`ORDER-{n:03d}`; this note uses the short form for readability") so the divergence is
intentional rather than a silent mismatch — but matching the golden verbatim is
stronger.

## Info

### IN-04: serializer `_seq` tiebreak is intentionally absent from the harness `_CASH_OPS_SORT_KEYS` — verified benign, document the asymmetry

**File:** `itrader/reporting/cash_operations.py:140-143`, `tests/e2e/conftest.py:122`
**Issue:** The IN-01 fix added `_seq` as the serializer's final sort tiebreak and
drops it before returning, so the harness diff sort (`_CASH_OPS_SORT_KEYS =
["correlation", "operation_type", "amount"]`) cannot and does not see it. I confirmed
this is NOT a regression: `_diff_frame` re-sorts fresh and golden by the identical
key set on the identical row content, so pandas resolves any residual
(correlation, operation_type, amount) tie deterministically and identically on both
sides — the diff cannot spuriously fail. The `_seq` correctly belongs only in the
serializer, whose job is cross-run reproducibility of the frozen golden bytes; the
harness only needs producer/golden agreement, which it already has because both flow
through the same serializer. No committed leaf even exercises a tie today.
**Fix:** None required. Optional one-line comment at conftest:122 noting the
serializer already imposes a total order via `_seq`, so the harness sort intentionally
mirrors only the business keys, to forestall a future maintainer "fixing" a
non-existent divergence by adding `_seq` to `_CASH_OPS_SORT_KEYS` (which would crash —
`_seq` is not a column on the returned frame).

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (iteration 2, --auto re-review)_
