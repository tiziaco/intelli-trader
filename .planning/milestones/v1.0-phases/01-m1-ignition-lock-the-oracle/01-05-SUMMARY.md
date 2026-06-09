---
phase: 01-m1-ignition-lock-the-oracle
plan: 05
subsystem: testing
tags: [golden-master, pytest, integration, backtest, oracle, regression-lock]

# Dependency graph
requires:
  - phase: 01-04
    provides: scripts/run_backtest.py reproducible oracle generator + ignition wirings (output/{trades,equity}.csv + summary.json)
provides:
  - "Committed behavioral+numerical oracle at test/golden/{trades.csv,equity.csv,summary.json} (134 trades, final equity $53,229.75, +$43,229.70 realised PnL)"
  - "Run-path integration test diffing a fresh full 2018->2026 run against the frozen oracle (exact, no float tolerance, D-13)"
  - "Phase 01 complete: the M1 behavioral oracle is law for M2-M4"
affects: [02, 03, m2, m3, m4, m5]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Golden-master regression lock: freeze blessed output/ into committed test/golden/, diff fresh runs via pandas frame-equal with check_exact=True (no tolerance)"
    - "First-oracle human-blessing gate before freezing (blocking-human checkpoint), since there is no prior baseline to diff against"

key-files:
  created:
    - test/golden/trades.csv
    - test/golden/equity.csv
    - test/golden/summary.json
  modified:
    - .planning/phases/01-m1-ignition-lock-the-oracle/deferred-items.md

key-decisions:
  - "D-11: blessed oracle committed to test/golden/ (output/ stays gitignored)"
  - "D-13: behavioral exact + numerical exact assertion, no float tolerance"
  - "DEF-01-C: no margin/liquidation model — un-liquidated short liability drives total_equity negative — BLESSED into the M1 oracle as current-behavior-to-preserve, deferred to M5"

patterns-established:
  - "Golden-master freeze + exact frame-equal regression lock (check_exact=True, check_like=True)"
  - "Deterministic-only serialized columns (D-12) keep the oracle bit-reproducible across runs"

requirements-completed: [M1-08, M1-10]

# Metrics
duration: 18min
completed: 2026-06-04
---

# Phase 01 Plan 05: Freeze + Regression-Lock the Blessed Oracle Summary

**Human-blessed BTCUSD SMA_MACD oracle (134 trades, final equity $53,229.75) frozen into committed test/golden/ and regression-locked by an exact, tolerance-free run-path integration test — Phase 01 complete.**

## Performance

- **Duration:** ~18 min (continuation executor)
- **Completed:** 2026-06-04
- **Tasks:** 3 (Task 1 completed by prior executor; Tasks 2-3 + DEF-01-C completed here)
- **Files modified:** 4 (3 golden files created, 1 deferred-items.md appended)

## Accomplishments
- Logged DEF-01-C: the no-margin/liquidation defect (un-liquidated short liability sends total_equity to a min of −$33,748 at 2023-11-10 while cash stays ≥0) was BLESSED INTO the M1 oracle by the human as current-behavior-to-preserve, deferred to M5.
- Froze the blessed `output/{trades,equity}.csv + summary.json` into committed `test/golden/` (M1-08). Confirmed NOT gitignored (`git check-ignore` exit 1) and 134 data rows.
- Greened the run-path integration test: a fresh full 2018→2026 run exact-matches the frozen oracle with NO float tolerance (D-13) — the deterministic, pinned-float_format run reproduced the oracle byte-for-byte with zero test-side edits.
- Confirmed the full suite is green (276 passed = 274 legacy + smoke + integration) and all 8 declared markers each select ≥1 test (M1-09).

## Task Commits

1. **DEF-01-C tracking** - `87f8135` (docs)
2. **Task 2: Freeze blessed oracle into test/golden/ (M1-08)** - `c2437c6` (feat)
3. **Task 3: Green integration test + confirm 8 markers (M1-10)** - `93a5d2c` (test, empty — no test-side edits required, deterministic run reproduced oracle as-is)

_Task 1 (run-path integration test) was committed by the prior executor at `1e336d9`._

## Files Created/Modified
- `test/golden/trades.csv` - Frozen behavioral+numerical trade-log oracle (134 round-trips, deterministic columns only)
- `test/golden/equity.csv` - Frozen equity-curve oracle (3076 snapshots)
- `test/golden/summary.json` - Frozen final cash/equity + trade count + realised PnL
- `.planning/phases/01-m1-ignition-lock-the-oracle/deferred-items.md` - Appended DEF-01-C

## Decisions Made
- **DEF-01-C accepted into the oracle (not fixed).** The negative-equity behavior from un-liquidated shorts is a genuine missing-model defect, but M1 is a golden-master capture milestone, not a correctness milestone. The human explicitly blessed current behavior; M2–M4 lock against it and M5 (the only milestone allowed to change results, cross-validated) owns the fix and re-blessing.
- **Task 3 committed empty.** The deterministic run with pinned `float_format="%.10f"` reproduced the frozen oracle exactly with no source/test edits needed; the empty commit preserves the atomic per-task history and records the green-gate verification.

## Deviations from Plan

None — plan executed exactly as written. No float tolerance was introduced (`grep -E "atol|rtol|approx"` on the test returns nothing, D-13 preserved). `test/test_integration/__init__.py` was intentionally NOT created (documented Rule-3 deviation by the prior executor; no sibling test dir uses one).

## Issues Encountered
None. The integration test, RED-until-golden in Task 1, went green immediately once `test/golden/` was committed — confirming the run path is bit-reproducible.

## User Setup Required
None - no external service configuration required.

## Verification (acceptance criteria)
- `poetry run pytest test/test_integration -m "integration" -q` → 1 passed (fresh full run exact-matches test/golden/ — M1-08)
- `poetry run pytest test/ -q` → 276 passed (274 legacy + smoke + integration — M1-10)
- 8 markers each select ≥1 test: portfolio 127, events 17, orders 64, execution 63, strategy 3, unit 1, integration 1, slow 1 (M1-09)
- `git check-ignore test/golden/trades.csv` → exit 1 (NOT ignored); 134 data rows
- No float tolerance in the integration test (D-13)

## Next Phase Readiness
- The M1 behavioral + numerical oracle is committed and regression-locked. It is now LAW for M2–M4 (behavior-preserving milestones).
- DEF-01-C is the one known accepted defect carried into the oracle; M5 owns its fix + re-blessing (numerical oracle re-baselines after M2 and after M5).
- Phase 01 (m1-ignition-lock-the-oracle) is complete — all 5 plans done.

## Self-Check: PASSED

All created files exist (test/golden/{trades,equity}.csv, summary.json; integration test; SUMMARY) and all task commits are present in git (`87f8135`, `c2437c6`, `93a5d2c`, plus prior `1e336d9`).

---
*Phase: 01-m1-ignition-lock-the-oracle*
*Completed: 2026-06-04*
