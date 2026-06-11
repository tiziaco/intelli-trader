---
phase: 04-e2e-harness-framework
fixed_at: 2026-06-09T00:00:00Z
review_path: .planning/phases/04-e2e-harness-framework/04-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 04: Code Review Fix Report

**Fixed at:** 2026-06-09
**Source review:** .planning/phases/04-e2e-harness-framework/04-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### WR-05: WR-03 grid-mismatch guard uses `assert` in production code — stripped under `python -O`

**Files modified:** `itrader/reporting/summary.py`
**Commit:** c81579c
**Applied fix:** Replaced the bare `assert fill_time in index, (...)` data-validation
guard in `decision_close` with an explicit `if fill_time not in index: raise
ValueError(...)`. The raise survives `python -O`/`-OO` and `PYTHONOPTIMIZE`, so the
grid-mismatch invariant can no longer be silently stripped from the oracle/harness
run path. `ValueError` matches the module's existing edge-case error style and aligns
with the CLAUDE.md "Error Handling" convention (raise typed exceptions, not bare
asserts). The grid-mismatch message text was preserved verbatim in this commit; the
residual review-tag was removed under IN-06.

### IN-06: Review-artifact tag ("WR-03") leaked into a runtime error message

**Files modified:** `itrader/reporting/summary.py`
**Commit:** 97d7199
**Applied fix:** Dropped the ephemeral `(WR-03)` suffix from the user-facing
`ValueError` message so the runtime error describes the invariant rather than citing
the review iteration that added it. Also removed the leaked review-iteration IDs from
the surrounding inline comment block (`WR-03` on the searchsorted note, `WR-02` on the
diff-stable-0.0 note), rewording them to describe behavior directly. No load-bearing
`D-`/`M5-` decision tags were touched (the comment carried none).

## Verification

- `python3 -c "import ast; ast.parse(...)"` syntax check passed after each edit.
- Re-read of modified sections confirmed fixes present and code intact.
- Gating tests re-run inside the isolated worktree, all green:
  - `tests/integration/test_backtest_oracle.py::test_oracle_behavioral_identity` PASSED
  - `tests/integration/test_backtest_oracle.py::test_oracle_numeric_values` PASSED
  - `tests/e2e/smoke/single_market_buy/test_scenario.py::test_single_market_buy` PASSED
- No golden value changed; the byte-exact oracle gate and canary E2E both reconcile.

---

_Fixed: 2026-06-09_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
