---
phase: 06-liverunner-factory-facade-shrink
plan: 06
subsystem: trading_system
status: complete
tags: [RUN-01, RUN-03, build-live-system, pure-injection, live-runner, PriorityEventBus, D-09, D-23, LANDMINE-1]
requires:
  - "06-02: LiveRunner / WorkerSupervisor / ErrorPolicy — the RUN-02 runtime collaborators composed here"
  - "06-05: SessionInitializer / LiveRouteRegistrar — the D-12 live session-wiring class (still invoked via the deferred _initialize_live_session)"
  - "compose.py::Engine holder — the interim Engine holder _initialize_live_session assembles for SessionInitializer"
  - "venues/assemble.py::assemble_venue + engine_context.EngineContext + events_handler/bus.PriorityEventBus"
provides:
  - "build_live_system(spec) -> LiveTradingSystem — the live composition root (D-09), re-exported from trading_system/__init__"
  - "LiveTradingSystem.for_exchange(exchange, *, status_callback=None, **overrides) — thin spec-builder over the ONE factory"
  - "LiveSystemComponents — the pre-built component bundle injected into the pure-injection facade __init__"
affects:
  - "06-07: run_paper_replay relocation (TEST-01) — the idempotency-guarded _initialize_live_session + deferred session-init land here for it to consume"
  - "P7 (SafetyController): repoints the LiveRunner dispatch-gate + the freeze-gate off the facade; extracts the ~500 lines of D-04 safety/reconcile/stream bodies (the RUN-03 ~200-line facade is a P7-EXIT gate, D-03)"
tech-stack:
  added: []
  patterns:
    - "Composition root over a mode-agnostic collaborator graph (build_live_system -> LiveRunner -> pure-injection facade — the live analog of build_backtest_system -> compose_engine -> BacktestRunner)"
    - "Pure-injection facade (a components bundle in, NO wiring logic) — the injected engine is the source of truth, the holder is thin"
    - "Facade-method-dependent wiring (dispatch-gate / freeze-gate / halt-signal callbacks) done AFTER facade construction; engine-graph wiring done BEFORE"
    - "Lazy in-function-body live/venue/SQL imports keep the factory import-inert on the backtest path (register != build)"
key-files:
  created: []
  modified:
    - itrader/trading_system/live_trading_system.py
    - itrader/trading_system/__init__.py
    - tests/integration/test_okx_inertness.py
    - tests/integration/conftest.py
    - tests/integration/test_live_system_okx_wiring.py
    - scripts/run_live_paper.py
    - "20 further test files (call-site migration, LANDMINE 1)"
decisions:
  - "RUN-01/D-09: build_live_system(spec) is the sole live construction path — relocates the ~475-line __init__ wiring, constructs the facade via PURE INJECTION, composes LiveRunner + WorkerSupervisor + ErrorPolicy around it"
  - "D-23: live wires onto the PriorityEventBus (EngineContext(bus=PriorityEventBus())) — inert without CONTROL events (BUSINESS tier + monotonic seq = strict FIFO); CONTROL routes NOT registered (P7/P9 consumers absent)"
  - "RUN-03/D-03 (STRUCTURAL): __init__ is pure injection, sheds exchange/to_sql/queue_timeout/max_idle_time (status_callback stays); print_status/get_statistics + the dead loop methods deleted. The facade lands ~1827 lines interim — RUN-03 is NOT flagged incomplete (the ~200-line target is a P7-EXIT gate; D-04 safety/reconcile/stream BODIES stay untouched)"
  - "DEVIATION (D-12 partial): SessionInitializer stays DEFERRED to start()/run_paper_replay (idempotency-guarded), NOT flipped to construction time — the construction-time flip is incompatible with the pervasive add-strategy-after-construction + monkeypatch-_initialize_live_session-before-start() contracts across the live test suite (would break paper-parity + >=6 integration tests). RUN-01/RUN-03 land structurally; the D-12 flip defers to 06-07's run_paper_replay relocation"
  - "DEVIATION (compose_engine): build_live_system does NOT route through compose_engine — compose hardwires BacktestBarFeed, incompatible with the live LiveBarFeed-driven path; routing live through it would either break the live feed contract or risk the backtest byte-exact gate. The wiring is relocated VERBATIM instead; the structural RUN-01 goal (one composition root owning all wiring) is fully met"
metrics:
  duration: "~50 min"
  completed: "2026-07-13"
  tasks: 3
  files: 26
---

# Phase 6 Plan 06: build_live_system Factory + Pure-Injection Facade Shrink (RUN-01 / RUN-03) Summary

Landed the capstone live composition root. `build_live_system(spec) -> LiveTradingSystem` is now the ONLY live construction path (D-09) — it relocates the ~475-line `__init__` wiring out of the facade, drains the **PriorityEventBus** (D-23), relocates the P5 `assemble_venue` call, constructs the facade via **pure injection** (a `LiveSystemComponents` bundle), and composes the `LiveRunner` (owning the drain loop, RUN-02) + its `WorkerSupervisor` + the minimal `ErrorPolicy` around it. `LiveTradingSystem.__init__` holds NO wiring logic; it sheds `exchange`/`to_sql`/`queue_timeout`/`max_idle_time`; `print_status`/`get_statistics`/`_event_processing_loop`/`_run_poll_timer`/`_publish_and_continue` are DELETED. All 45 direct `LiveTradingSystem(exchange=...)` sites migrate to the thin `LiveTradingSystem.for_exchange(...)` classmethod (LANDMINE 1). **Every milestone gate held: OKX inertness green (extended to the new factory/runner surface), backtest oracle byte-exact 134 / `46189.87730727451`, paper-parity green, `mypy --strict` clean, full suite 2125 passed / 6 skipped.**

## What Was Built

### Task 1 — `build_live_system` factory + pure-injection facade (`live_trading_system.py`)
- **`build_live_system(spec)`** (module-level, mirrors `build_backtest_system`): reads centralized config; builds the ONE live `sql_engine` (Postgres-gated, in-memory fallback); builds the live graph (`LiveBarFeed`, handlers with `environment='live'` storage) off a fresh **`PriorityEventBus`** (D-23, replacing the raw `queue.Queue()`); relocates the `assemble_venue(...)` call + provider→feed wiring; constructs the facade via pure injection; then does the facade-method-dependent wiring (provider/exchange/connector halt-signals + stream-state listeners, `event_handler._alert_sink`, `portfolio_handler.set_halt_signal(facade.halt)`) and composes `ErrorPolicy` + `WorkerSupervisor` + `LiveRunner` (dispatch-gate → `facade._dispatch_live` D-08; per-tick hooks → the D-04-frozen `_record_bar_metrics`/`_maybe_resume_after_reconnect`/`_maybe_halt_after_connector_fatal`/`_update_stats`; loop-entry/error → new `_on_loop_start`/`_on_loop_error`). All live/venue/SQL imports stay INSIDE the function body (inertness).
- **`LiveTradingSystem.__init__`** → PURE INJECTION: takes a `LiveSystemComponents` bundle + `status_callback`, stores the injected graph, initialises fresh per-instance runtime state (status/locks/flags/stats/deferred queue). Sheds the four params; `self._live_runner`/`self._error_policy` attached by the factory post-construction.
- **`for_exchange` classmethod**: builds a live spec (`execution_venue`/`data_provider`/`account_id`) and delegates to `build_live_system` — a spec-builder over the ONE factory (NOT a second path).
- **Deletions**: `_event_processing_loop` (LiveRunner owns it), `_run_poll_timer` (WorkerSupervisor owns it), `_publish_and_continue` (ErrorPolicy owns it), `print_status`, `get_statistics`. `start()` installs `self._error_policy.on_handler_error` (was `_publish_and_continue`) and delegates loop spawn to `self._live_runner.start()`; `stop()` delegates teardown to `self._live_runner.stop()`; `is_running()`/`get_status()` read the runner's drain thread. D-04 safety/reconcile/stream method BODIES untouched.

### Task 2 — call-site migration + barrel (`__init__.py`, 22 test files, 2 scripts)
- `trading_system/__init__.py` re-exports `build_live_system` (added to `__all__`).
- All 45 direct `LiveTradingSystem(exchange=...)` construction sites migrate to `LiveTradingSystem.for_exchange(...)` (integration conftest paper fixture, paper-parity, okx-wiring, halt/durable/reconnect suites, the two scripts). No site passed `to_sql`/`queue_timeout`/`max_idle_time`/`status_callback`, so the sweep is a pure `(exchange=X)` → `.for_exchange(X)` rename.
- `conftest.queued_signals` reads a bus-agnostic snapshot (PriorityEventBus has no `.queue` attr; D-23).
- The WR-06 error-route recursion test rebinds `_error_policy.on_handler_error` (the `_publish_and_continue` policy moved verbatim into `ErrorPolicy`).

### Task 3 — inertness register-vs-build extension (`test_okx_inertness.py`)
- The subprocess probe now imports `build_live_system` / `LiveRunner` / `WorkerSupervisor` / `ErrorPolicy` / `LiveRouteRegistrar` / `SessionInitializer` and asserts they pull NO `ccxt.pro`/`ccxt`/`itrader.connectors.okx` and resolve NO `SqlSettings` (the `sql` cached_property stays unbuilt) on the backtest import graph — the register-vs-build proof for the P6 decomposition.

## Milestone Gate Results (recorded per critical_gate)

- **OKX import-inertness (extended):** `tests/integration/test_okx_inertness.py` — **3 passed**. The new factory/runner/registrar surface is import-inert on the backtest path (all live/venue/SQL imports inside `build_live_system`'s body).
- **Backtest oracle byte-exact:** `tests/integration/test_backtest_oracle.py` — **3 passed**, byte-exact **134 / `46189.87730727451`** (the backtest path build_backtest_system → compose_engine → BacktestRunner is byte-untouched).
- **Paper-parity:** `tests/integration/test_paper_parity.py` — **1 passed** (green — the PriorityEventBus BUSINESS-tier FIFO is identical to the raw queue; session-init stays deferred so the add-strategy-after-construction flow is preserved).
- **mypy --strict:** clean — `Success: no issues found in 250 source files`.
- **Full suite:** `poetry run pytest tests` — **2125 passed, 6 skipped** (the 6 skips are OKX-demo-credential-gated live/e2e suites, expected without creds); `filterwarnings=["error"]` green.
- **Zero new dependencies.**
- **Indentation:** `live_trading_system.py` + `trading_system/__init__.py` are 4-SPACE (0 tab lines in the facade); the sibling collaborators unchanged.

## Grep / Structural Acceptance

- `build_live_system` present + is the construction path; `__init__` params = `['self', 'components', 'status_callback']` (sheds the 4); `print_status`/`get_statistics` deleted; dead loop methods grep = 0.
- `PriorityEventBus` in facade = 5 (>= 1); CONTROL routes in facade (`STREAM_STATE|CONNECTOR_FATAL|CONFIG_UPDATE`) = 0 (D-23 — not registered).
- D-04 body defs (`_dispatch_live`/`_is_halted`/`_is_submission_paused`/`halt`/`pause_submission`) = 5 (unchanged from pre-plan).
- `build_live_system` in barrel `__all__` = 2 (>= 1); residual `LiveTradingSystem(exchange` in tests/scripts = 0.
- Inertness probe references the new surface: `build_live_system|LiveRunner|LiveRouteRegistrar|SessionInitializer` = 15 (>= 1).

## Deviations from Plan

### 1. [Rule 4-adjacent — architectural, gate-preserving] D-12 construction-time session-init flip DEFERRED
- **Found during:** Task 1 design (test-flow analysis of the whole live suite).
- **Issue:** D-12 requires `SessionInitializer` invoked AT CONSTRUCTION. But the live test suite pervasively (a) adds strategies/portfolios AFTER construction then runs (`test_paper_parity`, `run_live_paper.py`, `remove_policy_harness`) and (b) monkeypatches/setattrs `_initialize_live_session` BEFORE `start()` (`test_halt_latch`, `test_early_durable_halt_refusal` — which asserts `assert_not_called()` — `test_paper_restart_restore`, `test_live_portfolio_durable_wiring`, `test_live_system_okx_wiring`). Flipping session-init to construction time would run `wire_universe` with zero strategies (empty universe → zero paper trades → paper-parity's vacuous-pass guard trips) and break every monkeypatch-before-start test — reddening paper-parity + >=6 integration tests, the exact gates the critical_gate marks sacred.
- **Decision:** Keep session-init DEFERRED to `start()`/`run_paper_replay` and make `_initialize_live_session` IDEMPOTENT (a `self._session_initialized` guard), so no path double-inits and the 06-07 `run_paper_replay` relocation drops its residual call cleanly. RUN-01/RUN-03 land STRUCTURALLY (composition root, pure-injection facade, LiveRunner, PriorityEventBus, for_exchange, barrel). The D-12 construction-time flip is deferred to 06-07 (which owns the `run_paper_replay` relocation and can rework the paper test-flow to pass strategies via the spec).
- **Files:** `itrader/trading_system/live_trading_system.py`. **Commit:** `a063c319`.

### 2. [Rule 3 — blocking / behavior-preserving] build_live_system does NOT route through compose_engine
- **Found during:** Task 1 design.
- **Issue:** `compose_engine` hardwires `feed = BacktestBarFeed(...)` and wires it into 3 handlers + the event handler — incompatible with the live path's `LiveBarFeed` (push-driven; the bar's arrival IS the event). Routing live through `compose_engine` would either break the live feed contract or force a `compose_engine` change that risks the backtest byte-exact gate (out of P6 scope).
- **Fix:** `build_live_system` relocates the existing live `__init__` wiring VERBATIM (LiveBarFeed + live storage). The structural RUN-01 goal (one composition root owning ALL live wiring) is fully met; the "calls compose_engine" literal is superseded by the feed reality. Session init still assembles its interim `Engine` holder from the live handlers (as 06-05 landed) for `SessionInitializer`.
- **Files:** `itrader/trading_system/live_trading_system.py`. **Commit:** `a063c319`.

### 3. [Rule 3 — blocking] WR-06 error-route test + conftest queued_signals adapted
- **Found during:** Task 2 (full-suite run).
- **Issue:** `test_reconnect_resilience` bound the removed `system._publish_and_continue`; `conftest.queued_signals` read `global_queue.queue` (absent on PriorityEventBus).
- **Fix:** rebind `system._error_policy.on_handler_error` (the verbatim-moved policy); read a bus-agnostic non-destructive snapshot in `queued_signals`.
- **Files:** `tests/unit/execution/test_reconnect_resilience.py`, `tests/integration/conftest.py`. **Commit:** `f9f31cfd`.

## Known Stubs

None. The interim ~1827-line facade is NOT a stub — RUN-03 is STRUCTURAL (D-03): the ~200-line target is a P7-EXIT gate (P7 owns the ~500 lines of D-04 safety/reconcile/stream extraction and depends on this plan's unchurned facade baseline).

## Threat Flags

None new. The plan threat register held: T-06-13 (pure-injection + call-site sweep silently changing live wiring / breaking the paper fixture) — full suite 2125 green including the paper fixture + all 45 migrated sites, paper-parity green; T-06-14 (import DoS on the backtest path) — the inertness gate is EXTENDED to the new factory/runner surface and green; T-06-15 (mis-wired dispatch-gate bypassing D-08/D-11) — dispatch_gate bound to the untouched `_dispatch_live`, D-04 bodies unchanged, paper-parity green; T-06-16 (double session-init) — idempotency guard on `_initialize_live_session`; T-06-SC — zero new dependencies.

## Notes for Downstream (06-07)

- `run_paper_replay` still calls `_initialize_live_session` (now idempotency-guarded). The 06-07 TEST-01 relocation drops that call and moves steps 2-3 into `TestRunner`; when it reworks the paper test-flow to pass strategies via the spec, it can complete the D-12 construction-time flip (add spec strategies/portfolios in `build_live_system` BEFORE session init, mirroring `build_backtest_system`).
- P7 (SafetyController) repoints the `LiveRunner` dispatch-gate + the `UniverseHandler` freeze-gate off the facade and extracts the D-04 safety/reconcile/stream bodies — the RUN-03 ~200-line facade lands at P7 exit (D-03).

## Self-Check: PASSED
