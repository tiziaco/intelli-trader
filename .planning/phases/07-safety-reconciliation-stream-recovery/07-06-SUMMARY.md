---
phase: 07-safety-reconciliation-stream-recovery
plan: 06
subsystem: live-trading
tags: [safety, assembly, control-events, facade, composition-root, live-only, stream-recovery, reconciliation, throttle]

# Dependency graph
requires:
  - phase: 07-safety-reconciliation-stream-recovery
    provides: "07-01 CONTROL events (StreamStateEvent/ConnectorFatalEvent) + config.safety; 07-03 SafetyController (+ classify/gate_and_dispatch/check_durable_halt_on_start); 07-04 StreamRecoveryHandler (+ CF-2 ring assertion); 07-05 PreTradeThrottle; 07-02 ReconciliationCoordinator"
provides:
  - "CONTROL routing wired: STREAM_STATE(down)->SafetyController.pause_submission, STREAM_STATE(up)->StreamRecoveryHandler.on_reconnect, CONNECTOR_FATAL->SafetyController.halt (via LiveRouteRegistrar, list order = execution order)"
  - "Flag side-channel DELETED (_pending_stream_resume/_pending_connector_halt/_pending_connector_halt_reason gone; the 2 LiveRunner drain hooks + 4 call sites removed)"
  - "Thin-delegator LiveTradingSystem facade over the injected SafetyController/StreamRecoveryHandler/PreTradeThrottle + a ReconciliationCoordinator built at start()"
  - "PreTradeThrottle fires at the pre-submit (ORDER->execution) boundary ahead of the dispatch gate (D-06); dispatch gate repointed to SafetyController.gate_and_dispatch"
  - "check_durable_halt_on_start() runs FIRST at start() (SAFE-02 first-run wiring); reconcile block delegates to ReconciliationCoordinator (SAFE-05)"
affects: [live-trading, safety, phase-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CONTROL-event connector handoff replaces the thread-flag side-channel (connector loop bus.puts a fixed-shape event; engine-thread routes are the sole actuators, LR-12)"
    - "Late-bound dispatch_fn (lambda over event_handler._dispatch) injected into SafetyController so gate/replay honour a live-patched inner dispatch"
    - "ReconciliationCoordinator constructed at start() from CURRENT venue fields (not build-time capture) so the live/swappable venue arms are honoured"

key-files:
  created: []
  modified:
    - itrader/trading_system/route_registrar.py
    - itrader/trading_system/live_runner.py
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/session_initializer.py
    - itrader/trading_system/safety/safety_controller.py
    - tests/integration/test_live_system_okx_wiring.py
    - tests/integration/test_early_durable_halt_refusal.py
    - tests/integration/test_durable_halt.py
    - tests/integration/test_live_portfolio_durable_wiring.py
    - tests/integration/test_resume_gated_on_all_streams.py
    - tests/integration/test_resume_missed_fill_catchup.py
    - tests/unit/execution/test_drift_halt_policy.py
    - tests/unit/execution/test_off_loop_halt_write.py
    - tests/unit/execution/test_reconnect_resilience.py
    - tests/unit/trading_system/test_pause_defer_replay.py

key-decisions:
  - "ReconciliationCoordinator is constructed at start() (in _build_reconciliation_coordinator) rather than build_live_system — it must read the CURRENT venue account/exchange/connector (live, swappable-before-start facade fields), not a build-time capture; the grep acceptance (constructor appears in the file) still holds"
  - "SafetyController.dispatch_fn injected as a LATE-BOUND lambda over event_handler._dispatch so the gate + deferred-protective replay honour a monkeypatched inner dispatch (preserving the donor _dispatch_live's live read)"
  - "Added SafetyController.status_snapshot() read seam so the facade get_status() reads the controller-owned status/halt/pause fields (single source of truth) + merges the throttle breach_count (D-09)"
  - "ConnectorFatalEvent.reason is the FIXED literal HaltReason.CONNECTOR_FATAL.value (never the passed reason / str(exc)) — V7 secret-scrub across the loop->engine boundary"
  - "Facade retains _link_venue_account_to_portfolios + _run_session_baseline_guard as tested seams (the ReconciliationCoordinator owns the production path); a minor duplication, test-covered not dead"

requirements-completed: [SAFE-03]

coverage:
  - id: D1
    description: "Connector stream up/down/fatal arrive as CONTROL events routed on the engine thread to pause_submission / on_reconnect / halt (via LiveRouteRegistrar)"
    requirement: "SAFE-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_live_system_okx_wiring.py#test_connector_control_events_route_to_safety_and_recovery"
        status: pass
    human_judgment: false
  - id: D2
    description: "The _pending_* flag side-channel + the 2 LiveRunner drain hooks (+ 4 call sites) are deleted; the runner invokes the throttle pre_submit ahead of the dispatch gate"
    requirement: "SAFE-03"
    verification:
      - kind: command
        ref: "grep -c '_pending_stream_resume|_pending_connector_halt' live_trading_system.py live_runner.py == 0; grep -c pre_submit live_runner.py >= 2"
        status: pass
      - kind: unit
        ref: "tests/unit/execution/test_off_loop_halt_write.py"
        status: pass
    human_judgment: false
  - id: D3
    description: "check_durable_halt_on_start() runs FIRST at start() and refuses RUNNING inert on an unresolved durable halt (SAFE-02 wiring)"
    requirement: "SAFE-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_early_durable_halt_refusal.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_durable_halt.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "build_live_system constructs+wires SafetyController/StreamRecoveryHandler/PreTradeThrottle (+ ReconciliationCoordinator at start()); dispatch gate -> gate_and_dispatch, pre_submit -> throttle.allow"
    requirement: "SAFE-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_live_system_okx_wiring.py"
        status: pass
      - kind: command
        ref: "grep -cE 'SafetyController\\(|StreamRecoveryHandler\\(|PreTradeThrottle\\(|ReconciliationCoordinator\\(' live_trading_system.py >= 4"
        status: pass
    human_judgment: false
  - id: D5
    description: "Backtest oracle byte-exact (134 / 46189.87730727451) + OKX import inertness + paper-replay parity stay green (safety imports stay lazy in build_live_system)"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_paper_parity.py"
        status: pass
    human_judgment: false

# Metrics
duration: 45min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 06: Safety Assembly + CONTROL Routing Summary

**The Phase 07 integration seam: rewired the connector stream/fatal handoff into `StreamStateEvent`/`ConnectorFatalEvent` CONTROL events routed on the engine thread (deleting the `_pending_*` flag side-channel + the two LiveRunner drain hooks), shrank `LiveTradingSystem` to a thin delegator over the injected `SafetyController`/`StreamRecoveryHandler`/`PreTradeThrottle` + a start()-built `ReconciliationCoordinator`, ran `check_durable_halt_on_start()` first, and fired the pre-trade throttle at the pre-submit boundary — with the backtest oracle byte-exact and the live stack import-inert.**

## Performance
- **Duration:** ~45 min
- **Tasks:** 3
- **Files modified:** 15 (5 source, 10 test); 0 created

## Accomplishments
- **CONTROL routing (SAFE-03):** `LiveRouteRegistrar` now SETs `STREAM_STATE`/`CONNECTOR_FATAL` routes (injected `safety`+`stream_recovery`): down→`pause_submission`, up→`on_reconnect`, fatal→`halt`. Threaded through `SessionInitializer` from the facade.
- **Flag side-channel deleted:** `_pending_stream_resume`/`_pending_connector_halt`/`_pending_connector_halt_reason` gone; the two `LiveRunner` drain hooks + their 4 call sites removed; connector callbacks now `bus.put` CONTROL events (fixed V7 reason literal) instead of flipping flags.
- **Thin-delegator facade:** the status latch / halt / pause / deferred-protective queue / dispatch gate / durable-halt machinery moved to the collaborators; the facade forwards `halt`/`pause_submission`/`resume_submission`/`reset_halt`/`is_halted`/`get_status` and reads the controller's `status_snapshot()` (+ throttle `breach_count`, D-09).
- **`check_durable_halt_on_start()` runs FIRST** at `start()` (before any venue I/O); the inline reconcile block delegates to a `ReconciliationCoordinator` built at start() from the live venue fields; the `PreTradeThrottle` fires at the pre-submit (ORDER→execution) boundary ahead of `SafetyController.gate_and_dispatch`.
- **Gates green:** backtest oracle byte-exact (134 / 46189.87730727451), OKX import inertness, paper-replay parity, and the full suite (2199 passed, 6 skipped); `mypy --strict` clean (257 files).

## Task Commits
1. **Task 1: CONTROL routes + delete LiveRunner drain hooks + throttle pre_submit** — `b6fb3d62` (feat)
2. **Task 2+3: facade surgery + build_live_system assembly + donor-test migration** — `925ce494` (feat)
3. **Task 3: CONTROL-route wiring integration test** — `f4d30c31` (test)

(Task 2 and Task 3 both edit `build_live_system`/the facade in one file, so the assembly landed in commit `925ce494`; the CONTROL-route integration test is `f4d30c31`.)

## Deviations from Plan

### [Rule 3 - Blocking] ReconciliationCoordinator constructed at start(), not build_live_system
- **Found during:** Task 3
- **Issue:** The plan's must-have places the coordinator's construction in `build_live_system`, but the coordinator captures `venue_account`/`exchange`/`connector` at construction. The live suite (durable-halt + okx-wiring + durable-wiring tests) swaps `system._venue_account` AFTER build and expects the reconcile to use the live value; a build-time capture used a stale VenueAccount and crashed (`fetch_balance` on a None connector).
- **Fix:** Added `LiveTradingSystem._build_reconciliation_coordinator()` (lazy import) that builds the coordinator from the CURRENT facade venue fields, called in `start()` right before `run_startup_reconcile()`. Production-faithful (nothing swaps the fields in production) and the grep acceptance (`ReconciliationCoordinator(` appears in the file) still holds.
- **Files:** itrader/trading_system/live_trading_system.py
- **Commit:** 925ce494

### [Rule 2 - Missing critical] SafetyController.status_snapshot() read seam
- **Found during:** Task 2
- **Issue:** The facade's `get_status()` must read the now controller-owned status/halt_reason/paused/last_error, but `SafetyController` exposed only `is_halted()`/`is_submission_paused()`.
- **Fix:** Added a read-only `status_snapshot()` (one `_status_lock` acquisition) returning the safety-owned fields; the facade merges it with stats + the throttle breach counter.
- **Files:** itrader/trading_system/safety/safety_controller.py
- **Commit:** 925ce494

### [Rule 3 - Blocking] SessionInitializer threads safety+stream_recovery to the registrar
- **Found during:** Task 2
- **Issue:** The CONTROL routes need the safety+stream_recovery collaborators, but the registrar is constructed inside `SessionInitializer.initialize()` (not directly in build_live_system). Not in the plan's file list.
- **Fix:** Added `safety`/`stream_recovery` params to `SessionInitializer.__init__` and passed them into `LiveRouteRegistrar(...)`.
- **Files:** itrader/trading_system/session_initializer.py
- **Commit:** 925ce494

### [Rule 3 - Blocking] Migrated 7 facade-donor test files beyond the plan's 3
- **Found during:** Task 2
- **Issue:** Deleting the donor methods from the facade breaks tests that drove them directly (`_dispatch_live`, `_maybe_resume_after_reconnect`, `_pending_stream_resume`, `_maybe_halt_after_connector_fatal`, `_is_submission_paused`, `system._halt_record_store` swaps). The plan listed only 3 test files; the "full suite green" gate requires handling all.
- **Fix:** Migrated the tests to drive the collaborators via the facade's new surface — `_dispatch_live`→`_safety.gate_and_dispatch`; resume→`_stream_recovery.on_reconnect()` (patching `_stream_recovery._venue_account`/`_okx_exchange`); connector-fatal→drain the queued `ConnectorFatalEvent` and `_safety.halt`; durable-store doubles injected on `_safety._halt_record_store`. `test_live_portfolio_durable_wiring` updated for the coordinator's `is_venue_truth` keying + halt-via-`halt_signal`. All logic remains covered by the Plan 03/04/05 collaborator unit tests plus these integration seams.
- **Files:** test_pause_defer_replay.py, test_reconnect_resilience.py, test_drift_halt_policy.py, test_off_loop_halt_write.py, test_resume_gated_on_all_streams.py, test_resume_missed_fill_catchup.py, test_live_portfolio_durable_wiring.py
- **Commit:** 925ce494

**Total deviations:** 4 auto-fixed (1 missing-critical, 3 blocking). **Impact:** the collaborator-capture-vs-live-swap tension (coordinator + halt store) drove a start()-time coordinator build and test-seam relocation; no behavior regression — all gates + the full suite are green.

## Import Sweep (ignore_errors blindspot)
Swept `live_trading_system.py` after the donor deletions: removed now-unused imports (`deque`, `ErrorEvent`, `ErrorSeverity`, `OrderCommand`, `VALID_STATUS_TRANSITIONS`) and the `_DEFERRED_PROTECTIVE_REPLAY_MAX` module constant; added `StreamStateEvent`/`ConnectorFatalEvent`. Verified every remaining import is referenced. `_link_venue_account_to_portfolios`/`_run_session_baseline_guard` are retained as test-covered seams (the coordinator owns the production path). `mypy --strict` clean.

## Issues Encountered
None outstanding — all gates and the full suite (2199 passed, 6 OKX-credential-gated skips) are green.

## Next Phase Readiness
Phase 07 is fully assembled: the five wave-1..3 collaborators are wired into a working live safety subsystem. Backtest oracle byte-exact + inertness + paper-parity hold. Ready for Phase 07 verification / close.

## Self-Check: PASSED
- All 5 modified source files exist on disk (verified).
- Task commits present: `b6fb3d62`, `925ce494`, `f4d30c31` (verified in git log).
- Acceptance greps: collaborators >=4 (4), hook args removed (0), flags removed (0), CONTROL events >=3 (6), pre_submit >=2 (6), prohibition flag grep across both files (0).
- Gates: oracle 134/46189.87730727451, inertness, paper-parity, full suite (2199 passed), mypy --strict (257 files) all green.

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
