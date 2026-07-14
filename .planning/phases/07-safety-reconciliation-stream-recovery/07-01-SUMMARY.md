---
phase: 07-safety-reconciliation-stream-recovery
plan: 01
subsystem: infra
tags: [enum, msgspec, pydantic, config, safety, control-events, decimal, uuidv7]

# Dependency graph
requires:
  - phase: 06
    provides: "EventType.STREAM_STATE / CONNECTOR_FATAL members (core/enums/event.py), config/stream.py eager-field inertness pattern"
provides:
  - "OrderRiskRole enum (CANCEL/PROTECTIVE/ENTRY) — shared risk-role vocabulary for the SafetyController gate (Plan 03) + PreTradeThrottle (Plan 05)"
  - "StreamStateEvent / ConnectorFatalEvent CONTROL msgspec.Struct events — connector→engine handoff classes for Plan 06 callbacks + routes"
  - "config/safety.py (ThrottleSettings/SafetySettings) + eager SystemConfig.safety field — static throttle caps for Plan 05 + deferred-queue bound (Plan 03)"
affects: [07-03, 07-05, 07-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OrderCommand house-pattern enum (explicit str values + case-insensitive _missing_) reused for OrderRiskRole"
    - "events/error.py msgspec.Struct event shape (type: ClassVar[EventType] pin) reused for CONTROL events"
    - "config/stream.py eager-inertness-safe SystemConfig field reused for SystemConfig.safety"

key-files:
  created:
    - itrader/events_handler/events/control.py
    - itrader/config/safety.py
    - tests/unit/core/test_order_risk_role.py
    - tests/unit/events/test_control_events.py
    - tests/unit/config/test_safety_config.py
  modified:
    - itrader/core/enums/order.py
    - itrader/core/enums/__init__.py
    - itrader/events_handler/events/__init__.py
    - itrader/config/system.py
    - itrader/config/__init__.py

key-decisions:
  - "OrderRiskRole is enum-only in core/enums/order.py; classify() defers to SafetyController in Plan 03 (D-16)"
  - "ConnectorFatalEvent.reason is a fixed-literal str field, never a stringified exception/payload (V7 secret-scrub, T-07-01) — enforced by grep-0 in the module"
  - "SafetySettings is the one-domain container shaping the P9 mutation seam (D-14); no runtime ConfigUpdateEvent wiring in P7"

patterns-established:
  - "Shared risk-role enum as single source of truth for gate + throttle (D-05/D-16)"
  - "CONTROL-tier msgspec events are barrel-export inertness-safe (never constructed on the backtest path)"

requirements-completed: [SAFE-01, SAFE-03, SAFE-06]

coverage:
  - id: D1
    description: "OrderRiskRole enum (CANCEL/PROTECTIVE/ENTRY) in TAB-indented core/enums/order.py, barrel-exported, case-insensitive _missing_, no classify()"
    requirement: "SAFE-01"
    verification:
      - kind: unit
        ref: "tests/unit/core/test_order_risk_role.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "StreamStateEvent / ConnectorFatalEvent msgspec.Struct CONTROL events with type pins, barrel-exported, secret-scrubbed reason"
    requirement: "SAFE-03"
    verification:
      - kind: unit
        ref: "tests/unit/events/test_control_events.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "config/safety.py ThrottleSettings/SafetySettings (static caps ON by default) + eager inertness-safe SystemConfig.safety field"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/config/test_safety_config.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
    human_judgment: false

# Metrics
duration: 12 min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 01: Shared Safety Primitives Summary

**OrderRiskRole enum (D-16), the StreamStateEvent/ConnectorFatalEvent CONTROL msgspec events (SAFE-03), and config/safety.py throttle caps wired as an eager inertness-safe SystemConfig.safety field (D-07/D-13/D-14) — three pure, backtest-dark primitives that unblock Plans 03/05/06.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-14T13:46Z
- **Completed:** 2026-07-14T13:59Z
- **Tasks:** 3
- **Files modified:** 10 (5 created, 5 modified)

## Accomplishments
- `OrderRiskRole(Enum)` (CANCEL/PROTECTIVE/ENTRY) added to the TAB-indented `core/enums/order.py`, matching the `OrderCommand` house pattern (explicit str values + case-insensitive `_missing_`), barrel-exported, enum-only per D-16 (no `classify()`).
- `StreamStateEvent(stream_name, up)` and `ConnectorFatalEvent(reason)` authored as frozen `msgspec.Struct` subclasses of `Event` in a new `events/control.py`, `type` pinned to the pre-existing `EventType.STREAM_STATE`/`CONNECTOR_FATAL` members, `reason` documented as a fixed-literal-only V7-scrubbed field, barrel-exported.
- `config/safety.py` with `ThrottleSettings` (10 orders / 10s + `Decimal('25000')` notional + 5s WARN dedup, `extra="forbid"`, ON by default) and the `SafetySettings` one-domain container, wired as an eager `SystemConfig.safety` field mirroring the `config/stream.py` inertness note.
- Both phase gates stay green — backtest oracle byte-exact (`134 / 46189.87730727451`) and OKX import inertness — plus `mypy --strict` clean on all touched source files and 320 unit tests passing in the touched suites.

## Task Commits

Each task was committed atomically:

1. **Task 1: OrderRiskRole enum (D-16)** - `08e5a19a` (feat)
2. **Task 2: CONTROL event classes (SAFE-03)** - `34092339` (feat)
3. **Task 3: config/safety.py + SystemConfig.safety (D-07/D-13/D-14)** - `03c01578` (feat)

## Files Created/Modified
- `itrader/core/enums/order.py` - added `OrderRiskRole` enum (TABS, after `OrderCommand`)
- `itrader/core/enums/__init__.py` - barrel-export `OrderRiskRole`
- `itrader/events_handler/events/control.py` - NEW: `StreamStateEvent` / `ConnectorFatalEvent` msgspec CONTROL events
- `itrader/events_handler/events/__init__.py` - barrel-export the two CONTROL events
- `itrader/config/safety.py` - NEW: `ThrottleSettings` / `SafetySettings` (static caps, `extra="forbid"`, `default()`)
- `itrader/config/system.py` - import `SafetySettings`; eager `safety` field with inertness note
- `itrader/config/__init__.py` - barrel-export `SafetySettings` / `ThrottleSettings`
- `tests/unit/core/test_order_risk_role.py` - NEW: members/values/case-insensitive/no-classify
- `tests/unit/events/test_control_events.py` - NEW: type pins, construction, frozen
- `tests/unit/config/test_safety_config.py` - NEW: defaults, Decimal, extra=forbid, SystemConfig reach

## Decisions Made
- Kept `OrderRiskRole` enum-only; `classify()` deferred to `SafetyController` (Plan 03) per D-16.
- `ConnectorFatalEvent.reason` is a fixed-literal `str` field — the V7 secret-scrub note in the module docstring was reworded to avoid the literal `str(exc)` token so the plan's grep-0 acceptance guard passes while keeping the prohibition explicit (see Deviations).
- Barrel-exported `SafetySettings`/`ThrottleSettings` from `itrader.config` to mirror the existing `StreamSettings` export convention (not strictly required by the plan, but consistent with the sibling config domain).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded V7 docstring to satisfy the grep-0 `str(exc` acceptance guard**
- **Found during:** Task 2 (CONTROL event classes)
- **Issue:** The plan's acceptance criterion requires `grep -c 'str(exc' control.py` to return `0`, but the natural way to document the V7 prohibition referenced the literal `str(exc)` token, tripping the guard (initial grep returned 2).
- **Fix:** Reworded the module + field docstrings to "stringified from a caught exception" / "a stringified exception", preserving the identical security meaning while removing the `str(exc` substring; also updated the test file comment.
- **Files modified:** `itrader/events_handler/events/control.py`, `tests/unit/events/test_control_events.py`
- **Verification:** `grep -c 'str(exc' itrader/events_handler/events/control.py` → `0`; control-event unit tests + inertness gate green.
- **Committed in:** `34092339` (Task 2 commit)

**2. [Rule 2 - Missing Critical] Added `config/__init__.py` barrel export for the new safety settings**
- **Found during:** Task 3 (config/safety.py)
- **Issue:** The plan named `config/safety.py` + `config/system.py` but not `config/__init__.py`; the sibling `StreamSettings`/`FeedProviderSettings` are barrel-exported from `itrader.config`, and the new test imports `from itrader.config import SafetySettings, ThrottleSettings`.
- **Fix:** Added `SafetySettings`/`ThrottleSettings` to the `config/__init__.py` import list + `__all__`, mirroring the stream-domain block.
- **Files modified:** `itrader/config/__init__.py`
- **Verification:** `from itrader.config import SafetySettings, ThrottleSettings` succeeds; safety config tests green; inertness gate green.
- **Committed in:** `03c01578` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing-critical)
**Impact on plan:** Both are convention/guard alignment with no behavioral or security change — the V7 scrub semantics are unchanged and the barrel export mirrors the established config-domain pattern. No scope creep.

## Issues Encountered
None - planned work proceeded cleanly; both phase gates and mypy --strict were green on first full run.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `OrderRiskRole`, the two CONTROL events, and `SystemConfig.safety` are all in place and consumable by downstream plans:
  - Plan 03 (`SafetyController` + `classify()`) consumes `OrderRiskRole` + `SystemConfig.safety` (deferred-queue bound).
  - Plan 05 (`PreTradeThrottle`) consumes `OrderRiskRole` + `ThrottleSettings`.
  - Plan 06 (connector callbacks + CONTROL routes) constructs `StreamStateEvent`/`ConnectorFatalEvent`.
- No blockers. Backtest path remains byte-exact and import-inert.

## Self-Check: PASSED
- Created files verified on disk: `itrader/events_handler/events/control.py`, `itrader/config/safety.py`, three new test files — all present.
- Commits verified: `08e5a19a`, `34092339`, `03c01578` all in `git log`.
- Gates: oracle `134 / 46189.87730727451` green; `test_okx_inertness.py` green; `mypy --strict` clean; 320 touched-suite unit tests pass.

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
