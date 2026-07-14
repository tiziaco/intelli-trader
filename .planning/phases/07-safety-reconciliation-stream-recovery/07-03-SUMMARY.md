---
phase: 07-safety-reconciliation-stream-recovery
plan: 03
subsystem: infra
tags: [safety, state-machine, halt, pause, dispatch-gate, order-risk-role, live-only]

# Dependency graph
requires:
  - phase: 07-safety-reconciliation-stream-recovery
    provides: "07-01: OrderRiskRole enum (core/enums/order.py), config/safety.py (SafetySettings), StreamStateEvent/ConnectorFatalEvent CONTROL events"
provides:
  - "SafetyController — pure live-engine safety state machine (status latch, halt/reset, pause/resume + deferred-protective queue, check_durable_halt_on_start), NO venue I/O"
  - "classify(event)->OrderRiskRole — the single shared risk predicate imported by the gate here + PreTradeThrottle (Plan 05)"
  - "gate_and_dispatch(event, dispatch_fn) — the freeze-in-place live dispatch gate, byte-moved from _dispatch_live"
  - "trading_system/safety/ subpackage (D-15), empty barrel (inertness-safe)"
affects: [07-04, 07-05, 07-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure injected state machine (bus + halt store + dispatch_fn + notify callback injected; no facade back-reference)"
    - "Byte-move extraction: donor bodies moved verbatim except the single D-11 overflow branch"
    - "Shared classify() predicate as one source of truth for gate + throttle (D-05/D-16)"

key-files:
  created:
    - itrader/trading_system/safety/__init__.py
    - itrader/trading_system/safety/safety_controller.py
    - tests/unit/trading_system/test_safety_controller.py
  modified:
    - tests/unit/core/test_order_risk_role.py

key-decisions:
  - "update_status is the public single-mutation seam (renamed from donor _update_status); force= reserved for reset_halt"
  - "_notify_status_change delegates exchange/queue-size enrichment + external status_callback to an injected notify_status_change callback so the machine stays pure (facade concern lifted out)"
  - "_replay_deferred_protective routes back through gate_and_dispatch (not raw dispatch) so a re-halt during replay re-defers"
  - "D-11 overflow reason is a fixed literal '_DEFERRED_PROTECTIVE_OVERFLOW_REASON' (V7 secret-scrub-safe); overflow halt()s and does NOT append/drop the offending order"

patterns-established:
  - "trading_system/safety/ subpackage never barrel-exported (Pitfall 5 inertness)"

requirements-completed: [SAFE-01, SAFE-02]

coverage:
  - id: D1
    description: "Pure SafetyController state machine (status latch, halt winner-only, reset_halt sole exit, pause/defer/resume replay), no venue I/O"
    requirement: "SAFE-01"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_safety_controller.py"
        status: pass
    human_judgment: false
  - id: D2
    description: "check_durable_halt_on_start re-latches HALTED via update_status from an unresolved durable record with NO second durable write"
    requirement: "SAFE-02"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_safety_controller.py#test_check_durable_halt_relatches_without_second_record"
        status: pass
    human_judgment: false
  - id: D3
    description: "Shared classify()->OrderRiskRole predicate (CANCEL/PROTECTIVE/ENTRY) consumed by gate_and_dispatch"
    requirement: "SAFE-01"
    verification:
      - kind: unit
        ref: "tests/unit/core/test_order_risk_role.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "D-11: deferred-protective queue overflow escalates to halt()+CRITICAL instead of silent drop-oldest"
    requirement: "SAFE-01"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_safety_controller.py#test_deferred_protective_overflow_escalates_to_halt"
        status: pass
    human_judgment: false
  - id: D5
    description: "Backtest oracle byte-exact (134 / 46189.87730727451) + OKX import inertness stay green (safety not barrel-exported)"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 03: SafetyController + classify() Summary

**Pure, injected `SafetyController` state machine byte-moved from `live_trading_system.py` (status latch, halt/reset, pause/resume + deferred-protective queue, durable-halt startup check) plus the single shared `classify()->OrderRiskRole` predicate and the D-11 overflow-to-HALT policy change.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-14T14:20:14Z
- **Completed:** 2026-07-14T14:26:27Z
- **Tasks:** 2
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- New `trading_system/safety/` subpackage (D-15) with an **empty** `__init__.py` — no re-exports, so the live stack never lands on the backtest import graph (Pitfall 5 inertness).
- `SafetyController` owns the byte-moved status latch: `update_status` (single mutation seam, `force=` reserved for `reset_halt`), winner-only `halt` (→ CRITICAL `ErrorEvent` → durable `record_halt`), `is_halted`/`reset_halt` (sole off-table exit + `resolve_all`), `pause_submission`/`resume_submission` + the bounded deferred-protective replay queue, and `check_durable_halt_on_start()` (SAFE-02 — re-latches via `update_status`, never a second durable write). No venue I/O.
- Module-level `classify(event)->OrderRiskRole` extracted **once** from the inline `_dispatch_live` classification (D-05/D-16); `gate_and_dispatch` consumes it, and Plan 05's throttle imports the same predicate.
- D-11 (the ONE behavior change): the deferred-protective queue overflow escalates to `halt()` + CRITICAL alert instead of the silent drop-oldest; every other extracted body is byte-identical to its donor.

## Task Commits

1. **Task 1: pure SafetyController state machine (SAFE-01/02)** - `ca205729` (feat)
2. **Task 2: shared classify() + gate_and_dispatch + D-11 overflow** - `cf4cb0ee` (feat)

## Files Created/Modified
- `itrader/trading_system/safety/__init__.py` - Empty package marker (inertness-safe, no re-exports)
- `itrader/trading_system/safety/safety_controller.py` - `SafetyController` (pure state machine) + module-level `classify()`
- `tests/unit/trading_system/test_safety_controller.py` - 15 unit tests (latch/halt/reset/pause-replay/durable-halt/gate/overflow) with fakes
- `tests/unit/core/test_order_risk_role.py` - Added 4 `classify()` predicate tests (CANCEL/PROTECTIVE/ENTRY/raw-SIGNAL)

## Decisions Made
- **`update_status` is the public seam** (renamed from donor `_update_status`) — matches the must-have "single update_status seam"; `is_halted`/`is_submission_paused` also made public for the injected consumers.
- **`_notify_status_change` delegates facade concerns** (exchange/queue-size enrichment + external `status_callback`) to an injected `notify_status_change` callback, keeping the controller pure. The facade (Plan 06) will supply that callback.
- **`_replay_deferred_protective` re-routes through `gate_and_dispatch`** (not raw dispatch) so a re-halt raised during replay re-defers onto the now-empty queue rather than sending blind — preserves the donor's snapshot-then-clear safety.
- **`dispatch_fn` is injected at construction AND accepted per-call** on `gate_and_dispatch` (defaults to the injected canonical fn) so replay/resume can dispatch without threading the fn through `resume_submission` (kept param-free per byte-move).
- **D-11 overflow reason** is a fixed module literal `deferred-protective-overflow` (V7 secret-scrub-safe); on overflow the controller `halt()`s and does NOT append or drop the offending order.

## Deviations from Plan

None - plan executed exactly as written. The `_notify_status_change` callback-delegation and the `update_status`/`is_halted` public-naming were explicitly anticipated by the plan (injected notify callback; "single update_status seam"), not unplanned work.

## Issues Encountered
- The Task 1 acceptance grep `catch_up_missed_fills|\.snapshot\(|backfill|ccxt|connector\.` initially matched the module docstring that *named* the forbidden venue-I/O methods (to document what is out of scope). Reworded the docstring to avoid the literal tokens; grep now returns 0. No code change.

## Next Phase Readiness
- `SafetyController` + `classify()` are ready. Plan 04 (`StreamRecoveryHandler`) consumes `resume_submission`; Plan 05 (`PreTradeThrottle`) imports `classify`; Plan 06 does the facade surgery (removes the donor methods from `live_trading_system.py`, wires `check_durable_halt_on_start` first at `start()`, and injects the `notify_status_change` callback).
- Donor methods remain in `live_trading_system.py` (facade keeps working on its own copies until Plan 06) — intentional per the plan.

## Self-Check: PASSED
- All 4 key files exist on disk (verified).
- Both task commits present in git history (`ca205729`, `cf4cb0ee`).
- Verification: `pytest tests/unit/trading_system tests/unit/core -q` → 198 passed; `mypy --strict` clean on the new file; oracle byte-exact (134 / 46189.87730727451) + OKX inertness green.

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
