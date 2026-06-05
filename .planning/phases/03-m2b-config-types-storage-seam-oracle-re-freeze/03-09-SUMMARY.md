---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 09
subsystem: testing
tags: [golden-master, oracle, decimal, regression-lock, pytest, backtest]

# Dependency graph
requires:
  - phase: 03-01
    provides: M2A-INERTNESS-REF byte-exact baseline (final_equity 53229.685, 134 trades) for the D-17 gate
  - phase: 03-08
    provides: test/ -> tests/ move (oracle + golden now under tests/integration/ + tests/golden/)
  - phase: 02
    provides: M2a Decimal-end engine numbers (CR-03 cash ledger + WR-05 sizing) that the re-freeze blesses
provides:
  - Numerical oracle re-frozen byte-exact at the M2b end-state (Decimal-end values)
  - D-15 transitional tolerance + DEF-02-08-A xfail machinery removed
  - test_oracle_numeric_values now asserts numeric columns check_exact=True (no tolerance)
  - Behavioral identity oracle unchanged and active (D-18)
affects: [phase-04, phase-05, phase-08, golden-master, oracle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-16 byte-exact re-freeze: regenerate golden from scripts/run_backtest.py::main, flip numeric asserts to check_exact=True"
    - "D-17 inertness gate: automated byte-exact diff vs phase-start baseline BEFORE re-freeze, blocking on any divergence"

key-files:
  created:
    - .planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/03-09-SUMMARY.md
  modified:
    - tests/integration/test_backtest_oracle.py
    - tests/golden/trades.csv
    - tests/golden/equity.csv
    - tests/golden/summary.json

key-decisions:
  - "Plan 03-09: numerical oracle re-frozen byte-exact at M2b end-state (final_equity 53229.68512642488, replacing stale M1 float 53229.75); D-15 tolerance + DEF-02-08-A xfail closed; numeric cols check_exact=True; behavioral identity unchanged (D-18). One of PROJECT.md's two sanctioned numeric re-baseline points (after M2)."
  - "Plan 03-09: D-17 inertness gate confirmed byte-exact (behavioral AND numeric) vs M2A-INERTNESS-REF before re-freeze — structural M2b changes proven numerically inert; no time_parser firing shift."

patterns-established:
  - "Pattern E (numeric re-baseline): owner-gated, inertness-checked, byte-exact re-freeze from the deterministic run path"

requirements-completed: [M2-13]

# Metrics
duration: 8min
completed: 2026-06-05
---

# Phase 3 Plan 9: Oracle Re-freeze Summary

**Numerical oracle re-frozen byte-exact at the M2b Decimal end-state (final_equity 53229.68512642488, replacing the stale M1 float 53229.75); D-15 tolerance + DEF-02-08-A xfail removed; numeric columns now asserted check_exact=True with the behavioral identity oracle left untouched (D-18).**

## Performance

- **Duration:** ~8 min (Task 3 only; Tasks 1-2 completed in prior session)
- **Completed:** 2026-06-05
- **Tasks:** 3 (Task 1 inertness gate + Task 2 owner sign-off done in prior session; Task 3 re-freeze this session)
- **Files modified:** 4

## Accomplishments

- Regenerated `tests/golden/{trades,equity}.csv` + `summary.json` from the M2b-end deterministic Decimal run, replacing the stale M1 float oracle (53229.75) with the Decimal-end values (53229.68512642488).
- Removed the DEF-02-08-A `@pytest.mark.xfail`, the `_DEF_02_08_A_XFAIL_REASON` text, and the `_D15_RTOL`/`_D15_ATOL` transitional-tolerance constants.
- Flipped `test_oracle_numeric_values` numeric-column assertions (trades, equity, summary `final_cash`/`final_equity`/`total_realised_pnl`) to `check_exact=True` (no rtol/atol) — both oracles are now exact law.
- Left `test_oracle_behavioral_identity` byte-exact and active, unchanged (D-18).
- Re-confirmed the D-17 inertness gate (byte-exact vs `M2A-INERTNESS-REF`) before regenerating any golden file.

## Task Commits

1. **Task 1: D-17 inertness gate (automated byte-exact diff)** - completed in prior session (verification-only, no tracked-file changes)
2. **Task 2: Owner sign-off (blocking human gate)** - APPROVED by owner
3. **Task 3: Re-freeze numerical oracle byte-exact (D-16)** - `b146af4` (test)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified

- `tests/integration/test_backtest_oracle.py` - Removed xfail + D-15 tolerance machinery; `test_oracle_numeric_values` now asserts `check_exact=True`; behavioral identity test unchanged.
- `tests/golden/trades.csv` - Re-frozen from M2b-end Decimal run (134 trades, exact Decimal magnitudes).
- `tests/golden/equity.csv` - Re-frozen from M2b-end Decimal run (3076 equity points).
- `tests/golden/summary.json` - Re-frozen: `final_cash`/`final_equity` 53229.68512642488, `total_realised_pnl` 43229.68512642489, `trade_count` 134.

## Decisions Made

- **Re-freeze blessed the M2a Decimal-end number, not a new M2b number.** The D-17 gate proved the M2b structural changes (config collapse, type relocation, storage seam, time_parser epoch alignment) are numerically inert vs the phase-start M2a baseline, so the re-freeze value is the already-characterized Decimal-end number. This is one of PROJECT.md's two sanctioned numeric re-baseline points.
- **Behavioral identity stays the law (D-18).** `test_oracle_behavioral_identity` was not touched — trade count, entry/exit/side/pair identity, and the equity timestamp grid remain byte-exact and active.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The D-17 gate passed byte-exact on re-verification, golden regeneration was a direct copy of the deterministic output, and all three gates (oracle test, `make test`, `make typecheck`) passed first try.

## Verification

- D-17 inertness gate: `byte-exact match` (exit 0) vs `M2A-INERTNESS-REF`.
- `poetry run pytest tests/integration/test_backtest_oracle.py` — 2 passed (both behavioral identity and numeric values exact).
- Acceptance grep `xfail|_D15_RTOL|_D15_ATOL|DEF_02_08_A` returns only CLOSED-state comment references, no live code.
- `make test` — 346 passed.
- `make typecheck` — `Success: no issues found in 148 source files`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 (M2b) is the last phase plan; the numerical oracle is now re-frozen byte-exact and regression-locked with no tolerance.
- The exact Decimal oracle is the new golden baseline for Phases 4-5 (behavior/value-preserving) and the final cross-validated re-freeze at Phase 8.
- No blockers.

## Self-Check: PASSED

- All modified files present: `tests/integration/test_backtest_oracle.py`, `tests/golden/{trades,equity}.csv`, `tests/golden/summary.json`, `03-09-SUMMARY.md`.
- Task 3 commit `b146af4` present in git log.

---
*Phase: 03-m2b-config-types-storage-seam-oracle-re-freeze*
*Completed: 2026-06-05*
