---
phase: 01-account-abstraction-portfolio-handler-refactor
plan: 04
subsystem: infra
tags: [cleanup, dead-code, trading-interface, float-money, fastapi, live-path]

# Dependency graph
requires: []
provides:
  - "TradingInterface deleted (D-08, LX-14) — dead pre-FastAPI bridge removed, eliminating a quantity: float live-path float-money leak"
  - "D-09 surviving-command-surface PRINCIPLE recorded: FastAPI calls a thin explicit engine command surface and never reaches into LiveTradingSystem internals; the concrete method set is deferred to Phase 4 (scopes FL-13)"
affects: [02-okx-connector, 04-paper-path]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Engine command surface principle (D-09): external/web callers go through a thin typed command surface, never into LiveTradingSystem internals"

key-files:
  created: []
  modified:
    - itrader/trading_system/__init__.py
    - tests/unit/order/test_admission_rules.py
    - tests/golden/FINAL-ORACLE.md

key-decisions:
  - "D-09: only the PRINCIPLE for the surviving engine command surface is locked this phase (FastAPI -> thin typed command surface, never into LiveTradingSystem internals); the concrete command method set is deferred to Phase 4 when the live path first has a real consumer (scopes FL-13)"
  - "TradingInterface confirmed genuinely dead before deletion (grep: referenced only by the barrel export + a test docstring + one oracle-doc prose mention; never instantiated, never in LiveTradingSystem composition)"

patterns-established:
  - "Deleting a dead float-leaking middle layer strengthens the no-float-money / mypy --strict gate rather than weakening it"

requirements-completed: [ACCT-05]

# Metrics
duration: 2min
completed: 2026-06-30
---

# Phase 01 Plan 04: Delete TradingInterface (LX-14) Summary

**TradingInterface deleted (D-08, LX-14) — a dead pre-FastAPI bridge carrying a `quantity: float` live-path float-money leak — barrel cleaned and dangling docstring/oracle references reworded; the D-09 surviving-command-surface principle recorded with the method set deferred to Phase 4.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-30T20:34:46Z
- **Completed:** 2026-06-30T20:35:52Z
- **Tasks:** 2
- **Files modified:** 3 (1 deleted, 2 edited)

## Accomplishments
- Deleted `itrader/trading_system/trading_interface.py` (D-08) — confirmed dead (not instantiated, not in `LiveTradingSystem` composition); removing it eliminates the `quantity: float` live-path float-money leak, HELPING the `mypy --strict` / no-float-money gate (ACCT-05)
- Cleaned the `trading_system` barrel: removed the `from .trading_interface import TradingInterface` import line and the `'TradingInterface'` `__all__` entry; `import itrader.trading_system` exits 0
- Reworded the dangling `TradingInterface` references (test docstring + oracle DoD prose) so `grep -rn "TradingInterface" itrader tests` returns nothing; no test logic changed (41 order-admission tests green)
- Recorded the D-09 principle (FastAPI -> thin typed engine command surface, never into `LiveTradingSystem` internals; concrete method set deferred to Phase 4 / FL-13)

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete TradingInterface + remove barrel export** - `eda9d9c` (refactor)
2. **Task 2: Fix the test docstring reference + verify suite collects** - `a0c488a` (docs)

## Files Created/Modified
- `itrader/trading_system/trading_interface.py` - DELETED (dead pre-FastAPI bridge with the float-money leak)
- `itrader/trading_system/__init__.py` - removed the TradingInterface import + `__all__` entry
- `tests/unit/order/test_admission_rules.py` - reworded the `test_long_short_direction_passes_the_gate` docstring ("from TradingInterface" -> "from a live/web entry path"); docstring-only, no assertion change
- `tests/golden/FINAL-ORACLE.md` - reworded the DoD criterion-3 note ("TradingInterface live leaks OUT" -> "Live-path float leaks OUT") to drop the now-deleted symbol name

## Decisions Made
- **D-09 (recorded):** Only the surviving-command-surface PRINCIPLE is locked this phase — FastAPI calls a thin explicit engine command surface and never reaches into `LiveTradingSystem` internals. The concrete command method set is deferred to Phase 4, when the live path first has a real consumer (this scopes FL-13). No speculative command surface was designed for a consumer that does not yet exist.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded an out-of-scope oracle-doc TradingInterface reference**
- **Found during:** Task 2 (fix the test docstring reference)
- **Issue:** The plan's `<interfaces>` enumerated three reference sites (the file, the barrel, the `test_admission_rules.py` docstring), but a fourth `TradingInterface` mention existed in `tests/golden/FINAL-ORACLE.md:110` (DoD criterion-3 prose). The plan's final `<verification>` block requires `grep -rn "TradingInterface" itrader tests` to return nothing, so that residual reference would have failed the verification gate.
- **Fix:** Reworded the prose note from "TradingInterface live leaks OUT (D-09)" to "Live-path float leaks OUT (D-09)" — descriptive prose only, no golden data (`trades.csv`/`equity.csv`/`summary.json`) touched, oracle numbers unaffected.
- **Files modified:** tests/golden/FINAL-ORACLE.md
- **Verification:** `grep -rn "TradingInterface" itrader tests` now returns nothing
- **Committed in:** a0c488a (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to pass the plan's own `<verification>` grep gate. No scope creep — a single prose-only reword of a doc that the plan's interface enumeration missed.

## Issues Encountered
- `git add` of the deleted file path failed (`pathspec did not match`) because `git rm` had already staged the deletion — committed the staged deletion + the barrel edit directly. No impact.

## Next Phase Readiness
- The float-leaking dead bridge is gone; the no-float-money gate is strengthened, not weakened.
- The D-09 principle is on record; Phase 4 owns designing the concrete engine command surface (FL-13) once the live path has a real consumer.
- No blockers.

## Self-Check: PASSED

- CONFIRMED-DELETED: `itrader/trading_system/trading_interface.py`
- FOUND commit: `eda9d9c` (Task 1)
- FOUND commit: `a0c488a` (Task 2)
- FOUND: `01-04-SUMMARY.md`

---
*Phase: 01-account-abstraction-portfolio-handler-refactor*
*Completed: 2026-06-30*
