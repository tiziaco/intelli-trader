---
phase: 03-running-pnl-accumulator
reviewed: 2026-06-24T08:20:00Z
depth: standard
iteration: 2
files_reviewed: 3
files_reviewed_list:
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position_manager.py
  - tests/unit/portfolio/test_realised_pnl_accumulator.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: clean
---

# Phase 3: Code Review Report (iteration 2)

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 3
**Status:** clean

## Summary

Re-review of the PERF-02 running realised-PnL accumulator after the iteration-1 fixes
(WR-01 commit `1427ebd`, WR-03/IN-03 commit `09a3b11`, WR-02/IN-01/IN-02 commit
`1abc290`). The three prior warnings and three prior info items were re-verified against
the source. **All three warnings are resolved.** The Decimal-end-to-end discipline,
determinism convention, and tab/space indentation convention all hold. The full suite for
these files (`test_realised_pnl_accumulator.py` + `test_position_manager.py`, 33 tests)
passes, and the accumulator was independently traced through spot LONG, margin LONG, SHORT,
and emergency-close lifecycles producing nonzero realised PnL that matches a fresh
dual-loop re-sum byte-for-byte.

### Verification of prior findings

**WR-01 (close_all_positions bypass) — RESOLVED.** `close_all_positions`
(`position_manager.py:491-506`) now captures `prior_realised` before `_close_position`
and feeds `apply_realised_increment(position.realised_pnl - prior_realised)`. The
double-count hazard the prior fix note flagged is **avoided correctly**: `_close_position`
itself does NOT call `apply_realised_increment` (verified at `position_manager.py:215-229`),
so the increment is fed exactly once per close path — externally by the two Portfolio
settle arms (`portfolio.py:376`, `:548`) on the normal path, and externally by
`close_all_positions` on the emergency path. Traced a partial-close-then-emergency-close
scenario: the position's already-realised PnL was fed by the partial-close settle arm,
`close_position` does not mutate `realised_pnl`, so the emergency-close increment is `0` —
no under-count, no double-count. The chosen funnel (Portfolio arms + `close_all_positions`,
NOT `_close_position`) is internally consistent.

**WR-02 (margin/SHORT/multi-ticker coverage) — RESOLVED.** Three new equivalence tests
were added against the same `_resum_realised` oracle with `==` assertions:
`test_accumulator_equals_resum_margin_open_partial_full` (margin arm),
`test_accumulator_equals_resum_short_lifecycle_spot` (SHORT realised_pnl branch), and
`test_accumulator_equals_resum_two_tickers_interleaved` (cross-ticker). Independent
re-run confirms these exercise real nonzero realised PnL (e.g. SHORT cover: 3000 partial,
8000 full), so they are not trivially passing on zeros.

**WR-03 (silent desync outside the funnel) — RESOLVED (downgraded residual, see IN-01).**
The `assert_accumulator_consistent` enforcement seam was added
(`position_manager.py:341-372`): it recomputes the dual open+closed re-sum and raises
`PositionCalculationError` on divergence. It was independently invoked after a populated
lifecycle and correctly passed. This satisfies the "if the funnel-only contract is
intentional, add a gated assert seam" branch of the prior WR-03 fix. The residual (the seam
has no caller) is downgraded to IN-01 because the funnel-only contract is now sound and
documented; the seam is a debug/test affordance, not a correctness gap.

**IN-01/IN-02/IN-03 (prior) — RESOLVED.** The test file uses a fixed
`_FIXED_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)` everywhere (no `datetime.now()`),
passes `Decimal` money at all call sites, and the `get_total_realized_pnl` docstring now
correctly states it returns the running accumulator.

No new BLOCKER or WARNING defects were introduced by the fixes. Two minor INFO items remain.

## Info

### IN-01: `assert_accumulator_consistent` enforcement seam has no caller

**File:** `itrader/portfolio_handler/position/position_manager.py:341-372`
**Issue:** The WR-03 fix added `assert_accumulator_consistent` as a "GATED test/debug seam"
to fail loud on accumulator desync, but no test or runtime path invokes it (the only
reference in the repo is its own docstring at `position_manager.py:332`). The new
equivalence tests assert `_realised_pnl_accumulator == _resum_realised(pm)` directly with
their own oracle rather than calling this method, so the seam's own logic
(the `PositionCalculationError` raise branch) is never exercised. It is therefore correct
but dead — it documents the contract in executable form without enforcing it anywhere a
regression would trip it. This is not a correctness defect (the contract is independently
covered by the equivalence tests' inline `==` assertions), only a dead-affordance smell.
**Fix (optional):** Either call `pm.assert_accumulator_consistent()` once at the end of
each lifecycle equivalence test (so the seam's raise branch is covered and a future desync
trips through the documented enforcement path), or add a dedicated negative test that
manually desyncs the accumulator and asserts the seam raises. Otherwise the method risks
being flagged as unused and removed, re-opening the WR-03 enforcement gap.

### IN-02: `close_all_positions` increment is provably always zero for its only realistic call shape

**File:** `itrader/portfolio_handler/position/position_manager.py:503-505`
**Issue:** The WR-01 fix feeds `position.realised_pnl - prior_realised`, but
`Position.close_position` (`position.py:265-272`) only sets `is_open`, `exit_date`, and
`current_price` — it never alters `buy_quantity`/`sell_quantity`/`avg_*`/commissions, so
`realised_pnl` is unchanged across the close and the fed increment is ALWAYS `Decimal("0")`.
The non-zero realised PnL of a position being emergency-closed (if any) was already fed by
its prior partial-close settle arms; the closed-list re-sum then counts the same value, so
the accumulator stays consistent. The fix is correct, but the `apply_realised_increment`
call is effectively a no-op given `close_position`'s semantics — the comment at lines
493-502 implies it recovers dropped realised PnL, which slightly overstates its mechanical
effect (it preserves consistency by being symmetric with the settle arms, not by
contributing a non-zero increment).
**Fix (optional):** Keep the call (it is correctly defensive and symmetric), but tighten
the comment to note the increment is structurally zero because `close_position` does not
realise PnL — the value of the call is that it is a *no-op that stays a no-op* if
`close_position` semantics ever change to realise the remaining quantity, not that it
currently recovers dropped PnL.

---

_Reviewed: 2026-06-24 (iteration 2)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
