---
phase: 02-event-bus
plan: 03
subsystem: infra
tags: [event-bus, engine-context, compose-seam, dependency-injection, mypy-strict, oracle-gate]

# Dependency graph
requires:
  - phase: 02-01
    provides: EventBus Protocol + FifoEventBus/PriorityEventBus substrate + 3 CONTROL EventType members
  - phase: 02-02
    provides: handler-owned storage seams (OrderHandler.storage, StrategiesHandler.signal_store)
provides:
  - Frozen EngineContext dataclass (bus/config/environment/sql_engine, loose types)
  - Two-arg compose_engine(ctx, spec) end-state signature (internal queue.Queue() deleted)
  - Both backtest arms (legacy __init__ + build_backtest_system factory) folded to (ctx, spec) with EngineContext(FifoEventBus, backtest, sql_engine=None)
  - global_queue retyped to EventBus across 5 handlers + SimulatedExchange + BacktestBarFeed.bind (retype-not-rename)
  - Extended register-vs-build inertness gate
affects: [P3, P4, P6, P7, P9, live-system-refactor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EngineContext infra bundle: ctx (infra) + spec (declarative WHAT) two-object split at the compose seam"
    - "Retype-not-rename DI: global_queue param retyped to EventBus Protocol, name preserved, no call-site churn"
    - "Handler-owned storage read-back: compose reads order_handler.storage / strategies_handler.signal_store off the constructed handlers"

key-files:
  created:
    - itrader/trading_system/engine_context.py
  modified:
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/events_handler/full_event_handler.py
    - itrader/order_handler/order_handler.py
    - itrader/strategy_handler/strategies_handler.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/execution_handler/execution_handler.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/price_handler/feed/bar_feed.py
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "D-01/CTX-01: compose_engine(ctx, spec) two-arg end-state signature; internal queue.Queue() deleted, ctx.bus owns transport"
  - "D-05/BUS-04: EngineContext = exactly 4 fields (bus/config/environment/sql_engine), loose types only tightened downstream, never widened/added"
  - "D-04/A1: compose reads only {data,start,end,timeframe,exchange,results_store}; order_config stays handler-owned via OrderConfig.default()"
  - "D-06: both backtest arms build EngineContext(FifoEventBus, backtest, sql_engine=None); legacy arm synthesizes placeholder SystemSpec (Pitfall 1)"
  - "D-07/D-08: retype-not-rename — global_queue param retyped to EventBus, name unchanged, no .put()/.get_nowait() call-site changes"
  - "D-11: live_trading_system.py unchanged (checkable non-diff)"

patterns-established:
  - "Infra/declarative split: EngineContext carries infra, SystemSpec carries the run description; the seam reads only A1-permitted spec fields"
  - "EventBus Protocol propagation: any strict-typed component receiving global_queue retypes to EventBus (only uses .put()); Protocol satisfied structurally"

requirements-completed: [BUS-01, BUS-04, CTX-01, CTX-03]

coverage:
  - id: D1
    description: "Frozen EngineContext dataclass with exactly 4 loose-typed fields (bus/config/environment/sql_engine)"
    requirement: "BUS-04"
    verification:
      - kind: unit
        ref: "poetry run python -c 'fields(EngineContext) == [bus,config,environment,sql_engine]' (Task 1 automated verify)"
        status: pass
    human_judgment: false
  - id: D2
    description: "compose_engine folded to two-arg (ctx, spec); internal queue.Queue() deleted; A1 spec-read constraint honored"
    requirement: "CTX-01"
    verification:
      - kind: unit
        ref: "inspect.signature(compose_engine) == ['ctx','spec']; grep queue.Queue()==0; grep spec.ticker/starting_cash/strategies/portfolios==0"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (byte-exact 134 / 46189.87730727451, check_exact=True)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Both backtest arms rewired to EngineContext(FifoEventBus, backtest, sql_engine=None); handler-owned storage read back"
    requirement: "CTX-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (oracle byte-exact, determinism double-run identical); grep compose_engine(ctx==2"
        status: pass
    human_judgment: false
  - id: D4
    description: "Register-vs-build inertness gate extended: FifoEventBus + EngineContext(sql_engine=None) pull no sqlalchemy/ccxt; sql stays unresolved"
    requirement: "CTX-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (register-vs-build assertion)"
        status: pass
    human_judgment: false
  - id: D5
    description: "global_queue retyped to EventBus across handlers + exchange + feed (retype-not-rename); mypy --strict clean"
    requirement: "BUS-01"
    verification:
      - kind: unit
        ref: "poetry run mypy itrader (237 source files, Success: no issues found)"
        status: pass
    human_judgment: false

# Metrics
duration: 18min
completed: 2026-07-09
status: complete
---

# Phase 2 Plan 03: EngineContext + Compose-Seam Fold Summary

**Frozen EngineContext + two-arg compose_engine(ctx, spec) fold — internal queue.Queue() deleted, global_queue retyped to the EventBus Protocol across 7 strict-typed components, both backtest arms rewired to FifoEventBus, oracle byte-exact at 134 / 46189.87730727451.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-09 (Task 1)
- **Completed:** 2026-07-09
- **Tasks:** 3
- **Files created:** 1
- **Files modified:** 9

## Accomplishments
- Introduced the frozen `EngineContext` (exactly 4 loose-typed fields `bus`/`config`/`environment`/`sql_engine`) as the infra half of the ctx+spec compose seam.
- Folded `compose_engine` to its end-state two-arg `(ctx, spec)` signature, DELETING the internal `queue.Queue()` — `ctx.bus` now owns the transport, injected into all 6 handler ctors + the `Engine` holder.
- Retyped `global_queue` to `EventBus` (name unchanged, D-07/D-08) across 5 handlers, `SimulatedExchange`, and `BacktestBarFeed.bind` — no `.put()`/`.get_nowait()` call-site changed.
- Rewired BOTH backtest arms (the spec-LESS legacy `__init__` the oracle runs through, and the `build_backtest_system` factory) to build+inject `EngineContext(bus=FifoEventBus(), environment='backtest', sql_engine=None)` and read handler-owned storage back.
- Extended the inertness gate with a register-vs-build assertion; SMA_MACD oracle byte-exact + deterministic double-run identical; `mypy --strict` clean on all 237 source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: EngineContext dataclass + retype-not-rename bus swap** - `7c2e18bf` (feat)
2. **Task 2: Fold compose_engine to (ctx, spec) — delete internal queue** - `9e7cdf49` (feat)
3. **Task 3: Rewire both backtest call sites + extend inertness gate** - `1369a21a` (feat)

## Files Created/Modified
- `itrader/trading_system/engine_context.py` (created) - Frozen `EngineContext` infra bundle (4 loose fields), imports only stdlib + the `EventBus` Protocol.
- `itrader/trading_system/compose.py` - `compose_engine(ctx, spec)`; internal queue deleted; `ctx.bus` threaded into every handler + Engine; A1 spec fold; storage read back off handlers; `Engine.global_queue` field retyped to `EventBus`; dropped now-unused `queue`/`Path`/`OrderStorage`/`ExchangeConfig` imports.
- `itrader/trading_system/backtest_trading_system.py` - Legacy arm synthesizes a placeholder `SystemSpec` + `EngineContext`, reads signal store back off the engine; factory uses `dataclasses.replace` to seed `spec.exchange`, builds ctx, calls `compose_engine(ctx, spec)`; dropped factory storage selection + unused `OrderStorageFactory`/`SignalStorageFactory` imports.
- `itrader/events_handler/full_event_handler.py` - `global_queue` param retyped to `EventBus` (kept `import queue` for the `queue.Empty` drain catch).
- `itrader/order_handler/order_handler.py` - `global_queue` param retyped to `EventBus`.
- `itrader/strategy_handler/strategies_handler.py` - `global_queue` param + self-attr retyped to `EventBus`.
- `itrader/portfolio_handler/portfolio_handler.py` - `global_queue` param + self-attr retyped to `EventBus` (4-space file).
- `itrader/execution_handler/execution_handler.py` - `global_queue` param retyped to `EventBus`.
- `itrader/execution_handler/exchanges/simulated.py` - (Rule 3) `global_queue` param retyped to `EventBus` — only calls `.put()`.
- `itrader/price_handler/feed/bar_feed.py` - (Rule 3) `bind` param + self-attr retyped to `Optional[EventBus]`; dropped now-unused `import queue`.
- `tests/integration/test_okx_inertness.py` - Extended `_PROBE` with the register-vs-build assertion (FifoEventBus + EngineContext(sql_engine=None) pull no sqlalchemy/ccxt; `sql` stays unresolved in `config.__dict__`).

## Decisions Made
- None beyond the locked plan decisions (D-01/D-04/D-05/D-06/D-07/D-08/D-11 delivered as specified).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Retype SimulatedExchange.global_queue to EventBus**
- **Found during:** Task 2 (compose fold)
- **Issue:** `ExecutionHandler.global_queue` retyped to `EventBus` propagated into `ExecutionHandler`'s construction of `SimulatedExchange(self.global_queue, ...)`, whose param was typed `Queue[Any]` — `mypy --strict` error `arg-type` at execution_handler.py:154.
- **Fix:** Retyped `SimulatedExchange.__init__`'s `global_queue` param to `EventBus` (it only calls `.put()`, which the Protocol provides) and added the `EventBus` import.
- **Files modified:** itrader/execution_handler/exchanges/simulated.py
- **Verification:** `mypy --strict` clean on the 8-module set; oracle byte-exact.
- **Committed in:** `9e7cdf49` (Task 2 commit)

**2. [Rule 3 - Blocking] Retype BacktestBarFeed.bind global_queue to EventBus**
- **Found during:** Task 3 (both-arm rewire — surfaced by the full `mypy itrader` gate)
- **Issue:** `Engine.global_queue` is now `EventBus`; `BacktestRunner` calls `engine.feed.bind(engine.global_queue, ...)` whose param + self-attr were typed `Optional[queue.Queue[Any]]` — `mypy --strict` error `arg-type` at backtest_runner.py:113.
- **Fix:** Retyped `BacktestBarFeed.bind`'s `global_queue` param and the `self.global_queue` attr to `Optional[EventBus]` (only calls `.put()`), added the `EventBus` import, dropped the now-unused `import queue`.
- **Files modified:** itrader/price_handler/feed/bar_feed.py
- **Verification:** `poetry run mypy itrader` — Success, 237 files; oracle byte-exact; 571 unit + 228 e2e/integration tests green.
- **Committed in:** `1369a21a` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking mypy propagations)
**Impact on plan:** Both are the natural, required continuation of the retype-not-rename bus swap — any strict-typed component receiving `global_queue` had to retype to the `EventBus` Protocol for `mypy --strict` to pass. No behavior change (both only enqueue via `.put()`), no scope creep. The oracle stayed byte-exact throughout.

## Issues Encountered
- Two docstring greps initially over-counted: the acceptance-criteria greps (`queue.Queue()`, `spec.ticker|...`, `compose_engine(ctx`) matched literal strings in docstrings/comments. Reworded the docstrings to avoid the literal forms so the greps report the code-only counts (0 / 0 / 2). No functional impact.

## Gate Results
- Oracle: `tests/integration/test_backtest_oracle.py` byte-exact `134 / 46189.87730727451` (`check_exact=True`), run twice — identical (determinism).
- Inertness: `tests/integration/test_okx_inertness.py` green incl. new register-vs-build assertion.
- `poetry run mypy itrader` — Success: no issues found in 237 source files.
- Unit + e2e/integration: 571 + 228 passed (6 OKX-credential-gated skips).
- `grep -c 'queue.Queue()' compose.py` == 0; `grep -c 'compose_engine(ctx' backtest_trading_system.py` == 2.
- `git diff --exit-code live_trading_system.py` — no changes (D-11); `poetry.lock` byte-unchanged.

## Next Phase Readiness
- The compose seam is at its end-state form — P3/P4/P9 only TIGHTEN `EngineContext`'s loose types (never add fields); no re-edit of the two-arg signature required downstream.
- `PriorityEventBus` remains wired into no path (D-11) — live ordering untouched until P6/P7 + the P12 live-smoke gate.

## Self-Check: PASSED

- FOUND: itrader/trading_system/engine_context.py
- FOUND: .planning/phases/02-event-bus/02-03-SUMMARY.md
- FOUND commits: 7c2e18bf, 9e7cdf49, 1369a21a

---
*Phase: 02-event-bus*
*Completed: 2026-07-09*
