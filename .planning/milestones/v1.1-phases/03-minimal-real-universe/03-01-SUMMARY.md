---
phase: 03-minimal-real-universe
plan: 01
subsystem: universe
tags: [membership, availability, span-model, pure-function, datetime]

# Dependency graph
requires:
  - phase: 02-data-ingestion
    provides: real differing-span datasets (ETH/SOL/AAVE/BTC) that motivate a time-aware availability primitive
provides:
  - "is_active(spans, ticker, asof) — span-model availability query (D-01)"
  - "active_membership(spans, asof) — set of tickers live at T, derived solely from data spans (UNIV-01)"
  - "Span type alias (tuple[datetime, datetime], half-inclusive-both-ends [first,last])"
  - "extended itrader.universe barrel re-exporting both new queries"
affects: [03-02 (feed consumes is_active for span-aware absence observability), 03-03 (integration), v1.3-screener (screen(active_membership(T), ranking))]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure-function-over-injected-shape availability query (mirrors derive_membership + SupportsTickers)"
    - "Availability (query) separated from selection (gate) — Zipline can_trade vs LEAN UniverseSelectionModel split"

key-files:
  created: []
  modified:
    - itrader/universe/membership.py
    - itrader/universe/__init__.py
    - tests/unit/universe/test_membership.py

key-decisions:
  - "is_active/active_membership added ALONGSIDE derive_membership, not replacing it (D-03)"
  - "Span model with inclusive both endpoints — a mid-life gap day inside [first,last] is still active (D-01)"
  - "active_membership returns set[str] (intentional divergence from derive_membership's list — honest about unordered availability)"

patterns-established:
  - "Pure availability primitive: no class, no state, no queue, no feed/store import — over an injected span-map"
  - "Sparse contract: a ticker absent from the span map is never active (returns False)"

requirements-completed: [UNIV-01]

# Metrics
duration: 4min
completed: 2026-06-09
---

# Phase 3 Plan 01: Universe Availability Primitive Summary

**Time-parameterized span-model availability query — `is_active(spans, ticker, T)` and `active_membership(spans, T)` — added pure and stateless beside the unchanged `derive_membership` (UNIV-01, D-01, D-03).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-09
- **Completed:** 2026-06-09
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `is_active(spans, ticker, asof)` — returns True iff `first_bar <= asof <= last_bar` (D-01 inclusive both ends); unknown ticker → False (sparse contract).
- `active_membership(spans, asof)` — the set of tickers live at T, derived solely from data spans, composing into the future `screen(active_membership(T), ranking)` (D-03 selection seam).
- `Span` type alias and extended package barrel re-exporting both queries.
- UNIV-01 unit coverage: inclusive endpoints, mid-life-gap-still-active, day-before/after False, unknown-ticker False, and a 3-span `active_membership` set query at 3 distinct T points — all set-equality, never order-dependent.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add is_active + active_membership pure functions and extend the barrel** - `359d036` (feat) — TDD: failing test written first (RED), then implementation (GREEN)
2. **Task 2: Add UNIV-01 unit cases** - `eabe4c7` (test)

_Note: This is a `tdd="true"` Task 1. The RED test cases were authored in the test file, confirmed failing (ImportError on the not-yet-existing symbols), then GREEN was reached by implementing the functions + barrel. The test-file commit was grouped under Task 2 (its plan-designated deliverable); the implementation + barrel under Task 1._

**Plan metadata:** (final docs commit below)

## Files Created/Modified
- `itrader/universe/membership.py` - Added `Span` alias + `is_active`/`active_membership` pure functions below the unchanged `derive_membership`; appended one sentence to the module docstring noting the availability query was added alongside.
- `itrader/universe/__init__.py` - Extended the barrel import line and `__all__` to re-export `active_membership` and `is_active` (single-quoted, 4-space).
- `tests/unit/universe/test_membership.py` - Added 5 UNIV-01 test functions covering the span model; existing `derive_membership` tests untouched.

## Decisions Made
None new — followed the plan and honored locked CONTEXT decisions D-01 (span model, inclusive both ends), D-03 (add alongside, do not replace `derive_membership`), and the set-vs-list return divergence (Pitfall 4).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## TDD Gate Compliance
Task 1 was `tdd="true"`. RED was confirmed (`ImportError: cannot import name 'active_membership'` before implementation), GREEN reached after implementing the functions and barrel. The `test(...)` (`eabe4c7`) and `feat(...)` (`359d036`) gate commits both exist. No refactor was needed.

## Verification
- `poetry run pytest tests/unit/universe/test_membership.py -x` → 11 passed.
- `poetry run python -c "from itrader.universe import is_active, active_membership, derive_membership"` → exits 0.
- `poetry run mypy itrader/universe/membership.py itrader/universe/__init__.py` → Success: no issues found.
- `derive_membership` body/signature byte-unchanged (D-03); membership.py and test file contain zero tabs (4-space confirmed).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The UNIV-01 primitive is ready for Plan 02 (feed consumes `is_active(self._spans, ticker, T)` for D-04 span-aware absence observability) and Plan 03 (synthetic-fixture integration).
- No blockers. Behavior-preserving: the primitive is not yet wired into the hot loop, so the BTCUSD golden oracle remains byte-identical.

## Self-Check: PASSED
- FOUND: itrader/universe/membership.py (is_active + active_membership present)
- FOUND: itrader/universe/__init__.py (both re-exported)
- FOUND: tests/unit/universe/test_membership.py (UNIV-01 cases)
- FOUND: commit 359d036 (Task 1 feat)
- FOUND: commit eabe4c7 (Task 2 test)

---
*Phase: 03-minimal-real-universe*
*Completed: 2026-06-09*
