---
phase: 08-m5c-cross-validation-final-oracle
plan: 08
subsystem: testing
tags: [cross-validation, golden-oracle, backtesting.py, backtrader, nautilus-trader, sortino, win-rate, D-05]

# Dependency graph
requires:
  - phase: 08-07
    provides: "CROSS-VALIDATION.md reconciliation table — 134/134 trades aligned (D-02 GREEN), 4 SECONDARY metric divergences flagged for disposition"
  - phase: 08-03
    provides: "REFREEZE-M5C-DECIMAL golden oracle (tests/golden/{trades.csv,equity.csv,summary.json}) — the baseline iTrader is defended as correct against"
provides:
  - "Per-divergence D-05 root-cause dispositions (0 BUG, 4 LEGITIMATE-DIFFERENCE) appended to CROSS-VALIDATION.md"
  - "Owner sign-off (APPROVED) recorded — accepts the no-bug/no-re-freeze verdict as the basis for the 08-09 final oracle freeze"
  - "Confirmation that golden artifacts are unchanged (no re-freeze) and the 724-test suite + oracle test are green"
affects: [08-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-05 disposition: root-cause every cross-validation divergence; iTrader is correct unless the trace proves a defect; never calibrate to reference engines"

key-files:
  created:
    - .planning/phases/08-m5c-cross-validation-final-oracle/08-08-SUMMARY.md
  modified:
    - tests/golden/CROSS-VALIDATION.md

key-decisions:
  - "0 BUG / 4 LEGITIMATE-DIFFERENCE verdict — no iTrader defect found; iTrader's post-M5b numbers kept; NO re-freeze (owner-approved)"
  - "3× sortino divergence = entry-bar equity-marking convention (timing-of-marking artifact, fully attributed: 134 differing bars == 134 trade-entry bars)"
  - "1× nautilus win_rate divergence = NETTING fill arithmetic on a 2025 rapid-round-trip cluster; iTrader's 49-winner count corroborated by BOTH gating engines"

patterns-established:
  - "Owner sign-off on a conditional result-changing plan is recorded in CROSS-VALIDATION.md even when the verdict is no-op (no-bug/no-re-freeze still requires the blocking acceptance gate)"

requirements-completed: [M5-10]

# Metrics
duration: ~25min (across the checkpoint)
completed: 2026-06-08
---

# Phase 08 Plan 08: Cross-Validation Root-Cause Dispositions Summary

**Every cross-validation divergence root-caused and dispositioned per D-05 — verdict 0 BUG / 4 LEGITIMATE-DIFFERENCE, owner-approved with no iTrader defect and no re-freeze, locking the existing golden as the basis for the 08-09 final oracle freeze.**

## Performance

- **Duration:** ~25 min (spanning the blocking human-verify checkpoint)
- **Completed:** 2026-06-08
- **Tasks:** 3 (Task 1 disposition + Task 2 conditional no-op completed pre-checkpoint; Task 3 owner sign-off completed on resume)
- **Files modified:** 1 (tests/golden/CROSS-VALIDATION.md)

## Accomplishments

- **D-02 PRIMARY gate confirmed fully GREEN:** all 134 trades align exactly (entry + exit dates) across iTrader, backtesting.py, backtrader, and nautilus — zero SHIFT, zero MISSING — so there are no trade-count or trade-timing divergences to disposition.
- **All 4 SECONDARY metric divergences dispositioned as LEGITIMATE-DIFFERENCE (Task 1):**
  - 3× sortino (backtesting.py 1.025097, backtrader 1.026906, nautilus 1.025410 vs iTrader 1.038504) traced to a single iTrader entry-bar equity-marking convention. backtrader is the smoking gun: byte-identical trade log AND byte-identical final equity, yet a divergent sortino — proving the gap lives only in the intermediate per-bar equity PATH. Exactly 134 bars differ, mapping one-to-one onto the 134 trade-entry dates (no residual).
  - 1× nautilus win_rate (0.358209 / 48 winners vs iTrader 0.365672 / 49 winners) traced to nautilus NETTING fill arithmetic on a 2025 rapid-round-trip cluster (3 borderline sign-flips on trades #121/#124/#126). iTrader's 49-winner count is corroborated by BOTH gating engines; the lone dissent is the non-gating engine.
- **Conditional bug-fix path was a documented no-op (Task 2):** zero BUG rows → no `REFREEZE-M5C-<bug>.md` note authored, golden artifacts unchanged, recorded as "no iTrader bug found; no re-freeze."
- **Owner sign-off recorded (Task 3, this resume):** owner responded "approved", accepting the verdict as the basis for the 08-09 final oracle freeze. The sign-off captures the additional per-trade corroboration the owner reviewed during the checkpoint (backtrader matched iTrader to the cent on all 3 disputed trades; backtesting.py within a few dollars, never flipping sign; only nautilus flipped them).

## Task Commits

1. **Task 1: Trace and disposition every divergence row (D-05)** - `f98ae14` (docs) — "## Root-Cause Dispositions" section appended to CROSS-VALIDATION.md
2. **Task 2: Conditional bug fix + re-freeze** - no-op, recorded in `f98ae14` (zero BUG rows; golden artifacts unchanged)
3. **Task 3: Owner sign-off (approved)** - recorded in the metadata commit below (no code change, no re-freeze)

**Plan metadata:** see final docs commit (CROSS-VALIDATION.md owner sign-off + SUMMARY.md + STATE.md + ROADMAP.md)

## Files Created/Modified

- `tests/golden/CROSS-VALIDATION.md` - Added "## Owner Sign-Off" section recording the APPROVED verdict (0 BUG / 4 LEGITIMATE-DIFFERENCE, no re-freeze) and the per-trade corroboration on trades #121/#124/#126. (The "## Root-Cause Dispositions" section was added in f98ae14.)
- `.planning/phases/08-m5c-cross-validation-final-oracle/08-08-SUMMARY.md` - This summary.

## Decisions Made

- **0 BUG / 4 LEGITIMATE-DIFFERENCE, no re-freeze (D-05 default upheld):** iTrader is correct unless the trace proves a defect; all four divergences are fully-attributed reference-engine semantic differences, so iTrader's post-M5b numbers are kept and the golden artifacts stay byte-identical to the 08-03 REFREEZE-M5C-DECIMAL freeze.
- **Owner accepted the verdict** as the basis for 08-09's final oracle freeze (blocking human-verify checkpoint resolved "approved").

## Deviations from Plan

None - plan executed exactly as written. Task 2's bug-fix branch was correctly a no-op because Task 1 found zero BUG rows; this is the plan's documented CONDITIONAL behavior, not a deviation.

## Issues Encountered

None. The blocking human-verify checkpoint (Task 3) paused execution until owner sign-off; the owner approved, and this resume recorded the sign-off and completed the plan.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Ready for 08-09 (final oracle freeze + D-13 definition-of-done gate):** the cross-validation evidence is closed out with a defensible per-divergence verdict and an owner sign-off. The golden oracle is unchanged (no re-freeze), so 08-09 freezes the final oracle on the existing `tests/golden/{trades.csv,equity.csv,summary.json}`.
- No blockers. The 724-test suite (including the frozen-oracle run-path integration test) is green; determinism preserved.

## Self-Check: PASSED

- FOUND: `.planning/phases/08-m5c-cross-validation-final-oracle/08-08-SUMMARY.md`
- FOUND: "## Owner Sign-Off" section + "APPROVED" in `tests/golden/CROSS-VALIDATION.md`
- FOUND: Task 1 commit `f98ae14` ("## Root-Cause Dispositions")
- CONFIRMED: golden artifacts (`tests/golden/{trades.csv,equity.csv,summary.json}`) UNCHANGED (no re-freeze)
- CONFIRMED: 724-test suite green (includes frozen-oracle run-path integration test)

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*
