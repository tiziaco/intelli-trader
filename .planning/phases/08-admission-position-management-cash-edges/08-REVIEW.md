---
phase: 08-admission-position-management-cash-edges
reviewed: 2026-06-10T00:00:00Z
depth: standard
iteration: 3
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
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 08: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Iteration:** 3 (final --auto re-review after fixes for WR-03, IN-04)
**Files Reviewed:** 14
**Status:** clean

## Summary

This is the iteration-3 (final) re-review. It confirms the two iteration-2 fixes
(WR-03 VERIFY-table padding sync, IN-04 conftest comment) landed correctly and hunts
adversarially for any regression they introduced. The phase suite is green: `7 passed
in 0.23s` over `tests/e2e/admission` + `tests/e2e/cash`. No open findings remain.

**Iteration-2 fixes — confirmed applied and correct:**

- **WR-03 (VERIFY tables out of sync with re-frozen goldens):** RESOLVED. A targeted
  grep across all phase `scenario.py` docstrings finds ZERO unpadded `ORDER-<digit>`
  labels remaining; every VERIFY hand-derivation table now prints the padded
  `ORDER-001`..`ORDER-005` form. I diffed each table against its frozen golden byte
  set:
  - `scale_in/scenario.py:99-105` matches `scale_in/golden/cash_operations.csv`
    (`ORDER-001` x2, `ORDER-002`, `ORDER-003` x2, `ORDER-004`, `ORDER-005`; amounts,
    balance_before, balance_after all reconcile).
  - `release_cancelled/scenario.py:81-82` and `release_refused/scenario.py:84-85`
    match their goldens (`ORDER-001` RESERVATION/RELEASE_RESERVATION pair, 3200 and
    4000 respectively). Surrounding prose (`ORDER-{n}` / "SAME ORDER-001") is
    consistent.
  The note-vs-golden contradiction that motivated WR-03 is gone; the load-bearing
  human-oracle audit trail is internally consistent again.

- **IN-04 (serializer `_seq` tiebreak asymmetry vs harness sort):** RESOLVED. The
  forestalling comment is present at `conftest.py:122-127`, explaining that the
  serializer already imposes a total order via the dropped `_seq` and that adding
  `_seq` to `_CASH_OPS_SORT_KEYS` would crash (it is not a column on the returned
  frame). This matches the recommended fix exactly. I re-confirmed the underlying
  behavior is benign: `_diff_frame` re-sorts fresh and golden by the identical key
  set on identical row content, so any residual `(correlation, operation_type,
  amount)` tie resolves deterministically and identically on both sides.

**Regression hunt — none found.** I specifically checked the surfaces the two fixes
touched:

- The WR-03 edits are docstring-only; they cannot alter runtime behavior, and the
  suite still passes with byte-exact goldens. No golden was re-frozen this iteration
  (the committed CSVs already carried the padded form from iteration 1's WR-01
  re-freeze).
- The IN-04 edit is a comment-only addition to `conftest.py`; no executable code
  changed.

**Independent re-verification of earlier fixes (still holding):**

- `cash_operations.py:93` emits `f"ORDER-{_ordinals[ref]:03d}"` (WR-01); the
  duck-typed field/enum guard (`cash_operations.py:102-119`, WR-02) fires only on
  shape drift; the `_seq` total-order tiebreak (`cash_operations.py:140-143`, IN-01)
  is dropped before return so the frame columns equal `CASH_OPERATION_COLUMNS`.
- The WR-03 UTC date-frame anchoring is consistent across BOTH producers
  (`conftest.py:212` `_make_on_tick` and `scripted_emitter.py:132` `generate_signal`),
  and the committed bar CSVs are UTC-stamped, so the operator-hook date key and the
  emitter decision-date key agree — verified against `max_positions/bars.csv` and
  `bars_eth.csv`.
- Cross-validation of goldens against their VERIFY derivations holds end-to-end:
  `scale_out` `avg_sold=135` / `slippage_exit=-25.0`; `re_entry` two round-trips at
  `realised_pnl=400` each; `release_rejected` REJECTED row `quantity=1000`;
  `max_positions` REJECTED row `quantity=0` (gate-before-sizing). All numbers
  reconcile.

All reviewed files meet quality standards. No issues found.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (iteration 3, --auto re-review, final)_
