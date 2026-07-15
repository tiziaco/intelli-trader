---
phase: 08-error-subsystem
verified: 2026-07-15T00:00:00Z
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: No — initial verification
---

# Phase 8: Error Subsystem Verification Report

**Phase Goal:** Inject an `ErrorPolicy` into `EventHandler` (removing the monkeypatch), formalize
the `ErrorHandler` ERROR-route consumer with two-guard terminal safety, and ship the CF-1 aggregate
circuit breaker that actually trips — all leaving backtest fail-fast byte-for-byte unchanged.
**Verified:** 2026-07-15
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ErrorPolicy` is injected into `EventHandler` at construction; backtest/replay → fail-fast re-raise, live → publish-and-continue; per-handler granularity + WR-06 source guard; backtest byte-exact | ✓ VERIFIED | `EventHandler.__init__` requires `error_policy`/`error_handler` params (`itrader/events_handler/full_event_handler.py:49-79`); `_dispatch` except-block calls `self._error_policy.on_handler_error(event, handler)` (line 158); `compose_engine` selects `FailFastPolicy()` when `error_policy is None`, else the injected live `ErrorPolicy` (`compose.py:265-282`); `build_live_system` constructs the live `ErrorPolicy` and threads it through `compose_engine` (`live_trading_system.py:1054-1076`); the old `start()` monkeypatch line (`self.event_handler._on_handler_error = ...`) is gone — confirmed via grep (0 hits) and by reading the `start()` body around the removal comment (lines ~583-588). Oracle re-run independently: `tests/integration/test_backtest_oracle.py` 3 passed, byte-exact 134/46189.87730727451. |
| 2 | The CF-1 aggregate circuit breaker (SETTLEMENT halt-on-first, ORDER-IO 3/60s, ADMISSION 3/300s, LOOP-BACKSTOP 5/60s) actually trips, proven by a "money route failing every event" test, while preserving the WR-06 terminal swallow | ✓ VERIFIED | `_POLICY_FIELDS` map (`error_policy.py:76-97`) carries the exact D-14 thresholds/windows; `should_trip`/`record_failure`/`classify_failure` implement the sliding-window tripwire (lines 100-134, 240-259). Independently re-ran `tests/unit/events/test_error_policy.py::test_settlement_trips_on_first` (unit-level, fake halt) AND the live end-to-end `tests/unit/events/test_error_flow.py::test_live_fill_route_failure_trips_halt_and_keeps_draining` (constructs the real `EventHandler`/`ErrorPolicy`/`ErrorHandler` graph, drives a FILL handler raising every event, asserts `fake_halt` called once with `HaltReason.SETTLEMENT_FAILURE.value` on the first failure, queue fully drains, no exception escapes) — both PASS (3 passed in 0.02s, this session). |
| 3 | `ErrorHandler` formalizes the ERROR-route consumer (severity-mapped log, CRITICAL → alert-sink, persist state.last_error via SystemStore, WR-06 consumer guard); handler failures, halt() CRITICAL, PortfolioErrorEvent, ConnectorFatalEvent all funnel through the one ERROR route | ✓ VERIFIED | `itrader/events_handler/error_handler.py::ErrorHandler.on_error` implements severity-mapped logging (WARNING/CRITICAL/else-ERROR, lines 101-118), CRITICAL→alert_sink (125-126), D-17 `system_store.upsert('state.last_error', ...)` scrubbed-field persist (133-151), and the whole body is wrapped in a WR-06 try/except with inner last-resort log (101, 163-173). Funnel traced for all 4 sources: (a) handler failure → `ErrorPolicy.on_handler_error` publishes an `ErrorEvent` → ERROR route; (b) `SafetyController.halt()` emits a CRITICAL `ErrorEvent` onto the bus (`safety_controller.py:187-196`) → ERROR route; (c) `PortfolioErrorEvent` subclasses `ErrorEvent` with `type=EventType.ERROR` (`events/error.py:64-74`) → ERROR route directly; (d) `ConnectorFatalEvent` routes to `route_registrar.py::_on_connector_fatal` which calls `self._safety.halt(event.reason)` → same CRITICAL-ErrorEvent path as (b). Re-ran `test_error_flow.py::test_critical_and_portfolio_error_events_both_funnel_to_error_handler` independently — PASS. `test_composition_root_wires_a_log_alert_sink` (asserts live root wires `LogAlertSink` into `event_handler.error_handler._alert_sink`) re-run independently — PASS. |
| 4 | `test_okx_inertness.py` stays green | ✓ VERIFIED | Re-ran independently: `tests/integration/test_okx_inertness.py` — 4 passed. |

**Score:** 4/4 roadmap-level truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/enums/system.py` | `FailureClass` (5 members) + 4 new `HaltReason` members, existing 5 unchanged | ✓ VERIFIED | Read in full; `FailureClass` has SETTLEMENT/ORDER_IO/ADMISSION/LOOP_BACKSTOP/FILL_TRANSLATION; `HaltReason` gained SETTLEMENT_FAILURE/ORDER_ROUTE_ERRORS/ADMISSION_ERRORS/LOOP_BACKSTOP with new wire strings; original 5 members (`baseline-residual`, `connector-fatal`, `reconciliation-unresolved`, `durable-halt`, `drift`) byte-unchanged; barrel-exported in `__all__`. |
| `itrader/config/safety.py` | `FailureRateSettings` on `SafetySettings.failure_rate`, D-14 defaults, `extra=forbid` | ✓ VERIFIED | `FailureRateSettings(BaseModel)` present with `ConfigDict(extra="forbid")`, named per-class threshold/window_s fields matching D-14 defaults (settlement 1/60.0, and — confirmed by grep — order_io/admission/loop_backstop present). |
| `itrader/execution_handler/exchanges/okx.py` | Both fill-translation drain paths emit scrubbed counted `ErrorEvent` | ✓ VERIFIED | `_consume_fills` (line ~794) and `catch_up_missed_fills` (line ~692) both emit `ErrorEvent(source="okx_exchange", operation="fill-translation", error_type=type(exc).__name__, error_message=_FILL_TRANSLATION_ERROR_MSG, severity=ErrorSeverity.ERROR)` — no `str(exc)`/raw payload. |
| `itrader/events_handler/error_policy.py` | Relocated `ErrorPolicy` + `HandlerErrorPolicy` Protocol + `FailFastPolicy` + tripwire (`should_trip`/`classify_failure`/`_POLICY_FIELDS`/`record_failure`/`bind`/`breaker_snapshot`) | ✓ VERIFIED | Full file read; all symbols present and match the plan's described behavior exactly. `itrader/trading_system/error_policy.py` confirmed deleted (`ls` → No such file). |
| `itrader/events_handler/error_handler.py` | New `ErrorHandler` class, WR-06 consumer guard, D-17 persist, FILL_TRANSLATION counting seam | ✓ VERIFIED | Full file read; matches plan precisely, including the `_AlertSinkLike` duck-typed Protocol (no runtime import of `trading_system.alert_sink`/`storage.system_store`). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `EventHandler._dispatch` except-block | `ErrorPolicy`/`FailFastPolicy` | `self._error_policy.on_handler_error(event, handler)` | ✓ WIRED | `full_event_handler.py:158`, injected at `__init__` (constructor param, no monkeypatch). |
| ERROR route | `ErrorHandler.on_error` | `self.routes[EventType.ERROR] = [self.error_handler.on_error]` | ✓ WIRED | `full_event_handler.py:114`. |
| `compose_engine` | `ErrorHandler`/policy selection | Builds `ErrorHandler(alert_sink, system_store, failure_sink=error_policy)`; `policy = error_policy or FailFastPolicy()` | ✓ WIRED | `compose.py:265-282`; backtest callers pass no kwargs → all None → log-only no-op graph, oracle byte-exact (independently re-verified). |
| `build_live_system` | `compose_engine` | `alert_sink=LogAlertSink()`, gated `SystemStore(system_db_backend)`, live `ErrorPolicy(bus, failure_settings=...)` | ✓ WIRED | `live_trading_system.py:1054-1076`; `SystemStore` mint gated on `system_db_backend is not None` mirroring the `HaltRecordStore` gate — no second `SqlEngine` (D-05 NEGATIVE, confirmed researched/grep-verified in `08-RESEARCH.md`). |
| `error_policy.bind` | `safety.halt` / `facade._increment_error_count` | Late-bind after `SafetyController` + facade exist | ✓ WIRED | `live_trading_system.py:1259` — `error_policy.bind(halt=safety.halt, error_counter=facade._increment_error_count)`. |
| `ErrorHandler.on_error` | `ErrorPolicy.record_failure` | `failure_sink.record_failure(classify_failure(event))` for the off-thread okx FILL_TRANSLATION event | ✓ WIRED | `error_handler.py:159-162`; `classify_failure` returns `None` for non-okx ERROR events, preventing double-count. |
| `SafetyController.halt` / `route_registrar._on_connector_fatal` | ERROR route | CRITICAL `ErrorEvent` put on bus | ✓ WIRED | `safety_controller.py:187-196` (halt emits CRITICAL ErrorEvent); `route_registrar.py:142-149` (`ConnectorFatalEvent` → `safety.halt(event.reason)` → same path). |
| `build_paper_replay_system` | `FailFastPolicy` override | `system.event_handler._error_policy = FailFastPolicy()` | ✓ WIRED | `tests/support/replay_harness.py:405` — deliberate deviation (Rule 2, documented in 08-03-SUMMARY.md) preserving D-06/D-19 replay-fail-fast despite `build_live_system` injecting the live policy; the paper-parity gate test (`test_paper_parity.py`, 1 passed per orchestrator gate) proves this holds. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| CF-1 SETTLEMENT halt-on-first (unit level, fake halt/bus) | `pytest tests/unit/events/test_error_policy.py::test_settlement_trips_on_first` | 1 passed | ✓ PASS |
| CF-1 SETTLEMENT halt-on-first (live end-to-end, real EventHandler graph) | `pytest tests/unit/events/test_error_flow.py::test_live_fill_route_failure_trips_halt_and_keeps_draining` | 1 passed | ✓ PASS |
| ERR-04 funnel (CRITICAL + PortfolioErrorEvent both reach ErrorHandler.on_error) | `pytest tests/unit/events/test_error_flow.py::test_critical_and_portfolio_error_events_both_funnel_to_error_handler` | 1 passed | ✓ PASS |
| Composition root wires LogAlertSink into ErrorHandler | `pytest tests/unit/execution/test_drift_halt_policy.py::test_composition_root_wires_a_log_alert_sink` | 1 passed | ✓ PASS |
| Oracle byte-exact + OKX inertness (independent re-run) | `pytest tests/integration/test_okx_inertness.py tests/integration/test_backtest_oracle.py` | 7 passed | ✓ PASS |
| Grep gates (deleted symbols / relocation) | `grep -nE "_on_handler_error\|_log_error_event\|_alert_sink\|_AlertSinkLike" full_event_handler.py`; `grep _alert_sink\|_on_handler_error live_trading_system.py`; `grep error_policy live_runner.py`; `grep -r trading_system.error_policy itrader tests` | all 0 hits | ✓ PASS |
| mypy --strict on all touched modules | `mypy error_policy.py error_handler.py compose.py full_event_handler.py live_trading_system.py live_runner.py core/enums/system.py config/safety.py` | Success, no issues found in 8 source files | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|-----------------|--------------|--------|----------|
| ERR-01 | 08-02, 08-03 | ErrorPolicy injected into EventHandler at construction, monkeypatch removed, per-handler granularity, WR-06 source guard, backtest byte-exact | ✓ SATISFIED | `full_event_handler.py` ctor injection + `_dispatch` call site; `start()` monkeypatch confirmed removed; oracle byte-exact re-run. |
| ERR-02 | 08-02, 08-03 | ErrorHandler formalizes ERROR-route consumer: severity-mapped log, CRITICAL→alert-sink, persist state.last_error, WR-06 consumer guard | ✓ SATISFIED | `error_handler.py::ErrorHandler.on_error` full implementation read + tested. |
| ERR-03 | 08-01, 08-02, 08-03 | CF-1 aggregate circuit breaker actually trips (money route failing every event), WR-06 swallow preserved, backtest unchanged | ✓ SATISFIED | Unit + live e2e trip tests independently re-run and passed; `_POLICY_FIELDS` matches exact D-14 thresholds. |
| ERR-04 | 08-01, 08-02, 08-03 | One error funnel: handler failures, halt() CRITICAL, PortfolioErrorEvent, ConnectorFatalEvent all route through the ERROR route | ✓ SATISFIED | All 4 sources traced to the single `EventType.ERROR` route; funnel test re-run and passed. |

**Note (documentation lag, non-blocking):** `.planning/REQUIREMENTS.md` still shows ERR-01..04 as `[ ]` / "Pending" and `.planning/STATE.md` still shows "Plan 1 of 3" / phase 08 "EXECUTING" — these are orchestrator-owned bookkeeping files that were correctly left untouched by the execution plans (each SUMMARY.md explicitly notes "STATE.md / ROADMAP.md NOT modified — orchestrator owns those") and are expected to be synced as part of phase-completion bookkeeping following this verification, not a code gap.

### Anti-Patterns Found

None. Scanned all 11 phase-touched source files (`core/enums/system.py`, `core/enums/__init__.py`, `config/safety.py`, `config/__init__.py`, `execution_handler/exchanges/okx.py`, `events_handler/error_policy.py`, `events_handler/error_handler.py`, `trading_system/compose.py`, `events_handler/full_event_handler.py`, `trading_system/live_trading_system.py`, `trading_system/live_runner.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented" — zero hits.

### Human Verification Required

None. All must-haves are code-verifiable (no visual/UX/external-service surface in this phase).

### Gaps Summary

None. All 4 roadmap success criteria, all 3 PLAN frontmatter `must_haves.truths` blocks (08-01/08-02/08-03), and all 4 requirement IDs (ERR-01..04) are verified against the actual codebase — not just SUMMARY.md claims. Independently re-ran the oracle, OKX-inertness, CF-1 trip (unit + live e2e), ERR-04 funnel, and composition-root alert-sink tests outside the orchestrator's pre-run gates; all passed. mypy --strict clean on every touched module. All grep-based deletion/relocation gates (monkeypatch removal, `_on_handler_error`/`_log_error_event`/`_alert_sink`/`_AlertSinkLike` deletion, `trading_system/error_policy.py` relocation) independently confirmed clean.

---

_Verified: 2026-07-15_
_Verifier: Claude (gsd-verifier)_
