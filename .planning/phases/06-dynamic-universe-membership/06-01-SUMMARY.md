---
phase: 06-dynamic-universe-membership
plan: 01
subsystem: universe
tags: [msgspec-event, universe-membership, event-dispatch, frozen-dataclass]

# Dependency graph
requires:
  - phase: 01-account-abstraction
    provides: "Instrument value object + Universe read-model facade (members-by-identity, instrument map)"
  - phase: 03-live-bar-feed
    provides: "feed binds Universe.members by identity (Pitfall 4 contract this plan must preserve)"
provides:
  - "UniverseUpdateEvent (frozen Event subclass, tuple added/removed payload) + EventType.UNIVERSE_UPDATE discriminator"
  - "explicit-empty _routes[UNIVERSE_UPDATE] entry — emitted event is a safe no-op, never NotImplementedError"
  - "Universe.apply(desired, instruments) -> UniverseDelta with in-place _members slice-assign (identity preserved)"
  - "empty-delta oracle-dark fast path (no mutation when desired == current)"
  - "added-symbol Instrument resolution with _DEFAULT_* ladder fallback"
  - "leaving-set surface: mark_leaving / leaving_symbols (copy) / clear_leaving"
affects: [06-02, 06-03, 06-04, 06-05, dynamic-universe-membership, poll-handler, remove-policy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "New-event three-step flow: enum member + frozen struct + explicit route in one change (Pitfall 5)"
    - "In-place list mutation via slice-assign to preserve by-identity binds (Pitfall 4)"
    - "Connector-free membership owner: caller passes resolved instruments into apply(), Universe does no I/O (D-03)"

key-files:
  created:
    - tests/unit/events/test_universe_update_event.py
    - tests/unit/universe/test_universe_apply.py
  modified:
    - itrader/core/enums/event.py
    - itrader/events_handler/events/market.py
    - itrader/events_handler/events/__init__.py
    - itrader/events_handler/full_event_handler.py
    - itrader/universe/universe.py

key-decisions:
  - "UniverseUpdateEvent kept DISTINCT from ScreenerEvent — dispose notification vs propose seam (D-04)"
  - "Universe stays connector-free (D-03): poll handler resolves precision from venue markets, passes instruments into apply()"
  - "added-symbol without a resolved Instrument falls back to the _DEFAULT_* ladder (2dp/8dp) — never KeyErrors later"
  - "UNIV-01 left Pending — this plan is the foundation seam only (no consumers); the requirement completes across plans 02-05"

patterns-established:
  - "Empty-delta fast path is the oracle-dark guarantee (single-symbol SMA_MACD yields desired == current)"
  - "leaving_symbols() returns a defensive copy so admission-gate callers cannot corrupt internal state"

requirements-completed: []  # UNIV-01 is a multi-plan requirement; foundation only — not yet satisfiable

# Metrics
duration: 22min
completed: 2026-07-06
---

# Phase 6 Plan 01: Dynamic-Universe Foundation Seam Summary

**UniverseUpdateEvent + EventType.UNIVERSE_UPDATE discriminator + explicit-empty route, and Universe.apply()->UniverseDelta with in-place membership mutation (identity-preserved) plus a leaving-set surface — the backtest-inert foundation for dynamic membership.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-07-06T12:01Z
- **Completed:** 2026-07-06T12:05Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments
- New `UniverseUpdateEvent` frozen `Event` subclass with `tuple[str, ...]` `added`/`removed` payload, pinned to a new `EventType.UNIVERSE_UPDATE` discriminator (case-insensitive parse via existing `_missing_`), exported from the events barrel.
- Explicit-empty `_routes[EventType.UNIVERSE_UPDATE]` entry (three-step flow, Pitfall 5) so an emitted event is a safe no-op on any path — never a `NotImplementedError`. Dispatch-registry coverage test still green.
- `Universe.apply(desired, instruments) -> UniverseDelta` diffs desired vs current, mutates `_members` IN PLACE via `self._members[:]` slice-assign (feed's by-identity bind preserved, Pitfall 4), with an empty-delta oracle-dark fast path that mutates nothing.
- Added-symbol `Instrument` resolution: uses the passed-in map (venue-correct precision) or falls back to the `instruments.py` `_DEFAULT_*` ladder, so a later `.instrument(sym)` never `KeyError`s.
- Leaving-set surface (`mark_leaving` / `leaving_symbols` (copy) / `clear_leaving`) backing the plan-04 remove-policy admission gate.

## Task Commits

Each task was committed atomically (TDD RED -> GREEN):

1. **Task 1: UniverseUpdateEvent + discriminator + barrel + empty route**
   - `1eefe56f` (test — RED)
   - `872a2a9d` (feat — GREEN)
2. **Task 2: Universe.apply/UniverseDelta + in-place mutation + leaving-set**
   - `eebc1dfe` (test — RED)
   - `f9ca6256` (feat — GREEN)

## Files Created/Modified
- `tests/unit/events/test_universe_update_event.py` - 7 behaviors: construct/frozen/tuple, case-insensitive parse, barrel import, explicit-empty-route dispatch-no-crash
- `tests/unit/universe/test_universe_apply.py` - 10 behaviors: fast path, add/remove/both, list identity, default-ladder fallback, leaving-set
- `itrader/core/enums/event.py` - `UNIVERSE_UPDATE` member after `SCREENER`
- `itrader/events_handler/events/market.py` - `UniverseUpdateEvent` struct after `ScreenerEvent`
- `itrader/events_handler/events/__init__.py` - barrel import + `__all__`
- `itrader/events_handler/full_event_handler.py` - explicit-empty `UNIVERSE_UPDATE` route (TABS preserved)
- `itrader/universe/universe.py` - `UniverseDelta` dataclass, `apply()`, `_default_instrument()`, leaving-set methods

## Decisions Made
- Followed the plan as specified. `UniverseUpdateEvent` kept a separate type from `ScreenerEvent` (D-04); `Universe` kept connector-free (D-03) with instruments passed into `apply()`.
- `UNIV-01` intentionally NOT marked complete: this plan ships the foundation event + mutation contract with NO consumers (route is deliberately empty). The requirement — "supports mid-run add/remove of symbols" — needs the poll handler and consumers landing in plans 02-05.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. `_DEFAULT_MAINTENANCE_MARGIN_RATE` / `_DEFAULT_MAX_LEVERAGE` were also imported from `instruments.py` (alongside the price/quantity scales named in the plan) because `Instrument` requires those two fields; this is within the plan's "default-ladder Instrument" instruction.

## Known Stubs

None. The empty `_routes[UNIVERSE_UPDATE]` entry is an intentional, documented no-op (live consumers wired live-only in plan 05), not a stub blocking this plan's goal.

## Milestone Gate

- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` 3 passed (134 / 46189.87730727451) — the seam is inert on the backtest hot path (empty route, `apply` unused on backtest).
- **mypy --strict:** clean on `itrader/universe/universe.py` and `itrader/events_handler/events/market.py`.
- **Unit tests:** 43 passed across new + existing universe/event suites; dispatch-registry coverage still green.

## Next Phase Readiness
- Settled event + mutation contract ready for plans 02 (poll seam / selection model), 03/04 (poll handler, remove policy), 05 (live wiring).
- No blockers. The leaving-set surface is present but unread until the plan-04 admission gate consumes it.

## Self-Check: PASSED

All created files present on disk; all four task commits present in git history.

---
*Phase: 06-dynamic-universe-membership*
*Completed: 2026-07-06*
