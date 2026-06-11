---
phase: 02-locked-decision-conformance
plan: 03
subsystem: core
tags: [uuid, uuidv7, idgen, newtype, correlation-id, mypy, conformance]

# Dependency graph
requires:
  - phase: 04-event-dispatch-core
    provides: "ErrorEvent / PortfolioErrorEvent frozen event hierarchy with the correlation_id field"
provides:
  - "CorrelationId NewType — 10th alias in core/ids.py, single UUIDv7 scheme conformance"
  - "IDGenerator.generate_correlation_id() returning a stdlib uuid.UUID"
  - "ErrorEvent.correlation_id retyped str | None -> CorrelationId | None"
  - "PortfolioHandler._generate_correlation_id mints CorrelationId(idgen.generate_correlation_id()); uuid4() retired"
affects: [type-modeling, naming-encapsulation, engine-surface-completion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "NewType-wrap-at-mint: CorrelationId(idgen.generate_correlation_id()) mirrors OrderId(idgen.generate_order_id())"

key-files:
  created: []
  modified:
    - itrader/core/ids.py
    - itrader/outils/id_generator.py
    - itrader/events_handler/events/error.py
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/portfolio/test_portfolio_handler.py

key-decisions:
  - "Per D-01 use the idgen UUIDv7 scheme (NOT a deterministic counter); correlation IDs are oracle-dark so per-run UUIDv7 nondeterminism does not break byte-exactness."
  - "Per D-02 type the correlation id as uuid.UUID via a CorrelationId NewType, mint at the call site, drop the ph_ string-format prefix."
  - "Retype _operation_context generator -> CorrelationId (Rule 3 blocking-type-error fix) to propagate the new type through the three with-as call sites."

patterns-established:
  - "Correlation id minting follows the established 9-sibling NewType-wrap-at-mint shape (OrderId(idgen.generate_order_id()))."

requirements-completed: [DEC-03]

# Metrics
duration: 12min
completed: 2026-06-11
---

# Phase 02 Plan 03: Locked-Decision Conformance (DEC-03) Summary

**Retired the lone `uuid.uuid4()` second ID scheme — correlation IDs now use the single UUIDv7 `idgen` scheme via a new `CorrelationId` NewType, clearing the FINAL-ORACLE.md:111 DoD grep.**

## Performance

- **Duration:** ~12 min
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Added `CorrelationId = NewType("CorrelationId", uuid.UUID)` as the 10th `core/ids.py` alias (+ `__all__`, docstring count Nine→Ten).
- Added `IDGenerator.generate_correlation_id(self) -> uuid.UUID` mirroring its nine siblings.
- `PortfolioHandler._generate_correlation_id` now returns `CorrelationId(idgen.generate_correlation_id())`; the `ph_` prefix and `uuid.uuid4().hex[:12]` format are gone; the now-dead `import uuid` was removed.
- Retyped `ErrorEvent.correlation_id` (`str | None` → `CorrelationId | None`, inherited by `PortfolioErrorEvent`) + docstring; retyped `_publish_error_event` param and `_operation_context` generator for consistency.
- Updated `test_correlation_id_generation` to assert `isinstance(id, uuid.UUID)` + uniqueness instead of the `ph_` prefix.
- DEC-03 closed: `grep -rn 'uuid4' itrader/` returns no hits — single UUIDv7 scheme restored.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CorrelationId NewType + IDGenerator.generate_correlation_id** - `04269dd` (feat)
2. **Task 2: Mint correlation id from idgen + retype event field + remove dead import** - `eacc0a0` (feat)
3. **Task 3: Update test_correlation_id_generation + roll-up verification** - `57ad3df` (test)

## Files Created/Modified
- `itrader/core/ids.py` - Added CorrelationId NewType (10th alias) + `__all__` entry; docstring Nine→Ten.
- `itrader/outils/id_generator.py` - Added `generate_correlation_id()` returning a UUIDv7 `uuid.UUID` (tab-indented, matched file).
- `itrader/events_handler/events/error.py` - Retyped `ErrorEvent.correlation_id` → `CorrelationId | None` + docstring; imported `CorrelationId`.
- `itrader/portfolio_handler/portfolio_handler.py` - `_generate_correlation_id` mints from idgen; retyped `_publish_error_event` param + `_operation_context` generator; removed dead `import uuid`.
- `tests/unit/portfolio/test_portfolio_handler.py` - Asserts `uuid.UUID` + uniqueness (no `ph_` prefix).

## Decisions Made
- Followed D-01 (idgen UUIDv7, not a deterministic counter) and D-02 (CorrelationId NewType, mint-at-call-site, drop `ph_`) exactly as the plan specified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Retyped `_operation_context` generator return type**
- **Found during:** Task 2 (event-field + handler retype)
- **Issue:** After retyping `_generate_correlation_id -> CorrelationId` and the `_publish_error_event` param to `CorrelationId`, `mypy --strict` reported 4 errors: `_operation_context` was still annotated `Generator[str, None, None]`, so its `yield` and the three `with ... as correlation_id` call sites (lines 164, 204, 339) passed `CorrelationId` where `str` was expected.
- **Fix:** Retyped `_operation_context(self, ...) -> Generator[CorrelationId, None, None]`, which propagates the correct type to all call sites and resolves all 4 errors at once. This is the same module the plan already scoped (the interfaces block named `_publish_error_event` for retype); the generator is the upstream source of the value.
- **Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
- **Verification:** `poetry run mypy itrader` → Success: no issues found in 161 source files.
- **Committed in:** `eacc0a0` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking type error).
**Impact on plan:** The fix was necessary to keep `mypy --strict` clean and stayed within the file the plan already scoped. No scope creep, no behavior change (NewType is identity at runtime).

## Issues Encountered
None beyond the auto-fixed blocking type error above.

## Verification Results
- `grep -rn 'uuid4' itrader/` → no hits (DEC-03 single-ID-scheme DoD grep clean; FINAL-ORACLE.md:111 cleared).
- `poetry run pytest tests/unit/portfolio/test_portfolio_handler.py -k correlation_id_generation -v` → 1 passed.
- `poetry run pytest tests/integration` → 12 passed; golden oracle byte-exact (134 trades / final_equity 46189.87730727451).
- Determinism double-run: the oracle exact-diff test passed on two consecutive runs (compared trades/equity/summary byte-identical — correlation IDs are oracle-dark, never in those fixtures).
- `poetry run pytest tests/e2e -m e2e` → 58 passed (no leaf re-baselined).
- `poetry run pytest` (full suite) → 811 passed.
- `poetry run mypy itrader` → Success: no issues found in 161 source files.

## Indentation Compliance
- `core/ids.py`, `error.py`, `test_portfolio_handler.py`, and the touched region of `portfolio_handler.py` are 4-space — edits matched 4 spaces.
- `id_generator.py` uses tabs (despite living under `outils/`) — the added `generate_correlation_id` method matched tab indentation. No mixed-indentation diff in any file.

## Note on Pre-existing Working-Tree Changes
At execution start the working tree already contained uncommitted modifications to `itrader/execution_handler/exchanges/simulated.py` and `itrader/order_handler/order_handler.py` (from a sibling Phase 2 plan). These files are NOT in this plan's scope and were left untouched — only this plan's 5 files were staged and committed.

## Next Phase Readiness
- DEC-03 complete; the single UUIDv7 ID scheme is restored across `itrader/`.
- `CorrelationId` is available for downstream typed correlation-id usage.
- No blockers.

## Self-Check: PASSED

- `02-03-SUMMARY.md` exists.
- Commits verified present: `04269dd`, `eacc0a0`, `57ad3df`, `b1720a3`.

---
*Phase: 02-locked-decision-conformance*
*Completed: 2026-06-11*
