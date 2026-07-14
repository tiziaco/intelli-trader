---
phase: 08-error-subsystem
plan: 03
subsystem: error-subsystem
tags: [compose, event-handler, injection, tripwire, wr-06, live-wiring, get-status]
requires:
  - "08-01: FailureClass enum, HaltReason +4, FailureRateSettings, okx counted ErrorEvent"
  - "08-02: relocated ErrorPolicy (+ FailFastPolicy/HandlerErrorPolicy/should_trip/classify_failure/record_failure/bind), new ErrorHandler"
provides:
  - "EventHandler constructor-injected with error_policy (HandlerErrorPolicy) + error_handler (ErrorHandler); _on_handler_error/_log_error_event/_alert_sink/_AlertSinkLike deleted; ERROR route = [error_handler.on_error]"
  - "compose_engine builds ErrorHandler + selects policy (FailFastPolicy default) via new Optional[Any] alert_sink/system_store/error_policy kwargs (inert)"
  - "build_live_system mints LogAlertSink + gated SystemStore(system_db_backend) + live ErrorPolicy before compose; late-binds error_policy.bind(halt=safety.halt, error_counter); monkeypatch/alert-set/old-build removed; LiveRunner error_policy param removed"
  - "ErrorPolicy.breaker_snapshot() + _last_trip; surfaced via get_status()['breaker'] None-safely (D-13)"
  - "ERR-03 end-to-end trip test + ERR-04 funnel test (live FILL failure halts-on-first while draining continues, WR-06 swallow)"
affects:
  - "P9 (RTCFG-06): breaker counters + state.* into SystemStore stats.snapshot read-model (deferred)"
  - "drift verification must EXCLUDE compose_engine new kwargs + EventHandler injected ctor + breaker_snapshot as intentional surface"
tech-stack:
  added: []
  patterns:
    - "results_store Optional-kwarg precedent reused for alert_sink/system_store/error_policy (Optional[Any], inert)"
    - "HaltRecordStore None-gate mirrored for the gated SystemStore mint over the shared SqlEngine (D-05 NEGATIVE)"
    - "ErrorPolicy.bind late-wire resolves the event_handler<-policy<-safety construction cycle (D-12)"
key-files:
  created: []
  modified:
    - itrader/events_handler/full_event_handler.py
    - itrader/trading_system/compose.py
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/live_runner.py
    - itrader/events_handler/error_policy.py
    - tests/unit/events/test_error_flow.py
    - tests/unit/execution/test_drift_halt_policy.py
    - tests/unit/execution/test_supervisor_catchall.py
    - tests/unit/execution/test_reconnect_resilience.py
    - tests/unit/trading_system/test_live_runner_stats.py
    - tests/support/replay_harness.py
    - tests/integration/test_okx_inertness.py
    - tests/unit/events/test_dispatch_registry.py
    - tests/unit/events/test_universe_update_event.py
    - tests/unit/events/test_universe_events.py
    - tests/integration/test_event_wiring.py
    - tests/integration/test_live_bar_feed_route_order.py
decisions:
  - "replay parity gate keeps fail-fast by overriding the injected policy back to FailFastPolicy in build_paper_replay_system (D-06 replay=fail-fast honored despite build_live_system injecting the live ErrorPolicy) — the old start()-only mechanism is gone"
  - "breaker_snapshot() records _last_trip on the should_trip True edge regardless of whether halt is wired (the windowed threshold reach IS the trip)"
  - "get_status()['breaker'] read None-safely so a facade built outside build_live_system does not crash"
metrics:
  duration: ~55m
  completed: 2026-07-15
status: complete
---

# Phase 8 Plan 03: Error-subsystem wiring pass (injected policy + consumer + live tripwire) Summary

The Wave-3 wiring pass that made the injected handler-failure policy, the formalized `ErrorHandler`
consumer, and the CF-1 tripwire LIVE — threading them through the single mode-agnostic
`compose_engine` (D-04), converting `EventHandler` to constructor injection (D-01/D-03/D-06), and
wiring `build_live_system`'s live collaborators (LogAlertSink + a freshly-minted SystemStore over the
shared SqlEngine + the live ErrorPolicy with `safety.halt` late-bound). The backtest fail-fast path is
byte-for-byte unchanged (oracle 134 / 46189.87730727451) and `test_okx_inertness` stays green.

## What Was Built

### Task 1 — EventHandler constructor injection + compose build site (`full_event_handler.py` TABS, `compose.py` TABS) — commit `61b420dd`
- `EventHandler.__init__` gained `error_policy: HandlerErrorPolicy` + `error_handler: ErrorHandler`
  params (stored on `self._error_policy` / `self.error_handler`). Deleted the `_on_handler_error` method,
  the `_log_error_event` method, the `_alert_sink` attribute, and the `_AlertSinkLike` Protocol (D-01/D-03/D-06).
  `_dispatch`'s except-block now calls `self._error_policy.on_handler_error(event, handler)`; the ERROR
  route is `EventType.ERROR: [self.error_handler.on_error]`. Swept the now-unused imports (`ErrorSeverity`,
  `Protocol`, the TYPE_CHECKING `ErrorEvent`); added TYPE_CHECKING refs for `HandlerErrorPolicy`/`ErrorHandler`.
- `compose_engine` gained three `Optional[Any]` kwargs (`alert_sink`, `system_store`, `error_policy`,
  mirroring the `results_store` precedent) — typed `Optional[Any]` so NO `SystemStore`/`LogAlertSink`
  concrete lands on the backtest import graph. At the EventHandler build site it builds
  `ErrorHandler(alert_sink=…, system_store=…, failure_sink=error_policy)` and selects
  `policy = error_policy if error_policy is not None else FailFastPolicy()` (both pure module-top imports),
  passing both into `EventHandler(...)`.

### Task 2 — build_live_system live wiring + SystemStore mint + late-bind halt + breaker get_status (`live_trading_system.py` 4-SPACE, `live_runner.py` 4-SPACE, `error_policy.py` 4-SPACE) — commit `579f13b9`
- BEFORE the `compose_engine` call, build the live collaborators: `alert_sink = LogAlertSink()`;
  a gated `SystemStore(system_db_backend)` minted under the same `system_db_backend is not None` gate
  as `HaltRecordStore` (D-05 NEGATIVE — no existing SystemStore, no second SqlEngine; import lazy inside
  the gate); and `error_policy = ErrorPolicy(global_queue, failure_settings=_system_config.safety.failure_rate)`.
  All three passed into `compose_engine`.
- Deleted the `event_handler._alert_sink = LogAlertSink()` post-build set and the old
  `ErrorPolicy(global_queue, error_counter=…)` construction. After `safety` + `facade` exist, late-bind
  `error_policy.bind(halt=safety.halt, error_counter=facade._increment_error_count)` (D-12).
- Deleted the `start()` monkeypatch; kept `facade._error_policy = error_policy`.
- `ErrorPolicy` gained `breaker_snapshot()` (per-FailureClass in-window hit counts + last-trip HaltReason
  wire string) + a `_last_trip` field set on the `should_trip` True edge (D-13). `get_status()` surfaces it
  as `['breaker']`, read None-safely.
- `live_runner.py`: removed the dead `error_policy` constructor param, the `self._error_policy` field, the
  `ErrorPolicy` import, and the monkeypatch-referencing docstring lines. Dropped the `error_policy=` arg from
  the `LiveRunner(...)` call site and from `test_live_runner_stats.py`.

### Task 3 — retarget 4 existing tests to the injected shape + ERR-03/04 e2e (`tests/unit/events` + `tests/unit/execution`) — commit `d469b108`
- `test_error_flow.py`: the `wiring` fixture now injects `FailFastPolicy()` + `ErrorHandler()` (9 args);
  the log-consumer assertions target `error_handler.logger`; the fail-fast test still propagates
  (`_SentinelError`). Added **ERR-03** (`test_live_fill_route_failure_trips_halt_and_keeps_draining` — a FILL
  handler failing every event drives the injected fake `halt` on the first failure via
  `error_policy.bind(halt=…)`, `process_events` keeps draining, NO exception escapes, breaker snapshot records
  the trip) and **ERR-04** (`test_critical_and_portfolio_error_events_both_funnel_to_error_handler` — a CRITICAL
  ErrorEvent + a PortfolioErrorEvent both reach `ErrorHandler.on_error`; only CRITICAL escalates to the sink).
- `test_drift_halt_policy.py` / `test_supervisor_catchall.py` / `test_reconnect_resilience.py`: alert-sink
  wired through `event_handler.error_handler._alert_sink`; the composition-root assertion now checks
  `system.event_handler.error_handler._alert_sink`; the removed `_on_handler_error` monkeypatch dropped (the
  live policy is injected at construction now).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] test_okx_inertness EventHandler ctor updated to injected shape**
- **Found during:** Task 1
- **Issue:** `test_backtest_event_handler_phase7_routes_are_inert_empty` constructs `EventHandler` directly with the old 7-arg shape → `TypeError` after the signature change; `test_okx_inertness` is a hard milestone gate.
- **Fix:** Added `error_policy=MagicMock(), error_handler=MagicMock()` to the construction (route-only test).
- **Files modified:** tests/integration/test_okx_inertness.py
- **Commit:** 61b420dd

**2. [Rule 2 - Critical safety] Preserve replay=fail-fast in the paper-replay fixture**
- **Found during:** Task 2
- **Issue:** The replay parity gate (`TestRunner`) drives `process_events()` directly and NEVER calls `start()`; it relied on the old start()-only monkeypatch to STAY fail-fast (documented load-bearing "can't false-green" invariant, D-19). Moving policy injection to construction makes `build_live_system` inject the live publish-and-continue ErrorPolicy into the paper-replay system too — silently converting the parity gate to publish-and-continue and contradicting D-06 ("backtest/**replay** inject a FailFastPolicy"). The plan's `files_modified` did not list the replay harness.
- **Fix:** `build_paper_replay_system` now overrides the injected policy back to a `FailFastPolicy()` after build (`system.event_handler._error_policy = FailFastPolicy()`), honoring D-06's replay=fail-fast and keeping the parity gate honest. Production live keeps publish-and-continue.
- **Files modified:** tests/support/replay_harness.py
- **Commit:** 579f13b9

**3. [Rule 3 - Blocking] 5 additional EventHandler-caller test files updated**
- **Found during:** post-Task-3 full-suite run
- **Issue:** `test_dispatch_registry.py`, `test_event_wiring.py`, `test_universe_update_event.py`, `test_universe_events.py`, `test_live_bar_feed_route_order.py` also construct `EventHandler` with the old 7-arg shape → `TypeError` / route errors.
- **Fix:** Passed injected `error_policy` + `error_handler` (MagicMock for the mock-style files; `SimpleNamespace` stubs with `on_handler_error`/`on_error` for the SimpleNamespace-style feed test). All are route/dispatch-only tests that never exercise the error path.
- **Files modified:** tests/unit/events/test_dispatch_registry.py, tests/integration/test_event_wiring.py, tests/unit/events/test_universe_update_event.py, tests/unit/events/test_universe_events.py, tests/integration/test_live_bar_feed_route_order.py
- **Commit:** 03bc6ec7

**Note (not a deviation):** `error_policy.py` was modified (`breaker_snapshot()` + `_last_trip`) even though it
is not in the plan frontmatter `files_modified` list — Task 2's action explicitly directed adding the
read-only breaker-snapshot method on `ErrorPolicy` (D-13), so this is planned scope.

## Threat Mitigations Applied
- **T-08-02 (DoS, ERROR-route error→error livelock):** WR-06 two guards survive the wiring byte-for-byte — the source guard in `ErrorPolicy.on_handler_error` (no republish/count of an ERROR-typed failing event) and the consumer guard in `ErrorHandler.on_error` (whole body wrapped + swallowed). The ERR-03 e2e test asserts `process_events` continues + no escape while the tripwire halts, and the queue fully drains (no republished ErrorEvent circulates).
- **T-08-03 (Tampering, tripwire wired inert):** `error_policy.bind(halt=safety.halt)` is late-bound after `SafetyController` exists; the ERR-03 test proves a live FILL route trips `safety.halt` (fake) on the FIRST failure (SETTLEMENT halt-on-first).
- **T-08-06 (Tampering, inertness/oracle):** the new compose kwargs are `Optional[Any]`; the `SystemStore` import stays lazy inside the None-gate; no second SqlEngine (D-05). `test_okx_inertness` + the byte-exact oracle both pass.
- **T-08-01 (Info Disclosure):** collaborators typed `Optional[Any]`; no secret-bearing concrete on the log path; the retargeted no-secret-substring tests still pass.

## Verification
All PYTHONPATH-prefixed (`.venv` editable-install shadow guard):
- `tests/integration/test_backtest_oracle.py` — **3 passed**, byte-exact `134 / 46189.87730727451` (check_exact=True, determinism double-run identical). The per-PLAN oracle gate held (compose + full_event_handler on the backtest path pass FailFastPolicy + ErrorHandler(None,None,None), `_dispatch` control-flow byte-identical).
- `tests/integration/test_okx_inertness.py` — **4 passed** (compose imports FailFastPolicy/ErrorHandler but no SystemStore/ccxt/sql; SystemStore lazy inside the live gate).
- `tests/unit/events tests/unit/execution tests/unit/trading_system` — green (retargeted tests + ERR-03/04 e2e).
- `tests/integration/test_paper_parity.py` — **1 passed** (replay fail-fast preserved via the fixture override).
- **Full suite** `poetry run pytest tests` — **2248 passed, 6 skipped** (skips are OKX-credential-gated live/e2e suites, expected).
- `poetry run mypy itrader` — **clean (236 source files)**; touched modules (compose, full_event_handler, error_policy, error_handler, live_trading_system, live_runner) all clean.
- grep gates all CLEAN: `_on_handler_error|_log_error_event|_alert_sink|_AlertSinkLike` empty in full_event_handler.py; `_on_handler_error`/`_alert_sink` empty in live_trading_system.py; `error_policy` empty in live_runner.py; `_on_handler_error|_log_error_event|event_handler._alert_sink` empty across the 4 retargeted test modules.

## Known Stubs
None — the injection is fully wired end-to-end; `alert_sink`/`system_store`/`halt`/`error_counter`/`failure_sink` are the intended DI seams, all live-bound in `build_live_system` and None-defaulted (log-only) on the backtest path.

## Self-Check: PASSED
- 08-03-SUMMARY.md present on disk.
- All 4 task commits (61b420dd, 579f13b9, d469b108, 03bc6ec7) present in git history.
- All 5 key modified source files present on disk.
- STATE.md / ROADMAP.md NOT modified (orchestrator owns those in worktree mode).
