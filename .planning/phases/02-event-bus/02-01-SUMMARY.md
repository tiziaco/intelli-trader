---
phase: 02-event-bus
plan: 01
subsystem: infra
tags: [event-bus, queue, priority-queue, protocol, msgspec, enum, itertools]

# Dependency graph
requires:
  - phase: 01
    provides: "EventType string-enum + msgspec.Struct Event base (frozen, non-orderable)"
provides:
  - "EventBus runtime_checkable Protocol (put/get/get_nowait/qsize/empty/depth_by_tier) in itrader/events_handler/bus.py"
  - "FifoEventBus — thin queue.Queue wrapper (byte-exact backtest buffer, D-07)"
  - "PriorityEventBus — queue.PriorityQueue keyed (tier, seq, event); CONTROL preempts BUSINESS, strict within-tier FIFO"
  - "EventTier IntEnum (CONTROL=0, BUSINESS=1) + _CONTROL_EVENT_TYPES frozenset + _tier() mapper"
  - "Three new CONTROL EventType members: STREAM_STATE, CONNECTOR_FATAL, CONFIG_UPDATE"
affects: [02-02, 02-03, compose-seam, engine-context, priority-plane-P6-P7]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Protocol read-model seam reused as transport interface (EventBus mirrors PortfolioReadModel shape)"
    - "PriorityQueue tuple keyed by one per-instance itertools.count() seq so the heap never dereferences the non-orderable Event"
    - "Bus assigns tier from event.type via _CONTROL_EVENT_TYPES — handlers stay tier-unaware"
    - "Import-inertness discipline: TYPE_CHECKING-only Event import keeps pandas off the substrate"

key-files:
  created:
    - itrader/events_handler/bus.py
    - tests/unit/events/test_event_bus.py
  modified:
    - itrader/core/enums/event.py

key-decisions:
  - "D-09: bus.py is 4-space, imports only stdlib + core.enums.event; Event is TYPE_CHECKING-only"
  - "D-10: PriorityEventBus is defined + unit-tested ONLY in P2, wired into no live path"
  - "D-11: no wiring touched — live_trading_system.py unchanged, poetry.lock byte-identical"
  - "Typed queue element as queue.Queue[Event] / PriorityQueue[tuple[EventTier,int,Event]] to satisfy mypy --strict (no Any returns)"

patterns-established:
  - "Two-tier event transport: CONTROL(0) preempts BUSINESS(1); BUSINESS is the default fall-through — only CONTROL is enumerated"
  - "get*() unwrap the priority tuple and return a BARE Event so the EventHandler drain contract is unchanged"

requirements-completed: [BUS-01, BUS-02, BUS-03]

coverage:
  - id: D1
    description: "EventBus Protocol + FifoEventBus + PriorityEventBus satisfy runtime_checkable isinstance; put/get round-trips same object; get_nowait raises queue.Empty on empty"
    requirement: "BUS-01"
    verification:
      - kind: unit
        ref: "tests/unit/events/test_event_bus.py#test_bus_satisfies_protocol / test_bus_put_get_roundtrips_same_object / test_get_nowait_raises_empty_on_empty"
        status: pass
    human_judgment: false
  - id: D2
    description: "PriorityEventBus dequeues CONTROL before BUSINESS, preserves strict within-tier FIFO, returns bare Event not tuple, and never compares events (event<event raises TypeError)"
    requirement: "BUS-02"
    verification:
      - kind: unit
        ref: "tests/unit/events/test_event_bus.py -k priority (9 tests)"
        status: pass
    human_judgment: false
  - id: D3
    description: "STREAM_STATE / CONNECTOR_FATAL / CONFIG_UPDATE EventType members exist, are in _CONTROL_EVENT_TYPES, and tier to CONTROL; BAR defaults BUSINESS"
    requirement: "BUS-03"
    verification:
      - kind: unit
        ref: "tests/unit/events/test_event_bus.py -k control_types (4 tests)"
        status: pass
      - kind: other
        ref: "poetry run python -c \"EventType('stream_state') is EventType.STREAM_STATE\""
        status: pass
    human_judgment: false

# Metrics
duration: 3min
completed: 2026-07-09
status: complete
---

# Phase 2 Plan 01: Event Bus Substrate Summary

**Pure two-tier event-bus substrate (EventBus Protocol + FifoEventBus + PriorityEventBus keyed by an itertools.count() seq) plus three CONTROL EventType members, proven by 18 stdlib-only unit tests — zero wiring touched, oracle-dark.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-07-09T12:57:00Z
- **Completed:** 2026-07-09T13:00:13Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- Added `STREAM_STATE`, `CONNECTOR_FATAL`, `CONFIG_UPDATE` to `EventType` (4-space, string-valued, `_missing_` case-insensitive parse still works).
- Created `itrader/events_handler/bus.py`: `EventBus` runtime_checkable Protocol, `EventTier` IntEnum, `_CONTROL_EVENT_TYPES` frozenset, `_tier()`, `FifoEventBus` (queue.Queue wrapper), `PriorityEventBus` (PriorityQueue keyed `(tier, seq, event)` with per-instance `itertools.count()` and lock-guarded per-tier depth Counter).
- Proved BUS-01/02/03 with 18 pure-stdlib unit tests, including the load-bearing non-orderability negative test (`event < event` raises `TypeError`).
- Kept the substrate import-inert: no pandas/sqlalchemy/ccxt pulled; `Event` is `TYPE_CHECKING`-only.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add three CONTROL EventType members** - `af1a2b9c` (feat)
2. **Task 2: Create the bus substrate** - `087a79f3` (feat)
3. **Task 3: Prove BUS-01/02/03 in a unit suite** - `20d99ac2` (test)

## Files Created/Modified
- `itrader/events_handler/bus.py` - NEW (4-space): the EventBus Protocol + EventTier + `_CONTROL_EVENT_TYPES` + `FifoEventBus` + `PriorityEventBus` substrate.
- `itrader/core/enums/event.py` - Added the three CONTROL EventType members before `ERROR`.
- `tests/unit/events/test_event_bus.py` - NEW (4-space): 18-test BUS-01/02/03 proof suite (no `__init__.py` in the dir).

## Decisions Made
- Typed the internal queues concretely (`queue.Queue[Event]`, `queue.PriorityQueue[tuple[EventTier, int, Event]]`) rather than `[Any]`. The plan's action text suggested `[Any]`, but `mypy --strict` (a plan verification gate) rejected the resulting `Returning Any from function declared to return "Event"`. Concrete typing is byte-identical at runtime, satisfies the mypy gate, and is strictly better — treated as a Rule 3 blocking fix (see Deviations). `Any` was dropped from the typing import as it became unused.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Concrete queue element typing for mypy --strict**
- **Found during:** Task 2 (Create the bus substrate)
- **Issue:** The plan's `<action>` specified `self._q: "queue.Queue[Any]"` and `self._pq: "queue.PriorityQueue[Any]"`. Under `mypy --strict` (plan verification gate line: "mypy ... clean (new code strict)"), the `[Any]` element type made `get`/`get_nowait` return `Any`, producing four `no-any-return` errors returning from functions declared `-> "Event"`.
- **Fix:** Typed the queues as `queue.Queue[Event]` and `queue.PriorityQueue[tuple[EventTier, int, Event]]` (string annotations, so `Event` stays `TYPE_CHECKING`-only). Removed the now-unused `Any` from the typing import.
- **Files modified:** `itrader/events_handler/bus.py`
- **Verification:** `poetry run mypy itrader/events_handler/bus.py itrader/core/enums/event.py` → "Success: no issues found in 2 source files"; runtime behaviour unchanged (all 18 tests pass, inertness gate green).
- **Committed in:** `087a79f3` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to pass the plan's own mypy verification gate. Runtime semantics byte-identical; no scope creep. All other plan acceptance criteria met exactly as written.

## Issues Encountered
None beyond the mypy typing fix above.

## Verification Evidence
- `poetry run pytest tests/unit/events/test_event_bus.py -x` → 18 passed.
- `-k priority` → 9 passed; `-k control_types` → 4 passed.
- `poetry run python -c "import itrader.events_handler.bus"` → clean (no heavy pull; pandas/sqlalchemy/ccxt not in `sys.modules`).
- `poetry run mypy itrader/events_handler/bus.py itrader/core/enums/event.py` → clean.
- `git diff --stat` (vs `b3eb2d18`) shows only `bus.py`, `event.py`, `test_event_bus.py`.
- `git diff --exit-code itrader/trading_system/live_trading_system.py` → no changes (D-11).
- `git diff --stat poetry.lock` → empty (no dependency change).
- No `tests/unit/events/__init__.py` created (package-collision hazard avoided).
- No tabs introduced in any of the three files (`grep -cP '^\t'` == 0 each).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Substrate ready: plan 02-03 wires `FifoEventBus` into the compose seam (`EngineContext(bus=...)`); P6/P7 will later wire `PriorityEventBus` into the live CONTROL-plane.
- No blockers. Oracle cannot have moved (no run-path wiring touched).

## Self-Check: PASSED
- FOUND: itrader/events_handler/bus.py
- FOUND: tests/unit/events/test_event_bus.py
- FOUND: itrader/core/enums/event.py (modified)
- FOUND commit: af1a2b9c (Task 1)
- FOUND commit: 087a79f3 (Task 2)
- FOUND commit: 20d99ac2 (Task 3)

---
*Phase: 02-event-bus*
*Completed: 2026-07-09*
