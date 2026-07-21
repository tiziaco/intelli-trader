<!-- refreshed: 2026-07-21 -->
# Architecture

**Analysis Date:** 2026-07-21

## System Overview

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  TradingSystem / LiveTradingSystem  (composition root + run loop)         │
│  `itrader/trading_system/backtest_trading_system.py`,                     │
│  `itrader/trading_system/live_trading_system.py`                          │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ wires via
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  compose_engine()  — shared, mode-agnostic component graph                │
│  `itrader/trading_system/compose.py`                                      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ builds
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                          global_queue (EventBus)                          │
│                     `itrader/events_handler/bus.py`                       │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ drained by
                                 ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  EventHandler.process_events() / ._dispatch()                             │
│  `itrader/events_handler/full_event_handler.py`                           │
│  routes EVERY event through `self.routes: dict[EventType, list[Callable]]`│
│  — LIST ORDER IS EXECUTION ORDER                                          │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │
        ┌────────────┬──────────┼───────────┬─────────────┬─────────────┐
        ▼            ▼          ▼            ▼             ▼             ▼
   TIME route     BAR route  SIGNAL route  ORDER route  FILL route   ERROR route
   screeners_     portfolio. strategies_   execution_   portfolio.   error_
   handler.       handler.   handler ->    handler.     handler.     handler.
   screen_        update_    order_        on_order ->  on_fill ->   on_error
   markets +      portfolios handler.on_   FillEvent    order_
   bar_event_     _market_   signal ->                  handler.
   source (feed)  value +    OrderEvent                 on_fill
                  execution.
                  on_market_
                  data +
                  strategies.
                  on_bar

┌───────────────────────────────────────────────────────────────────────────┐
│  Domain handlers (StrategiesHandler, OrderHandler+OrderManager,           │
│  ExecutionHandler+SimulatedExchange, PortfolioHandler+Portfolio)          │
│  — never call each other directly; each emits events back onto the queue  │
│  — cross-domain READS go through injected read-model seams instead        │
│  (`PortfolioReadModel` Protocol, `BacktestBarFeed`/`LiveBarFeed`)          │
└───────────────────────────────────────────────────────────────────────────┘
```

Live-only overlay: `LiveRouteRegistrar.install()` (`itrader/trading_system/route_registrar.py`)
SETs the empty `UNIVERSE_POLL`/`UNIVERSE_UPDATE`/`STRATEGY_COMMAND`/`BARS_LOADED`/
`BARS_LOAD_FAILED`/`STREAM_STATE`/`CONNECTOR_FATAL`(/`CONFIG_UPDATE`) route slots and
APPENDs `universe.on_fill` + `strategies.on_fill` to the base `FILL` list, once, at
live wiring time — the backtest `EventHandler.routes` literal is never mutated, so
the backtest per-tick path stays inert (`tests/integration/test_okx_inertness.py`).

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `Event` (msgspec.Struct) | Immutable event fact base; frozen, `kw_only=True`, `gc=False`; `type` is a `ClassVar[EventType]` per subclass | `itrader/events_handler/events/base.py` |
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (dict of lists, list order = execution order); delegate handler failures to injected `HandlerErrorPolicy` | `itrader/events_handler/full_event_handler.py` |
| `ErrorHandler` | The formalized `ERROR`-route consumer: severity-mapped logging, CRITICAL alert-sink escalation, `last_error` persistence | `itrader/events_handler/error_handler.py` |
| `HandlerErrorPolicy` (`FailFastPolicy` / `ErrorPolicy`) | Injected per-mode failure seam consumed by `EventHandler._dispatch`'s except-block — backtest re-raises, live publishes `ErrorEvent` and continues | `itrader/events_handler/error_policy.py` |
| `EventBus` / `PriorityEventBus` | The `global_queue` implementation (backtest FIFO / live priority variant) | `itrader/events_handler/bus.py` |
| `compose_engine` | Shared, mode-agnostic component-graph wiring seam (queue, clock, store, feed, handlers, `EventHandler`) returned as an `Engine` holder | `itrader/trading_system/compose.py` |
| `EngineContext` | Post-compose context object threading the built `Engine` + config through backtest/live wiring | `itrader/trading_system/engine_context.py` |
| `TradingSystem` | Backtest composition root; owns the golden-run wiring on top of `compose_engine` | `itrader/trading_system/backtest_trading_system.py` |
| `BacktestRunner` | Drives the synchronous fail-fast `for` loop over `TimeGenerator` | `itrader/trading_system/backtest_runner.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `LiveTradingSystem` | Live composition-root facade: `add_event` fail-closed ingress (D-10), lifecycle (`start`/`stop`/status latch), delegates run-loop ownership to `LiveRunner` | `itrader/trading_system/live_trading_system.py` |
| `build_live_system` | Live-mode factory (module-level function in `live_trading_system.py`) selecting concrete live backends (SQL/in-memory storage, connectors, safety, config router) and injecting them into `compose_engine` | `itrader/trading_system/live_trading_system.py` |
| `SessionInitializer` | Builds live-only collaborators (`StrategiesHandler`, `UniverseHandler`, etc.) consumed by `LiveRouteRegistrar` | `itrader/trading_system/session_initializer.py` |
| `LiveRouteRegistrar` | THE single declarative live/BUSINESS route table; installs live-only routes into the one shared `EventHandler.routes` dict once, never mutated again | `itrader/trading_system/route_registrar.py` |
| `LiveRunner` | Owns the live background drain loop (queue timeout / idle-warn), started/stopped by `LiveTradingSystem` | `itrader/trading_system/live_runner.py` |
| `WorkerSupervisor` | Supervises live worker thread(s)/tasks lifecycle | `itrader/trading_system/worker_supervisor.py` |
| `ConfigRouter` | Engine-thread runtime-config actuator: validate → persist → apply → push for scoped `ConfigUpdateEvent`s (RTCFG-02/D-23) | `itrader/trading_system/config_router.py` |
| `SafetyController` | Halt / pause-submission safety latch, CRITICAL alert escalation, durable halt-record persistence | `itrader/trading_system/safety/safety_controller.py` |
| `StreamRecoveryHandler` | Reconnect-resume collaborator: missed-fill catch-up + REST snapshot + all-streams-healthy gate → resume | `itrader/trading_system/safety/stream_recovery_handler.py` |
| `PreTradeThrottle` | Pre-trade rate/size throttle safety collaborator | `itrader/trading_system/safety/pre_trade_throttle.py` |
| `StrategiesHandler` | Run all strategies per bar; emit `SignalEvent`s; delegates control-plane verbs to `StrategyLifecycleManager` | `itrader/strategy_handler/strategies_handler.py` |
| `StrategyLifecycleManager` | Owns the STRATEGY_COMMAND control plane (add/enable/reconfigure/remove verbs) moved out of `StrategiesHandler` (DECOMP-01/02) | `itrader/strategy_handler/lifecycle/manager.py` |
| `StrategyCatalog` / `resolve_strategy_class` | Injected allowlist of strategy TYPES (code); the sole access-control point resolving an untrusted `strategy_type` string | `itrader/strategy_handler/registry/catalog.py` |
| `ManagedStrategies` | Roster of live strategy INSTANCES (data) | `itrader/strategy_handler/managed_strategies.py` |
| `OrderHandler` | Event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; admission/sizing; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; structurally satisfies `PortfolioReadModel` Protocol | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven, single-shared-queue architecture with a data-driven
central router (`EventHandler.routes`) and a shared, mode-agnostic composition
seam (`compose_engine`) that both the backtest and live composition roots build
their component graph from.

**Key Characteristics:**
- Queue-only cross-domain communication — handlers never call each other's methods directly; they emit events onto `global_queue`.
- Data-driven dispatch — `EventHandler.routes` is a single `dict[EventType, list[Callable]]`; list order IS execution order (D-14). No handler self-registers.
- Frozen, immutable event facts — every event subclasses `Event` (`msgspec.Struct`, `frozen=True, kw_only=True, gc=False`), NOT a dataclass (the class docstring/CLAUDE.md phrasing "frozen dataclass" is stale terminology — verified against `itrader/events_handler/events/base.py`, it is `msgspec.Struct`).
- Read-model seams instead of cross-domain reads — `PortfolioReadModel` (Protocol, `itrader/core/portfolio_read_model.py`) and `BacktestBarFeed`/`LiveBarFeed` are injected as read-models; the queue-only rule governs handlers, not read-models.
- Decimal end-to-end for money — `float()` appears only at the serialization/logging edge.
- Determinism — one seeded `random.Random` injected at wiring (`rng_seed`, default 42); an injected `BacktestClock` on the determinism seam.
- Single shared route table, two additive overlays — the backtest `EventHandler.routes` literal in `full_event_handler.py` is the base table; `LiveRouteRegistrar.install()` SETs the previously-empty live-only slots and APPENDs to `FILL`, once, at live-wiring time only. Backtest never sees the mutation.

## Layers

**Composition / run-loop layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `compose_engine` (shared seam), `TradingSystem`/`BacktestRunner` (backtest for-loop), `LiveTradingSystem`/`build_live_system`/`LiveRunner`/`SessionInitializer`/`LiveRouteRegistrar`/`WorkerSupervisor`/`ConfigRouter`/`safety/` (live), `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers (live).

**Event dispatch layer:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/` (`full_event_handler.py`, `bus.py`, `error_handler.py`, `error_policy.py`, `events/`)
- Contains: `EventHandler.process_events()`, `_dispatch()`, `ErrorHandler.on_error`, `EventBus`/`PriorityEventBus`, `FailFastPolicy`/`ErrorPolicy`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain handler layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners, universe).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`, `itrader/universe/`.
- Contains: Thin handler classes + fat managers/sub-components (e.g. `StrategyLifecycleManager`, `OrderManager`, `MatchingEngine`).
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data engine layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, `LiveBarFeed`, CCXT/OANDA/Binance/OKX providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Core layer:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Config layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `ITraderConfig` (frozen root — `rng_seed`/`timezone`/identity base params + mutable `system`/`universe`/`stream`/`feed_provider`/`safety`/`order`/`logging` sub-models + lazy `sql`), `PortfolioConfig`, `ExchangeConfig`.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`, `ConfigRouter`.

**Bootstrap layer:**
- Location: `itrader/__init__.py`
- Initialised on import: `config = ITraderConfig()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `TimeGenerator` yields a `TimeEvent` for the next bar date (`itrader/trading_system/simulation/time_generator.py`).
2. `EventHandler` dispatches TIME to `screeners_handler.screen_markets` then `bar_event_source` (`BacktestBarFeed.generate_bar_event`), producing a `BarEvent`.
3. BAR dispatches (in order): `portfolio_handler.update_portfolios_market_value` (mark-to-market) → `execution_handler.on_market_data` (resting stop/limit matching against the new bar, may emit `FillEvent`) → `strategies_handler.on_bar` (may emit `SignalEvent`).
4. SIGNAL dispatches to `order_handler.on_signal` (validate + size via `OrderManager`/`AdmissionManager`), which may emit an `OrderEvent`.
5. ORDER dispatches to `execution_handler.on_order`, which routes to the exchange (`SimulatedExchange` → `MatchingEngine`), emitting a `FillEvent`.
6. FILL dispatches to `portfolio_handler.on_fill` (positions/cash, EXECUTED only) then `order_handler.on_fill` (order-mirror reconciliation: FILLED/CANCELLED/REJECTED).
7. `BacktestRunner` (`itrader/trading_system/backtest_runner.py`) drives this loop synchronously and fail-fast — any handler exception propagates via `FailFastPolicy` and aborts the run.

### Live External-Signal Path

1. External caller invokes `LiveTradingSystem.add_event(event)` (`itrader/trading_system/live_trading_system.py`).
2. `add_event` is fail-closed/default-deny (D-10): only `SIGNAL`, `STRATEGY_COMMAND`, and `CONFIG_UPDATE` are admissible; everything else is rejected.
3. An admitted `SIGNAL` is put on `global_queue` and flows through the SAME `SIGNAL → OrderHandler.on_signal → AdmissionManager` path as the backtest flow, so validation/sizing/cash-reservation always run before any `OrderEvent` is emitted.
4. `LiveRunner` owns the background drain loop (`process_events()` on a daemon thread) started/stopped by `LiveTradingSystem`.
5. On a handler exception, the injected `ErrorPolicy` (not `FailFastPolicy`) emits an `ErrorEvent` and the loop keeps draining (publish-and-continue).

### Live Control-Plane Path (BUS-03)

1. A connector's asyncio loop puts a `StreamStateEvent` or `ConnectorFatalEvent` on the bus (never touches engine state directly).
2. `LiveRouteRegistrar`-installed routes actuate on the engine thread: `STREAM_STATE(up)` → `StreamRecoveryHandler.on_reconnect`; `STREAM_STATE(down)` → `SafetyController.pause_submission`; `CONNECTOR_FATAL` → `SafetyController.halt(reason)`.
3. A scoped `ConfigUpdateEvent` (RTCFG-02/D-23) is actuated via the injected `ConfigRouter.apply(event)` (validate → persist → apply → push), only when a durable store/router exists; otherwise the route is a pre-declared no-op empty slot.

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`, selected via `OrderStorageFactory`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Strategy control-plane state: `ManagedStrategies` roster + `StrategyLifecycleManager` (pending removals, etc.).
- Live run status: `LiveTradingSystem._status_lock` + `threading.Event`, `HaltRecordStore` for durable halt state.

## Key Abstractions

**Event:**
- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — split by domain: `base.py`, `market.py`, `portfolio.py`, `screener.py`, `universe.py`, `signal.py`, `strategy.py`, `order.py`, `fill.py`, `feed.py`, `error.py`, `control.py`.
- Pattern: `class X(Event, ...)` where `Event` is `msgspec.Struct(frozen=True, kw_only=True, gc=False)` (NOT a `@dataclass` — verified in `base.py`); `type: ClassVar[EventType] = EventType.X` pinned per subclass; `event_id` auto-generated UUIDv7 via `uuid_utils.compat.uuid7`; `time` is business time, `created_at` defaults to `time` in `__post_init__` (frozen struct honours `object.__setattr__` there).

**Strategy:**
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py` (Strategy ABC), `itrader/strategy_handler/pair_base.py` (PairStrategy); reference strategy `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, plus `strategies/empty_strategy.py`, `strategies/eth_btc_pair_strategy.py`; user-supplied strategies in `itrader/strategy_handler/my_strategies/`.
- Pattern: Subclass implements `generate_signal(ticker)` returning a `SignalIntent`; `StrategiesHandler` pushes bars via `update(ticker, bar)`, gates on `is_ready(ticker)`, and emits the resulting `SignalEvent` onto `global_queue`. Strategy TYPES are supplied via the injected `StrategyCatalog` allowlist (`itrader/strategy_handler/registry/catalog.py`) — `itrader` never imports a concrete strategy class by name; strategy INSTANCES are DATA rehydrated from the store via `registry/rehydrate.py` + `registry/config_codec.py`.

**Exchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange` (`exchanges/simulated.py`), `OkxExchange` (`exchanges/okx.py`, live).
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.

**PortfolioReadModel:**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.

**BarFeed:**
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`, `LiveBarFeed` (push-driven ring buffer, live).
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, `searchsorted`/incremental cursor per tick — zero per-tick resample).

**OrderStorage:**
- Purpose: Pluggable order-mirror persistence.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`; built via `OrderStorageFactory`.

**Fee/Slippage models:**
- Purpose: Pluggable execution cost.
- Examples: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`), `slippage_model/` (`zero`, `fixed`, `linear`).

**StrategyLifecycleManager (control plane):**
- Purpose: Owns the entire STRATEGY_COMMAND verb surface (add/enable/reconfigure/remove) moved verbatim out of `StrategiesHandler` (DECOMP-01/02).
- Examples: `itrader/strategy_handler/lifecycle/manager.py`.
- Pattern: Injected with `managed` (`ManagedStrategies`), `global_queue`, `feed`, `registry_store`, `strategy_catalog`, `portfolio_read_model`, `logger`; DOES hold `global_queue` (a stated deviation from the order-domain "no queue access" convention) because its moved bodies emit `UniversePollEvent`/`ErrorEvent` directly as part of its queue-only contract.

## Entry Points

**TradingSystem.run() (backtest):**
- Location: `itrader/trading_system/backtest_trading_system.py`; loop mechanics in `itrader/trading_system/backtest_runner.py::BacktestRunner`.
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks.
- Responsibilities: Wire components via `compose_engine`, derive membership + ping grid, precompute resampled frames, drive the for-loop, print/record metrics.

**LiveTradingSystem.start() / build_live_system():**
- Location: `itrader/trading_system/live_trading_system.py`.
- Triggers: External caller / web API.
- Responsibilities: `build_live_system` selects live backends (SQL/in-memory storage, connectors, safety controller, config router) and wires them through `compose_engine` + `SessionInitializer` + `LiveRouteRegistrar`; `LiveTradingSystem.start()` launches `LiveRunner`'s processing thread and manages lifecycle (status latch, halt).

**LiveTradingSystem.add_event():**
- Location: `itrader/trading_system/live_trading_system.py`.
- Triggers: Web API / external caller.
- Responsibilities: Fail-closed default-deny admission (D-10) — accepts only externally-originated `SIGNAL`, `STRATEGY_COMMAND`, and `CONFIG_UPDATE` events onto the queue; a `SIGNAL` routes through `OrderHandler.on_signal` → `AdmissionManager` so validation/sizing/cash-reservation run before any `OrderEvent` is emitted.

**Strategy.generate_signal(ticker):**
- Location: `itrader/strategy_handler/base.py` — strategy `generate_signal(ticker)` → `SignalIntent`, which `StrategiesHandler` turns into a `SignalEvent`.
- Triggers: `StrategiesHandler.on_bar` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread owned by `LiveRunner`; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates; connector-loop callbacks only flip thread-safe flags — blocking venue I/O always runs on the engine thread, never the asyncio loop.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Route table is single-writer:** `EventHandler.routes` is set once in `EventHandler.__init__`; `LiveRouteRegistrar.install()` is the ONLY place that mutates it afterward, and it does so exactly once at live-wiring time (no runtime re-mutation, LR-16).
- **Bar-timing contract:** the seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation is per-file, not per-package.** Verified per file (do not generalize a whole directory): TABS — `itrader/trading_system/engine_context.py`, `backtest_runner.py`, `itrader/strategy_handler/registry/catalog.py`, `itrader/strategy_handler/lifecycle/manager.py`, `itrader/strategy_handler/strategies_handler.py`, `itrader/events_handler/full_event_handler.py`. SPACES — `itrader/trading_system/session_initializer.py`, `live_runner.py`, `config_router.py`, `route_registrar.py`, `live_trading_system.py`, `itrader/events_handler/events/base.py`, `error_handler.py`, `bus.py`, and all of `itrader/config/`, `itrader/core/`. Measure the specific file before editing.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports and calls another domain handler's method directly instead of emitting an event.
**Why it's wrong:** Breaks the queue-only contract; makes ordering/timing implicit and untestable in isolation, and defeats both the backtest fail-fast and live publish-and-continue error seams.
**Do this instead:** Emit an event onto `global_queue` and add/confirm a route in `EventHandler.routes` (`itrader/events_handler/full_event_handler.py`) or, for read-only cross-domain access, use an injected read-model (`PortfolioReadModel`, `BacktestBarFeed`).

### Adding a new event type without registering it

**What happens:** A new `EventType` member is added and a frozen event class defined, but no entry is added to `EventHandler.routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on any event type not present as a key in `routes` (KB1 — silent drops are a tampering risk, T-04-18); an unrouted event type crashes the run rather than being silently ignored, so forgetting the entry is a hard failure, not a soft gap.
**Do this instead:** Define the frozen event under `events_handler/events/<domain>.py`, add the member to `core/enums/event.py::EventType`, and add an explicit key (even `[]` for "explicitly no consumer yet") to `EventHandler.routes` in `full_event_handler.py`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Order-fill matching logic (stop/limit trigger evaluation, OCO) is implemented in `OrderHandler`/`OrderManager` instead of the exchange.
**Why it's wrong:** Matching is the execution layer's responsibility — the exchange holds the resting-order book and is the source of truth for fills; duplicating matching logic in the order handler creates two sources of truth that can disagree.
**Do this instead:** `OrderManager` only translates signals into orders, declares brackets (`parent_order_id`/`child_order_ids`), and reconciles its mirror from `FillEvent`s in `on_fill`. All matching lives in `itrader/execution_handler/matching_engine.py::MatchingEngine`, composed by `SimulatedExchange`.

### Float arithmetic on money

**What happens:** A money value is constructed via `float(...)` or `Decimal(some_float)` instead of `to_money(x)`.
**Why it's wrong:** `Decimal(float)` inherits the binary-float representation artifact; float math on money is a locked correctness defect for the whole project.
**Do this instead:** Enter the Decimal domain only via `to_money(x)` (`itrader/core/money.py`); carry full precision through intermediate math; `quantize(value, instrument, kind)` only at money boundaries (ledger write, reported PnL, serialization).

## Error Handling

**Strategy:** Mode-specific error POLICY is injected once at composition time (`compose_engine`), not branched inline in `EventHandler`. Backtest fails fast; live publishes-and-continues.

**Patterns:**
- `EventHandler._dispatch` wraps each handler call in `try/except Exception` and delegates the decision to the injected `HandlerErrorPolicy.on_handler_error(event, handler)` — `FailFastPolicy` bare-re-raises (backtest, byte-exact oracle); `ErrorPolicy` emits an `ErrorEvent` and returns (live, keeps draining).
- `ErrorHandler.on_error` (`itrader/events_handler/error_handler.py`) is the real `ERROR`-route consumer: severity-mapped structured logging, CRITICAL alert-sink escalation, `last_error` persistence.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Execution failures flow as `FillEvent(REFUSED)` events, not exceptions — `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` so the order mirror reconciles via the normal FILL route.
- `ExecutionHandler.on_order`/`on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- Live CONTROL-plane fatal conditions route through `SafetyController.halt(reason)` — a latched freeze with no legal exit except operator `reset_halt()`, durably recorded via `HaltRecordStore`.

## Cross-Cutting Concerns

**Logging:** `structlog`; bind a component context via `get_itrader_logger().bind(component="ClassName")`.
**Validation:** `EnhancedOrderValidator` at order admission; `SimulatedExchange.validate_order` re-checks structural preconditions at the fill boundary (defense-in-depth, D-03a — justified overlap, not removed).
**Authentication:** Live external ingress is fail-closed/default-deny at `LiveTradingSystem.add_event` (D-10); connector credentials owned solely by the connector (`OkxSettings`, `SecretStr`).

---

*Architecture analysis: 2026-07-21*
