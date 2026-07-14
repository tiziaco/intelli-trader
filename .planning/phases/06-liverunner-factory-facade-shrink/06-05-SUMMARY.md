---
phase: 06-liverunner-factory-facade-shrink
plan: 05
subsystem: trading_system
status: complete
tags: [RUN-05, RUN-04, session-initializer, route-registrar, live, D-10, D-11, D-12, D-23]
requires:
  - "06-01: wire_universe(engine) — the shared RUN-04 universe-injection unit"
  - "06-03: register_strategy_warmup(feed, strategies) — the RUN-07/D-17 warmup seam"
  - "06-04: UniverseHandler(*, bus, universe, feed, config) + set_venue_metadata (RUN-06/D-11)"
provides:
  - "LiveRouteRegistrar (route_registrar.py) — the central declarative BUSINESS/live route table; install(event_handler)"
  - "SessionInitializer (session_initializer.py) — the D-12 live session-wiring class; initialize() -> UniverseHandler"
affects:
  - "live_trading_system.py::_initialize_live_session — now a thin delegator to SessionInitializer"
  - "06-06: build_live_system will construct SessionInitializer at construction time over the real compose_engine Engine (the D-12 FLIP)"
tech-stack:
  added: []
  patterns:
    - "Central declarative route table (LR-16): one greppable install() mirroring the single _routes literal, list order = execution order"
    - "Has-a collaborator over the shared phase seams (SessionInitializer composes wire_universe + register_strategy_warmup + UniverseHandler + LiveRouteRegistrar)"
    - "Interim-callback for a P7-owned gate (freeze_gate wired to facade _is_halted/_is_submission_paused, repointed to SafetyController in P7)"
    - "TYPE_CHECKING forward-refs + lazy in-method imports keep the new trading_system modules import-inert"
key-files:
  created:
    - itrader/trading_system/route_registrar.py
    - itrader/trading_system/session_initializer.py
  modified:
    - itrader/trading_system/live_trading_system.py
decisions:
  - "D-10/D-23: LiveRouteRegistrar registers the BUSINESS/live set ONLY (UNIVERSE_POLL/UNIVERSE_UPDATE/STRATEGY_COMMAND/BARS_LOADED/BARS_LOAD_FAILED SET, FILL appended); NO CONTROL route (STREAM_STATE/CONNECTOR_FATAL/CONFIG_UPDATE named only in the plan, absent from the file — grep==0)"
  - "D-11: set_venue_metadata is now UNCONDITIONAL over the uniformly-resolved venue exchange (okx when present, else the paper 'simulated' exchange) — zero OKX coupling; the None-guard is purely defensive"
  - "D-12 interim: SessionInitializer is invoked via the existing _initialize_live_session delegation (still at start()/run_paper_replay); the construction-time FLIP lands in 06-06"
  - "Interim Engine holder: the facade assembles a compose Engine from its handlers with inert BacktestClock()/TimeGenerator() placeholders (never read by wire_universe/SessionInitializer); 06-06's build_live_system replaces it with the real compose_engine Engine"
metrics:
  duration: "~9 min"
  completed: "2026-07-13"
  tasks: 3
  files: 3
---

# Phase 6 Plan 05: SessionInitializer + LiveRouteRegistrar (RUN-05 / RUN-04 live / D-12) Summary

Extracted the live session-wiring out of the `LiveTradingSystem` God object into two focused, import-inert `trading_system/` collaborators — `LiveRouteRegistrar` (the ONE central declarative BUSINESS/live route table) and `SessionInitializer` (the D-12 class composing `wire_universe` + `register_strategy_warmup` + the first-class `UniverseHandler` + `LiveRouteRegistrar`) — and collapsed the ~175-line `_initialize_live_session` into a thin delegator. Live now GAINS the WR-03 desync assert via the shared `wire_universe`. All milestone gates held: OKX inertness green, backtest oracle byte-exact **134 / 46189.87730727451**, paper-parity green continuously, `mypy --strict` clean, full suite 2125 passed.

## What Was Built

### Task 1 — `LiveRouteRegistrar` (`route_registrar.py`, 4-SPACE)
The live analog of the single `EventHandler._routes` literal (list order IS execution order). `install(event_handler)` SETs `UNIVERSE_POLL` (`on_poll`), `UNIVERSE_UPDATE` (`on_universe_update`), `STRATEGY_COMMAND` (`on_strategy_command`), `BARS_LOADED` (`[strategies.on_bars_loaded, universe.on_bars_loaded]` — strategies FIRST, D-03b), `BARS_LOAD_FAILED` (`on_bars_load_failed`), and APPENDs `universe.on_fill` to the existing base `FILL` list (portfolio → order → universe). No subclass, no runtime mutation (LR-16). Registers **NO CONTROL route** — the CONTROL-plane routes stay OUT until their P7/P9 consumers land (D-23); the three member names never appear in the file (`grep -c "STREAM_STATE\|CONNECTOR_FATAL\|CONFIG_UPDATE"` = 0).

### Task 2 — `SessionInitializer` (`session_initializer.py`, 4-SPACE)
The D-12 live session-wiring class. `initialize()` runs, in exact donor order: (1) `wire_universe(engine)` (RUN-04 shared helper — live GAINS the WR-03 desync assert); (2) `register_strategy_warmup(engine.feed, strategies)` (RUN-07/D-17 — replaces the inline `_LiveWarmupConsumer`; safe AFTER `feed.bind` per RESEARCH Landmine 3); (3) the live-only subscription/membership mismatch guard (transplanted verbatim); (4) build the first-class `UniverseHandler(bus, universe, feed, config)` + wire the D-11 seams — `set_selection_source` (strategy-derived), `set_venue_metadata` UNCONDITIONAL over the resolved venue exchange, `set_provider` (guarded), `set_portfolio_read_model`, `set_strategy_warmth`, `set_freeze_gate` (interim callable); (5) `LiveRouteRegistrar(strategies_handler, universe_handler).install(engine.event_handler)`. Returns the built `UniverseHandler`. The live-only concretions (`StrategyDerivedSelectionModel`, `UniverseHandler`) are lazy-imported inside the method; the module stays import-inert.

### Task 3 — `_initialize_live_session` delegation (`live_trading_system.py`, 4-SPACE)
Replaced the inline wiring body with: assemble the interim compose `Engine` holder from the facade's handlers (inert `BacktestClock()`/`TimeGenerator()` placeholders), resolve the venue exchange (`_okx_exchange` else `'simulated'`), build `UniverseHandlerConfig`, then `SessionInitializer(...).initialize()`; hold `self._universe_handler` + mirror `self.universe = engine.universe`. Kept the `try/except → SystemStatus.ERROR` wrapper. Deleted the `_LiveWarmupConsumer` dataclass and the inline `event_handler.routes[...]` mutation. Trimmed now-unused imports (`dataclass`, `derive_membership`, `derive_instruments`). D-04 method bodies (`halt`/`pause`/`_dispatch_live`/`_is_halted`/reconcile/stream) untouched. Call sites unchanged (`start()`, `run_paper_replay()`).

## Milestone Gate Results (recorded per critical_gate)

- **OKX import-inertness:** `tests/integration/test_okx_inertness.py` — **3 passed** (green). The new `route_registrar.py` / `session_initializer.py` + the facade delegation pull no `ccxt.pro`/async/SQL onto the backtest graph (TYPE_CHECKING forward-refs + lazy in-method imports).
- **Backtest oracle byte-exact:** `tests/integration/test_backtest_oracle.py` — **3 passed**, byte-exact **134 / 46189.87730727451** (live session-wiring is live-only; backtest constructs no SessionInitializer/registrar — trivially inert).
- **Paper-parity:** `tests/integration/test_paper_parity.py` — **1 passed** (green CONTINUOUSLY through the delegation — pure behavior-preserving code-motion; confirms the wire_universe reorder + warmup-after-bind order + unconditional set_venue_metadata do not perturb the paper path).
- **mypy --strict:** clean, `Success: no issues found in 250 source files`.
- **Full suite:** `poetry run pytest tests` — **2125 passed, 6 skipped** (the 6 skips are OKX-demo-credential-gated live/e2e suites, expected without demo creds); `filterwarnings=["error"]` green.
- **Zero new dependencies** — no poetry change.
- **Indentation:** all three files 4-SPACE (no tabs — `grep -Pn "^\t"` empty on the new files; `live_trading_system.py` is 4-space, matched).

## Grep / Structural Acceptance

- Task 1: `LiveRouteRegistrar.install` present; CONTROL literals = 0; BUSINESS-route mentions = 13 (>= 5); `routes[EventType.FILL].append` = 1.
- Task 2: `wire_universe|register_strategy_warmup` = 9 (>= 2); `Universe(members=` = 0; `LiveRouteRegistrar` = 4 (>= 1); `set_freeze_gate` = 2 (>= 1); inertness green.
- Task 3: `SessionInitializer` = 7 (>= 1); `_LiveWarmupConsumer` = 0; `routes[EventType.UNIVERSE_POLL]` mutation = 0; D-04 body defs (`_dispatch_live`/`_is_halted`/`halt`) = 3 (unchanged).

## Deviations from Plan

None affecting scope or behavior. Two minor in-scope decisions handled inline:

**1. [Rule 3 - Blocking] `bus` type bridge in SessionInitializer**
- **Found during:** Task 2 (mypy --strict).
- **Issue:** The compose `Engine.global_queue` is typed `EventBus` but `UniverseHandler.__init__` expects `bus: Queue[Any]` (the live facade threads a raw `queue.Queue`). mypy flagged the incompatible arg-type.
- **Fix:** `bus=cast(Any, engine.global_queue)` with a comment noting 06-06's EventBus-native wiring supersedes the interim bridge. Mirrors the documented interim `cast("LiveBarFeed", engine.feed)` (the Engine holder types `feed` as `BacktestBarFeed`; the live path threads a `LiveBarFeed`).
- **Committed in:** `35d8bfa4` (Task 2).

**2. [Rule 3 - Scope-boundary] stale `_LiveWarmupConsumer` comment reference**
- **Found during:** Task 3 (acceptance grep — `_LiveWarmupConsumer` returned 1, in a `run_paper_replay` descriptive comment).
- **Fix:** Reworded the comment to describe the new delegation (`wire_universe` + `register_strategy_warmup`), dropping the deleted symbol's name — acceptance grep now 0.
- **Committed in:** `063e64df` (Task 3).

## Task Commits

1. **Task 1: LiveRouteRegistrar** — `5bdbb73e` (feat)
2. **Task 2: SessionInitializer** — `35d8bfa4` (feat)
3. **Task 3: _initialize_live_session delegation + removals** — `063e64df` (refactor)

## Known Stubs

None.

## Threat Flags

None — internal-only session-wiring extraction; no new external input / network / trust boundary. The threat register's mitigations held: T-06-10 (route-ordering drift) — LiveRouteRegistrar preserves the exact donor list order + FILL-append, paper-parity green; T-06-11 (warmup order inversion) — warmup registered AFTER feed.bind per RESEARCH Landmine 3, paper-parity green; T-06-12 (freeze-gate predicate) — interim `lambda: _is_halted() or _is_submission_paused()` transplanted verbatim; T-06-SC — zero new dependencies.

## Notes for Downstream (06-06)

- `SessionInitializer(engine, *, universe_config, venue_exchange, data_provider, freeze_gate)` is ready for the D-12 construction-time FLIP: `build_live_system` will call `compose_engine` (a real `Engine` with real clock/time_generator), construct `SessionInitializer` at construction time, drop the interim Engine-holder assembly + the two interim `cast`s, and remove the `_initialize_live_session` delegation from `start()`/`run_paper_replay`.
- `LiveRouteRegistrar` is the ONE home P7/P9 extend with the CONTROL routes (STREAM_STATE/CONNECTOR_FATAL/CONFIG_UPDATE) when their consumers land — construction-time declaration, never runtime mutation (D-23/LR-16).

## Self-Check: PASSED

- FOUND: `itrader/trading_system/route_registrar.py`
- FOUND: `itrader/trading_system/session_initializer.py`
- FOUND: `itrader/trading_system/live_trading_system.py` (modified — delegation in place)
- FOUND commit `5bdbb73e` (Task 1)
- FOUND commit `35d8bfa4` (Task 2)
- FOUND commit `063e64df` (Task 3)
