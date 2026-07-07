---
phase: 07-live-dynamic-universe-hardening
plan: 01
subsystem: events
tags: [msgspec, event-driven, enum, universe, live-trading]

# Dependency graph
requires:
  - phase: 06-live-dynamic-universe (v1.7)
    provides: UniverseUpdateEvent + explicit-empty _routes 3-step-flow precedent
  - phase: 04-event-dispatch-core (M3)
    provides: frozen msgspec Event base + data-driven _routes dispatch
provides:
  - Readiness tri-state enum (PENDING/READY/FAILED) for the WR-02 per-symbol readiness gate
  - Four new EventType members (UNIVERSE_POLL, STRATEGY_COMMAND, BARS_LOADED, BARS_LOAD_FAILED)
  - Four frozen event structs (BarsLoaded, BarsLoadFailed, UniversePollEvent, StrategyCommandEvent)
  - StrategyCommandEvent.add_ticker / remove_ticker construct-complete factory classmethods
  - Explicit-empty backtest _routes entries closing the 3-step flow (backtest-inert by construction)
affects: [07-02, 07-03, 07-04, 07-05, 07-06, 07-07, live-warmup, per-symbol-readiness-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-step event flow (struct + EventType member + explicit-empty _routes entry) reused verbatim"
    - "Construct-complete factory classmethods (FillEvent.new_fill convention) for StrategyCommandEvent"

key-files:
  created:
    - itrader/core/enums/universe.py
    - itrader/events_handler/events/universe.py
    - tests/unit/events/test_universe_events.py
  modified:
    - itrader/core/enums/event.py
    - itrader/core/enums/__init__.py
    - itrader/events_handler/events/__init__.py
    - itrader/events_handler/full_event_handler.py

key-decisions:
  - "Readiness carries NO _missing_ parser (D-02) — set engine-side only, never enters from an external string"
  - "BarsLoaded reuses core.bar.Bar as tuple[Bar, ...] — never a pandas frame on the queue (M5-02)"
  - "BarsLoadFailed.reason contract mandates scrubbed exception TYPE / short message (T-05-27); emit-site scrub is Plan 07-03+"
  - "StrategyCommandEvent uses factory classmethods, no wrapper method on LiveTradingSystem (D-09)"
  - "All four _routes entries explicit-empty so backtest _dispatch stays inert (T-07-01-DROP mitigated + unit-asserted)"

patterns-established:
  - "Universe control-plane events live in events/universe.py mirroring the UniverseUpdateEvent shape"

requirements-completed: [WR-02, WR-06, OP-SEAM]

# Metrics
duration: 3min
completed: 2026-07-06
---

# Phase 7 Plan 01: New Type Vocabulary (Contracts-First) Summary

**Readiness tri-state enum + four new EventType members + four frozen msgspec event structs (BarsLoaded/BarsLoadFailed/UniversePollEvent/StrategyCommandEvent with add/remove-ticker factories) + explicit-empty backtest _routes — additive-only, backtest-inert by construction.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-07-06T18:01:47Z
- **Completed:** 2026-07-06T18:05:01Z
- **Tasks:** 3
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- `Readiness(Enum)` (PENDING/READY/FAILED) shipped in a new `core/enums/universe.py`, barrel-re-exported — the WR-02 per-symbol readiness-gate vocabulary for downstream plans.
- Four `EventType` members added after `UNIVERSE_UPDATE`, all case-insensitive-parsing via the existing `_missing_`.
- Four frozen msgspec `Event` structs in a new `events/universe.py`, barrel-re-exported, all carrying business `time` + auto UUIDv7 `event_id`; `StrategyCommandEvent` gets construct-complete `add_ticker`/`remove_ticker` factory classmethods.
- The backtest `_routes` literal carries explicit-empty entries for all four new types, so `_dispatch` never raises `NotImplementedError` on one (3-step flow closed, T-07-01-DROP mitigated).
- New `test_universe_events.py` (17 tests) locks struct/factory/frozen semantics + route-presence + inert-dispatch as data.

## Task Commits

Each task was committed atomically:

1. **Task 1: Readiness enum + four EventType members** - `e8e3719e` (feat)
2. **Task 2: Four event structs + factory classmethods + barrel re-export** - `2151f6d6` (feat)
3. **Task 3: Explicit-empty _routes entries + tests** - `8930fb2e` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `itrader/core/enums/universe.py` (created) - `Readiness` tri-state enum (D-02)
- `itrader/core/enums/event.py` (modified) - four new `EventType` members
- `itrader/core/enums/__init__.py` (modified) - `Readiness` barrel import + `__all__`
- `itrader/events_handler/events/universe.py` (created) - four frozen event structs + factories
- `itrader/events_handler/events/__init__.py` (modified) - four-event barrel import + `__all__`
- `itrader/events_handler/full_event_handler.py` (modified, TABS) - four explicit-empty `_routes` entries
- `tests/unit/events/test_universe_events.py` (created) - 17 tests: structs/factories/frozen + route inertness

## Decisions Made
- Followed the plan exactly. Notable pins: `Readiness` needs no `_missing_` (engine-set only, D-02); `BarsLoaded.bars` is `tuple[Bar, ...]` reusing `core.bar.Bar` (M5-02); `BarsLoadFailed.reason` scrub discipline documented in the docstring (emit-site enforcement is Plan 07-03+); `StrategyCommandEvent` factories over any wrapper method (D-09).
- Matched per-file indentation: 4-space in `core/enums/` and `events/`, TABS in `full_event_handler.py`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The full new type vocabulary is in place; Plans 07-02..07-07 implement against these contracts (structs, enum, and inert routes) without re-deriving them.
- Backtest-inert by construction: no consumers wired, all four routes explicit-empty; the oracle hot path is untouched (no import cost added on the backtest path — new modules are only reached via the events barrel, already imported).
- Verification green: `tests/unit/events` 109 passed, `tests/unit/universe` 54 passed, `mypy --strict` clean on the three targeted files.

## Self-Check: PASSED

- FOUND: itrader/core/enums/universe.py
- FOUND: itrader/events_handler/events/universe.py
- FOUND: tests/unit/events/test_universe_events.py
- FOUND commit: e8e3719e
- FOUND commit: 2151f6d6
- FOUND commit: 8930fb2e

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*
