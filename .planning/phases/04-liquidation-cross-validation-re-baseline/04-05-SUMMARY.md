---
phase: 04-liquidation-cross-validation-re-baseline
plan: 05
subsystem: testing
tags: [golden-master, cross-validation, liquidation, owner-sign-off, determinism, e2e]

# Dependency graph
requires:
  - phase: 04-liquidation-cross-validation-re-baseline (Plan 04-04)
    provides: cross-validation evidence (CROSS-VALIDATION-ACCOUNTING.md per-scenario reconciliation tables, crossval runners) + the 3 new liquidation e2e leaves
provides:
  - APPROVED Owner Sign-Off block in CROSS-VALIDATION-ACCOUNTING.md (D-12, attributed tiziaco 2026-06-16)
  - the single accounting-core golden frozen across all 7 scenario leaves (D-10) via FROZEN freeze-provenance banners
  - liquidation determinism double-run gate (scripts/determinism_liquidation_double_run.py)
  - phase gate proof — SMA_MACD oracle byte-exact, mypy --strict clean, determinism byte-identical, full suite green
affects: [v1.4 milestone close, future margin/leverage/shorts work, trailing-stop phase, pair-trading capstone]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Owner-gated golden freeze: blocking human-verify checkpoint -> APPROVED sign-off with full attribution -> freeze (D-12)"
    - "FROZEN freeze-provenance banner (white-box e2e kept, no golden-diff harness) replacing PARKED — NOT A GOLDEN (D-10)"
    - "SCRIPT-ONLY determinism double-run under scripts/ (never imported by tests; keeps filterwarnings=[error] intact)"

key-files:
  created:
    - scripts/determinism_liquidation_double_run.py
  modified:
    - tests/golden/CROSS-VALIDATION-ACCOUNTING.md
    - tests/e2e/levered_long/test_levered_long_scenario.py
    - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
    - tests/e2e/short_carry/test_short_carry_scenario.py
    - tests/e2e/partial_cover/test_partial_cover_scenario.py
    - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
    - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
    - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py

key-decisions:
  - "Kept all 7 leaves in white-box-asserted form (no golden/ dir); freeze = FROZEN freeze-provenance banner citing the owner sign-off date (per 04-PATTERNS: load-bearing asserts are liquidation/margin INTERNALS the trades/equity/summary CSVs don't capture)"
  - "Verdict recorded for the freeze: 0 BUG / 25 divergence rows (12 INFORMATIONAL tiny-series metrics + 13 LEGITIMATE-DIFFERENCE D-08 directional-only liquidation)"
  - "Liquidation determinism gate is a standalone scripts/ double-run (no Makefile target existed); short_carry e2e already covers the carry double-run, this covers the forced-close path"

patterns-established:
  - "Pattern 1: owner-gated accounting-core golden freeze — APPROVED sign-off with attribution gates the freeze (D-12)"
  - "Pattern 2: freeze-provenance banner on white-box e2e leaves (D-10) — mirrors the CROSS-VALIDATION.md APPROVED block format"

requirements-completed: [XVAL-01]

# Metrics
duration: 8min
completed: 2026-06-16
---

# Phase 4 Plan 05: Owner-Gated Accounting-Core Golden Freeze Summary

**The single owner-gated accounting-core golden re-baseline — APPROVED sign-off (tiziaco, 2026-06-16) flips CROSS-VALIDATION-ACCOUNTING.md to APPROVED and freezes all 7 scenario leaves (4 parked P2/P3 + 3 new P4 liquidation) as ONE golden, with SMA_MACD byte-exact and the full phase gate green.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-16T11:23Z
- **Completed:** 2026-06-16T11:31Z
- **Tasks:** 3 (Task 1 checkpoint pre-approved by orchestrator; Tasks 2-3 executed)
- **Files modified:** 8 (1 created, 7 modified)

## Accomplishments
- Recorded the owner sign-off (D-12): flipped the CROSS-VALIDATION-ACCOUNTING.md Owner Sign-Off block to `Status: APPROVED` with full attribution (Approved-by: tiziaco (tiziano.iaco@gmail.com), 2026-06-16), mirroring the CROSS-VALIDATION.md APPROVED block format and recording the 0 BUG / 25-divergence verdict.
- Froze the single accounting-core golden (D-10): replaced the `PARKED — NOT A GOLDEN` banner with a `FROZEN — ACCOUNTING-CORE GOLDEN` freeze-provenance banner citing the sign-off date on all 7 scenario leaves (levered_long, short_roundtrip, short_carry, partial_cover, forced_liq_long, forced_liq_short, levered_long_into_liquidation). No `PARKED — NOT A GOLDEN` banner remains.
- SMA_MACD goldens untouched (D-11) — `tests/golden/{trades,equity,summary}` byte-identical (git diff empty); the oracle holds 134 / 46189.87730727451.
- Phase gate green: oracle byte-exact, `mypy --strict itrader` clean (163 files), a new liquidation determinism double-run byte-identical, full suite 1146 passed.

## Task Commits

1. **Task 1: Owner sign-off checkpoint (D-12)** — pre-approved by the orchestrator (owner tiziaco, 2026-06-16); no commit (checkpoint, not code).
2. **Task 2: Freeze accounting-core golden + record Owner Sign-Off** — `ce0e3e9` (docs)
3. **Task 3: Phase gate + liquidation determinism double-run** — `1547b92` (test)

**Plan metadata:** committed separately with this SUMMARY.

## Files Created/Modified
- `scripts/determinism_liquidation_double_run.py` (created) — SCRIPT-ONLY liquidation determinism gate; drives the forced-liq LONG engine twice and asserts the cash/position/PnL trajectory byte-identical.
- `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` — Owner Sign-Off block flipped to APPROVED with attribution + the per-scenario verdict.
- `tests/e2e/{levered_long,short_roundtrip,short_carry,partial_cover,forced_liq_long,forced_liq_short,levered_long_into_liquidation}/test_*_scenario.py` — `PARKED — NOT A GOLDEN` banner replaced with the D-10/D-12 FROZEN freeze-provenance banner.

## Decisions Made
- Chose the white-box-asserted freeze form (FROZEN freeze-provenance banner, NO `golden/` dir + `run_scenario`) per 04-PATTERNS.md: the load-bearing assertions are liquidation/margin INTERNALS (isolated liq price, breach-bar forced-close FillEvent, penalty-on-commission, WB-capped loss, LIQUIDATION-tagged mirror reconcile) that the trades/equity/summary golden CSVs do not capture.
- Determinism gate (Task 3): no Makefile determinism target exists, so per the plan ("run a margin scenario twice and diff") added a standalone scripts/ double-run for the LIQUIDATION forced-close path (short_carry already covers the carry double-run).

## Deviations from Plan

None - plan executed exactly as written. Task 1 was pre-approved by the orchestrator (owner explicitly approved the accounting-core golden freeze with attribution tiziaco / tiziano.iaco@gmail.com / 2026-06-16); Tasks 2-3 ran autonomously per the plan.

## Issues Encountered
- `make test` aborts in the worktree because the Makefile `include .env` finds no `.env` file (a worktree-environment artifact, not a test failure). Ran the equivalent full suite via `PYTHONPATH="$PWD" poetry run pytest tests` (1146 passed) — the same suite `make test` drives. PYTHONPATH prepend per the worktree-.venv-shadowing convention.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 4 (LIQ-01/02/03, XVAL-01) complete: the single owner-gated accounting-core golden is frozen with full attribution; SMA_MACD byte-exact; the phase gate (oracle / mypy / determinism / full suite) holds.
- DEF-01-C is closed — the explicit WB-capped loss guarantees equity can no longer drift impossibly negative on a forced liquidation.
- Ready for the v1.4 trailing-stop and pair-trading phases (separate subsystems / re-baselines).

---
*Phase: 04-liquidation-cross-validation-re-baseline*
*Completed: 2026-06-16*
