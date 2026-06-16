---
phase: 04-liquidation-cross-validation-re-baseline
plan: 02
subsystem: portfolio_handler (margin/cash accounting seam)
tags: [WR-04, margin, solvency-assertion, call-order, regression-test]
requirements-completed: [LIQ-01]
dependency-graph:
  requires:
    - "Phase 2 Plan 04: lock-and-settle margin model (CashManager position-keyed locked_margin + assert_lock_fits_buying_power)"
    - "Phase 3: shorts/carry seam that surfaced WR-04 in deferred-items"
  provides:
    - "Correct WR-04 call-order on the margin-lock seam: get_locked_margin_for (the WB source the 04-03 liquidation floor reads) is now accounted before liquidation reads it"
  affects:
    - "04-03 (liquidation floor) — re-touches the same margin seam; now reads a correctly-accounted prior lock"
tech-stack:
  added: []
  patterns:
    - "Settlement-side solvency assertion runs BEFORE state release (assert-before-release call-order contract)"
key-files:
  created:
    - "tests/unit/portfolio/test_wr04_lock_fits_buying_power.py"
  modified:
    - "itrader/portfolio_handler/portfolio.py"
    - "itrader/portfolio_handler/cash/cash_manager.py"
decisions:
  - "Fix shape = Option A (assert BEFORE release), not Option B (thread prior_lock kwarg): no signature change, keeps assert_lock_fits_buying_power the single canonical add-back reader, and the call-order is the natural correct ordering"
  - "Regression test pins the CALL-ORDER CONTRACT on the real Portfolio margin path (spy on the prior lock the assertion observes), because the numeric outcome of the two orderings coincides today — the test must distinguish the orderings, not just the number"
metrics:
  duration-min: 7
  completed: 2026-06-16
  tasks: 2
  files: 3
---

# Phase 4 Plan 02: WR-04 Lock-Fits-Buying-Power Call-Order Fix Summary

Fixed the WR-04 carry-forward defect on the margin-lock seam: both `portfolio.py` margin-lock
sites now run `assert_lock_fits_buying_power` BEFORE `release_margin`, so the solvency
assertion's documented add-back reads the position's TRUE prior lock via `get_locked_margin_for`
instead of `0`. The SMA_MACD oracle stays byte-exact (WR-04 is oracle-dark on the spot path).

## What Was Built

- **Task 1 (TDD) — WR-04 fix + regression test:**
  - `portfolio.py` (TABS), open/scale-in arm (~430) and partial/full-close arm (~449): reordered
    to `assert → release → lock`. On the close arm, the assert+release+lock now run only inside the
    `position.is_open` branch (the recomputed remaining lock is what the guard checks); a full close
    falls to a bare `release_margin` in the `else`.
  - `cash_manager.py` (4 SPACES): pinned the WR-04 CALL-ORDER CONTRACT in the
    `assert_lock_fits_buying_power` docstring — callers MUST invoke the guard while the position's
    prior lock is still present, since the add-back reads `get_locked_margin_for(position_id)`.
  - `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` (4 SPACES, 3 tests): two call-order
    tests drive the real `Portfolio.process_transaction` margin scale-in / partial-close path and
    spy on the prior lock the assertion observes (RED: `Decimal('0')` under the defect; GREEN: the
    true prior lock 10000 / 20000); one isolated-CashManager test pins the no-leak loud guard.

- **Task 2 — proof gate (no code change):** oracle byte-exact + portfolio suite green.

## Verification Results

- `pytest tests/unit/portfolio -k "lock_fits_buying_power" -x` → 3 passed (selects all 3).
- `pytest tests/integration/test_backtest_oracle.py -x` → 3 passed (byte-exact: behavioral identity +
  numeric values 134 / 46189.87730727451).
- `pytest tests/unit/portfolio/` → 255 passed (no margin regression; includes the 3 new WR-04 tests).
- `mypy --strict itrader/portfolio_handler/portfolio.py itrader/portfolio_handler/cash/cash_manager.py`
  → Success, no issues in 2 source files.
- Indentation preserved: `portfolio.py` edited region TABS, `cash_manager.py` + new test 4-SPACE.
- RED proven: reverting `portfolio.py` to the defect ordering failed the two call-order tests
  (`assert Decimal('0') == Decimal('10000')` / `== Decimal('20000')`); the loud-guard test passed in
  both states (correct — it is the no-leak invariant, not ordering-dependent).

## Deviations from Plan

### Plan-premise clarification (not a code deviation)

The plan's Task-1 Test-1 premise — "today it raises because it reads `own_prior_lock == 0`" — does
NOT hold for the real code path. `release_margin` pops the lock into `available_balance` live, so
`available_after_release + 0 == available_before + own_prior_lock`: the defect and the fix produce
the SAME buying-power figure (WR-04 is genuinely "conservative, not a leak", as deferred-items
states — and on the L=1 single-position path it is fully inert, not merely conservative). A unit
test asserting a false-reject would have passed before the fix (TDD fail-fast trigger).

Resolution (within plan scope, no architectural change): the regression test was written to pin the
**call-order contract** on the real `Portfolio` margin path via a spy on the prior lock the
assertion observes, rather than a numeric pass/raise. This is the behavior the fix actually changes
and the invariant the FRAGILE seam needs protected for 04-03. The three required behaviors are
honored in spirit: scale-in add-back credited (Test 1), genuine over-lock still raises (Test 2),
partial-close add-back honored (Test 3).

### cash_manager.py modification

Option A needs no functional change to `assert_lock_fits_buying_power` (the assertion code was
already correct — the bug was purely call-order in `portfolio.py`). To honor the plan's artifact
contract (cash_manager.py listed as modified, "reads the prior lock add-back correctly") and to pin
the invariant the fix depends on, a WR-04 CALL-ORDER CONTRACT note was added to the docstring. This
is correctness documentation of the seam, not a cosmetic edit.

## Self-Check: PASSED

- `itrader/portfolio_handler/portfolio.py` — FOUND (2 `WR-04 (Plan 04-02)` markers)
- `itrader/portfolio_handler/cash/cash_manager.py` — FOUND (1 `WR-04 (Plan 04-02)` marker)
- `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` — FOUND
- Commit 897ef66 — FOUND in git log
