---
phase: 03-running-pnl-accumulator
plan: 01
subsystem: portfolio
tags: [performance, decimal, accumulator, realised-pnl, position-manager, perf-02]

# Dependency graph
requires:
  - phase: 01-perf-tooling-baseline
    provides: W1 benchmark harness + re-frozen baseline (gate (b) measurement); byte-exact SMA_MACD oracle gate (a)
  - phase: 02-order-storage-indexing
    provides: audit-the-invariant + dedicated equivalence-test precedent (D-04/D-09) reused here as D-02/D-03
provides:
  - Running Decimal realised-PnL accumulator on PositionManager (O(1) get_total_realized_pnl, no per-bar dual re-sum)
  - apply_realised_increment funnel call wired into both Portfolio settle arms (spot + margin)
  - Written single-funnel invariant audit (03-INVARIANT-AUDIT.md) locking the D-02 contract
  - Equivalence regression test (accumulator == fresh full re-sum) through the Portfolio funnel
affects: [04-hot-path-discipline, 05-incremental-indicators, perf gate-b re-freeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Running accumulator cache fed from the existing close funnel (facade->manager, no back-reference)"
    - "Audit-the-invariant + dedicated equivalence test, NO hot-path runtime guard (Phase 2 precedent)"

key-files:
  created:
    - .planning/phases/03-running-pnl-accumulator/03-INVARIANT-AUDIT.md
    - tests/unit/portfolio/test_realised_pnl_accumulator.py
  modified:
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/portfolio_handler/portfolio.py

key-decisions:
  - "D-01: PositionManager owns the accumulator; get_total_realized_pnl returns the field, no loop"
  - "D-02: fed via apply_realised_increment from BOTH Portfolio settle arms (spot path added — it had no explicit increment)"
  - "D-05: seed Decimal('0.00'), no mid-sum quantize — per-bar value byte-identical, not merely =="
  - "D-04: collapsing the dead dual re-sum loop is intrinsic to the change (not a separate cleanup)"

patterns-established:
  - "Pattern 1: running realised-PnL cache fed unconditionally from each settle arm (open/scale-in yield increment 0, byte-safe)"
  - "Pattern 2: three-layer correctness lock — written invariant audit + byte-exact oracle/determinism + dedicated equivalence test"

requirements-completed: [PERF-02]

# Metrics
duration: 5min
completed: 2026-06-24
---

# Phase 3 Plan 01: Running PnL Accumulator Summary

**Replaced the O(positions)-growing-to-O(n²) per-bar dual open+closed realised-PnL re-sum in `PositionManager.get_total_realized_pnl` with an O(1) running `Decimal` accumulator fed from both `Portfolio` settle arms — byte-identical (SMA_MACD oracle held 134 / 46189.87730727451).**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-24T06:38:18Z
- **Completed:** 2026-06-24T06:43Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **Loop-free `get_total_realized_pnl`:** now returns `self._realised_pnl_accumulator` (a `Decimal('0.00')`-seeded running field) instead of re-summing over open + closed positions every bar — the ~13% W1 hotspot #3 (PERF-02) eliminated.
- **Both settle arms wired:** `apply_realised_increment` is called from the margin CLOSE branch (reusing the existing `realised_increment`) AND the spot arm (which had no explicit increment today — added pre/post capture mirroring the margin arm). The SMA_MACD oracle is a spot run, so the spot wiring is load-bearing.
- **Three-layer correctness lock:** written single-funnel invariant audit (`03-INVARIANT-AUDIT.md`), the byte-exact oracle + determinism double-run, and a dedicated equivalence regression test asserting `accumulator == fresh full re-sum` across open / scale-in / partial / full closes.
- **Gate (a) green:** oracle byte-exact (134 / 46189.87730727451), `mypy --strict` clean (187 files), full suite 1241 passed, determinism double-run byte-identical (trades/equity/summary).

## Task Commits

Each task was committed atomically:

1. **Task 1: Audit and lock the single-funnel realised_pnl invariant** - `cd5875e` (docs)
2. **Task 2: Add the accumulator + apply method and wire both close arms** - `07ec0b4` (perf)
3. **Task 3: Equivalence regression test + gate (a)** - committed with plan metadata (test + SUMMARY)

**Plan metadata:** see final docs commit (SUMMARY + STATE + ROADMAP + REQUIREMENTS)

_Note: Task 3 is `tdd="true"`. The implementation it tests landed in Task 2 (the plan sequences the equivalence drift-lock test after the production change). The test was verified meaningful — the accumulator is non-trivially $21,000 after the full-close scenario and matches the independent dual-loop oracle, so the test would fail on a broken accumulator. Per the TDD fail-fast rule, a pre-existing-implementation pass is the expected state here (the test is a regression drift-lock, not driver of new production code)._

## Files Created/Modified

- `itrader/portfolio_handler/position/position_manager.py` (4-space) - Added `_realised_pnl_accumulator` field (seeded `Decimal('0.00')`), `apply_realised_increment` method (no quantize), and rewrote `get_total_realized_pnl` to return the field (dead dual loop collapsed).
- `itrader/portfolio_handler/portfolio.py` (TAB) - Spot arm: added `prior_realised` pre-capture + post-mutation `realised_increment` + `apply_realised_increment` call. Margin arm: added `apply_realised_increment(realised_increment)` on the CLOSE branch (reusing the existing increment).
- `.planning/phases/03-running-pnl-accumulator/03-INVARIANT-AUDIT.md` - Written D-02 single-funnel audit + spot-vs-margin two-arm reconciliation + locked invariant.
- `tests/unit/portfolio/test_realised_pnl_accumulator.py` (4-space) - Equivalence drift-lock: independent `_resum_realised` oracle + funnel-driven open/scale-in/partial/full-close test.

## Decisions Made

- **Spot arm wiring is load-bearing (audit finding):** The plan/PATTERNS anchored only the margin arm's explicit `realised_increment`. The audit (Task 1) surfaced that the spot arm — the SMA_MACD oracle path — has no explicit increment today, so margin-only wiring would feed the accumulator nothing on the golden run and silently return a constant `Decimal('0.00')`. Both arms feed the accumulator; the spot increment is applied unconditionally (open/scale-in yield `0`, byte-safe).
- Followed all locked decisions D-01..D-07 as specified.

## Deviations from Plan

None - plan executed exactly as written. All 3 tasks completed; all acceptance criteria met.

**Acceptance-criterion note (Task 3, not a deviation):** The grep guard `grep -rn "for .* in .*get_closed_positions" position_manager.py` (intended to prove the realised-PnL dual re-sum loop is gone, not relocated) matches one line — `position_manager.py:344` — but that is the **pre-existing** `calculate_position_metrics` position-lookup-by-id loop (last touched by an unrelated prior commit, off the per-bar hot path), NOT a relocated re-sum. The criterion's intent is satisfied: `get_total_realized_pnl` is a bare `return self._realised_pnl_accumulator` (verified via AST — no `for` loop), and no re-sum loop was relocated into it or a new helper. The grep pattern is an over-broad false positive against an unrelated lookup loop.

## Issues Encountered

None. The implementation, audit, and test all landed cleanly; gate (a) was green on first run.

## Known Stubs

None - no stubs, placeholders, or unwired data sources introduced. The accumulator is fed from a real, audited code path on every reducing fill.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Gate (a) PASSED** — the behavior-preserving guarantee held (oracle byte-exact, determinism byte-identical, mypy clean, full suite green). Phase 3 re-baselined nothing.
- **Gate (b) (W1 wall-clock re-freeze) is Plan 02's concern** — this plan delivered the optimization + correctness locks; the W1 benchmark measurement + baseline re-freeze for PERF-02 follows in the next plan of this phase per the phase's two-plan split (Plan 1 = optimize + lock correctness; gate (b) measurement separate).
- No blockers for Phase 4 (Hot-Path Discipline).

## Self-Check: PASSED

- Files: all 4 FOUND (`position_manager.py`, `portfolio.py`, `test_realised_pnl_accumulator.py`, `03-INVARIANT-AUDIT.md`)
- Commits: `cd5875e` (Task 1) FOUND, `07ec0b4` (Task 2) FOUND
- Gate (a): oracle 3/3 byte-exact, mypy 187 files clean, full suite 1241 passed, determinism double-run byte-identical

---
*Phase: 03-running-pnl-accumulator*
*Completed: 2026-06-24*
