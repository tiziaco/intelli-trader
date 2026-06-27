<!-- refreshed: 2026-06-27 -->
# Architecture

**Analysis Date:** 2026-06-27

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                       Composition / Run Layer                             │
│   build_backtest_system(spec) -> compose_engine() -> BacktestRunner       │
│   `trading_system/compose.py` · `backtest_trading_system.py`              │
│   `backtest_runner.py` · `system_spec.py` · `live_trading_system.py`      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ wires every component around ONE queue
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  EventHandler — data-driven dispatch                       │
│   drain global_queue -> self.routes[event.type] (list order = exec order) │
│   `events_handler/full_event_handler.py`                                  │
└───────┬──────────┬───────────┬───────────┬───────────┬───────────┬────────┘
        ▼          ▼           ▼           ▼           ▼           ▼
   Strategies  Screeners   Portfolio   Order        Execution   Price/Feed
   Handler     Handler     Handler     Handler      Handler     (read-model)
   `strategy_  `screeners_ `portfolio_ `order_      `execution_ `price_
    handler/`   handler/`   handler/`   handler/`    handler/`   handler/`
        │                      │            │            │            │
        │ SignalEvent          │ on_fill    │ on_signal  │ on_order   │ BarEvent
        └──────────────── all emit/consume frozen msgspec Events ──────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  State stores (NOT on the queue — owned per-domain)                        │
│  Portfolio cash/position/transaction/metrics · OrderStorage (mirror)      │
│  MatchingEngine._resting (resting-order book) · BracketBook (OCO)         │
│  CsvPriceStore / SqlHandler (read-only on run path)                       │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `compose_engine` | Shared mode-agnostic wiring seam; builds the component graph into an `Engine` holder | `itrader/trading_system/compose.py` |
| `build_backtest_system` | Backtest factory: selects backends, seeds symbol set, calls `compose_engine`, builds runner | `itrader/trading_system/backtest_trading_system.py` |
| `BacktestRunner` | Synchronous per-tick run loop over `TimeGenerator` (`set_time` -> `queue.put` -> `process_events`) | `itrader/trading_system/backtest_runner.py` |
| `SystemSpec` | Frozen declarative description of what to run (strategies, portfolios, exchange, data/dates) | `itrader/trading_system/system_spec.py` |
| `LiveTradingSystem` | Live composition root; background daemon processing thread + start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (list order = execution order); error seam | `itrader/events_handler/full_event_handler.py` |
| `StrategiesHandler` | Run all strategies per BAR; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Thin event interface: `on_signal` -> orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | Coordinator: delegates to Admission/Bracket/Lifecycle/Reconcile managers (D-07) | `itrader/order_handler/order_manager.py` |
| `AdmissionManager` | Signal->order pipeline, sizing, cash-reservation admission gate | `itrader/order_handler/admission/admission_manager.py` |
| `BracketManager` / `BracketBook` | Declare OCO brackets; hold parent/child bracket state | `itrader/order_handler/brackets/` |
| `LifecycleManager` | Modify/cancel orders; run-end time-in-force sweep | `itrader/order_handler/lifecycle/lifecycle_manager.py` |
| `ReconcileManager` | Reconcile order mirror against exchange truth on FILL | `itrader/order_handler/reconcile/reconcile_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; satisfies `PortfolioReadModel` Protocol | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven pipeline on a single FIFO queue with data-driven dispatch, decomposed into thin domain handlers (facades) over fat managers.

**Key Characteristics:**
- **Queue-only cross-domain writes.** Handlers receive `global_queue` in their constructor and communicate by emitting events; they never call another handler's methods across domains.
- **Data-driven dispatch.** `EventHandler.routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Routing changes happen only there; an unrouted type raises `NotImplementedError` (silent drops are a tampering risk).
- **Frozen event facts via `msgspec.Struct` (v1.5).** Every event subclasses `Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)` carrying a UUIDv7 `event_id` and a business `time` (never wall clock). The `@dataclass` event base was migrated to msgspec.
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol) and `BacktestBarFeed` are injected; the queue-only rule governs *writes*, not injected read-models.
- **Facade -> manager -> storage layering.** `<Domain>Handler` (thin, queue-facing) delegates to `<Domain>Manager` (business logic, no queue) which delegates to pluggable storage.
- **Declarative composition.** A frozen `SystemSpec` describes WHAT to run; a mode-named factory (`build_backtest_system`) selects backends and calls the shared `compose_engine` seam.
- **Decimal end-to-end for money; determinism via injected seeded RNG + `BacktestClock`.**

## Layers

**Composition / Run Layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `compose_engine` (shared seam), `build_backtest_system` factory, `BacktestTradingSystem` (thin holder), `BacktestRunner` (loop), `SystemSpec`, `LiveTradingSystem`, `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, feed/store, `reporting`.
- Used by: `scripts/run_backtest.py`, e2e harness, notebooks, external/web callers.

**Dispatch Layer:**
- Purpose: Drain the queue and route each event to its registered handler callables in list order.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.routes`, `process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain Handler Layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `order_handler/`, `execution_handler/`, `portfolio_handler/`, `screeners_handler/`.
- Contains: Thin `<Domain>Handler` facades + fat managers / sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data Layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production; stateful indicators.
- Location: `itrader/price_handler/store/`, `feed/`, `providers/`; `strategy_handler/indicators/`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, shared-bar cache registration, CCXT/OANDA/Binance providers, stateful indicator catalog/handle.
- Depends on: `pandas`, `msgspec`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Core Layer:**
- Purpose: Cross-cutting primitives — enums, exceptions, ids, money, clock, read-model protocols, instrument/commission/sizing/constants.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `instrument.py`, `commission_estimator.py`, `constants.py`, `portfolio_read_model.py`).
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Config Layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, `OrderConfig`, exchange presets, `Settings(BaseSettings)`. Registry/provider getters were removed (M2-06); `SystemConfig.default()` is constructed directly.
- Used by: `itrader/__init__.py`, handlers.

**Import-Side-Effect Singletons:**
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `BacktestRunner.run()` iterates `engine.time_generator`, calls `clock.set_time(t)`, enqueues a `TimeEvent` (`itrader/trading_system/backtest_runner.py:145`)
2. `process_events()` drains the queue (`full_event_handler.py:91`)
3. **TIME route** -> `screeners_handler.screen_markets` + `bar_event_source` (the feed's `generate_bar_event` factory produces a `BarEvent` carrying a `Bar` per ticker) (`full_event_handler.py:69`)
4. **BAR route** (list order is the contract): `portfolio_handler.update_portfolios_market_value` (mark-to-market) -> `execution_handler.on_market_data` (resting stop/limit matching -> `FillEvent`) -> `strategies_handler.calculate_signals` (new signals) (`full_event_handler.py:73`)
5. **SIGNAL route** -> `order_handler.on_signal` -> `OrderManager.process_signal` (admission/sizing/bracket declaration) -> `OrderEvent` enqueued (`order_handler.py:123`)
6. **ORDER route** -> `execution_handler.on_order` -> `SimulatedExchange.execute_order` (fill or rest; apply fee/slippage) -> `FillEvent` (`full_event_handler.py:79`)
7. **FILL route**: `portfolio_handler.on_fill` (EXECUTED only: update positions/cash) -> `order_handler.on_fill` (mirror reconcile: FILLED/CANCELLED/REJECTED) (`full_event_handler.py:80`)
8. End-of-run: final `process_events()` drain clears pending cancels; metrics recorded per portfolio (`backtest_runner.py:162`)

### Live Trading Path

1. `LiveTradingSystem.start()` launches a daemon thread that loops `process_events()` (`itrader/trading_system/live_trading_system.py`)
2. `TradingInterface` validates running state and enqueues `OrderEvent`s from the external/web API
3. Same routes execute, but `_on_handler_error` is overridden to publish-and-continue (emit `ErrorEvent`, keep draining)

### Bracket / Resting-Order Flow

1. `OrderManager` declares a bracket via `parent_order_id` / `child_order_ids`; `BracketBook` holds the OCO state (`order_handler/brackets/bracket_book.py`)
2. The exchange (not the order handler) holds the resting-order book in `MatchingEngine._resting` and is the source of truth for fills
3. On a triggering BAR, `MatchingEngine` evaluates stop/limit against intrabar high/low with gap-aware fills and same-bar OCO priority; `SimulatedExchange` applies fee/slippage and emits the `FillEvent`
4. `ReconcileManager` reconciles the stored order mirror (EXECUTED->FILLED, CANCELLED->CANCELLED, REFUSED->REJECTED) and cancels orphaned children

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`).
- Bracket/OCO state: `BracketBook` (one per order manager).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `LiveTradingSystem` status lock + `threading.Event`.

## Key Abstractions

**Event (frozen `msgspec.Struct`):**
- Purpose: All inter-component messages; immutable facts.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent`.
- Pattern: subclass of `Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)`; `type` pinned via a `ClassVar[EventType]`; `event_id` auto-generated UUIDv7; `created_at` defaults to business `time` in `__post_init__` (uses `object.__setattr__` on the frozen struct). **v1.5: the whole event chain + `Bar` + 5 DTOs migrated from `@dataclass` to `msgspec.Struct`** — note the `events/__init__.py` docstring still references `@dataclass`/`FrozenInstanceError`, which is stale; the live base is msgspec.

**msgspec value-object DTOs (v1.5):**
- `Bar` (`core/bar.py`) — per-tick OHLCV struct, Decimal via `Decimal(str(x))`, carried on `BarEvent.bars` (ticker -> `Bar`).
- `Transaction` (`portfolio_handler/transaction/transaction.py`) — non-frozen struct (`gc=False`).
- `TrailState` (mutable), `FillDecision` (frozen), `CancelDecision` (frozen) in `execution_handler/matching_engine.py`.
- `SignalRecord` (frozen) in `strategy_handler/signal_record.py`.

**Strategy:**
- Purpose: Base for all trading strategies; `pair_base.py` for pairs strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `strategies/SMA_MACD_strategy.py`, `strategies/eth_btc_pair_strategy.py`, `strategies/empty_strategy.py`; `my_strategies/` for user code.
- Pattern: subclass implements `calculate_signal(...)`; emits a `SignalEvent` onto `global_queue`.

**Stateful indicator (v1.5 Model B):**
- Purpose: O(1) per-tick streaming indicators replacing per-tick `ta` full-series recompute.
- Examples: `strategy_handler/indicators/catalog.py` (typed singletons `SMA`/`MACDHist`/`EMA`/`RSI`), `indicators/handle.py`.
- Pattern: stateless adapter hands out a fresh recurrence `*State` via `new_state()`; advances on `update(value)`, exposes `value` / `is_ready` / `reset()` / `causal`. `ta`/pandas survive only as the test-time convergence oracle.

**Exchange:**
- Purpose: Pluggable exchange interface.
- Examples: `execution_handler/exchanges/base.py` (`AbstractExchange`); concrete `SimulatedExchange`.
- Pattern: implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.

**PortfolioReadModel (Protocol):**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.

**Price store / feed:**
- Purpose: Look-ahead-safe data access.
- Examples: `price_handler/store/base.py`, `feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`; `feed/cache_registration.py` (shared recent-bars cache capacity, derive-once).
- Pattern: store eager-loads frames; feed slices per-tick windows (monotonic incremental cursor — v1.5 perf fix replaced per-tick `searchsorted`).

**Pluggable cost/storage models:**
- Fee: `execution_handler/fee_model/` (`zero`/`percent`/`maker_taker`). Slippage: `slippage_model/` (`zero`/`fixed`/`linear`).
- Order storage: `order_handler/storage/` (`in_memory`/`postgresql`) via `OrderStorageFactory`.
- Signal storage: `strategy_handler/storage/` via `SignalStorageFactory`.

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `build_backtest_system(spec)` / `BacktestTradingSystem.run()`, driving `BacktestRunner`.
- Triggers: `scripts/run_backtest.py` (`make backtest`), `tests/integration/test_backtest_oracle.py`, e2e harness, notebooks.
- Responsibilities: select backends, seed the complete symbol set, wire via `compose_engine`, add strategies/portfolios in spec order, drive the for-loop, record/print metrics.

**Live run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`.
- Triggers: external caller / web API.
- Responsibilities: wire components, launch processing thread, manage start/stop/status lifecycle.

**External order injection:**
- Location: `itrader/trading_system/trading_interface.py`.
- Triggers: web API / external caller.
- Responsibilities: validate running state; construct and enqueue `OrderEvent`s.

**Strategy signal:**
- Location: `itrader/strategy_handler/base.py` — `calculate_signal` -> `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` and `BracketBook` are instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` <-> `OrderManager` and `OrderManager` <-> its sub-managers are resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Bar-timing contract:** the look-ahead-safety rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges; enter the Decimal domain only via `to_money` / `Decimal(str(x))`.
- **Determinism:** one shared seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); injected `BacktestClock`.
- **Indentation:** handler modules and `trading_system/` use TABS; `config/`, `core/`, `price_handler/feed/`, and the `events_handler/events/` package use 4 spaces — match the file, never normalize.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports and calls another handler's method (e.g. `portfolio_handler.on_fill(...)` from execution code).
**Why it's wrong:** Breaks the single-queue ordering contract and the data-driven dispatch model; introduces hidden coupling and non-deterministic execution order.
**Do this instead:** Emit an event onto `global_queue`; let `EventHandler.routes` dispatch it. Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel`, `BacktestBarFeed`).

### Adding a new event type without registering it

**What happens:** A new `Event` subclass is constructed and enqueued but no `routes` entry exists.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on an unrouted type (`full_event_handler.py:116`) — silent drops are a tampering risk (T-04-18).
**Do this instead:** Add the member to `core/enums/event.py::EventType`, define the frozen `msgspec.Struct` under `events_handler/events/<domain>.py`, and add a branch to `EventHandler.routes`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Order code evaluates stop/limit triggers and decides fills itself.
**Why it's wrong:** Matching is the execution layer's responsibility; the exchange holds the resting-order book and is the source of truth. Duplicating it desynchronizes the mirror.
**Do this instead:** `OrderManager` declares brackets (`parent_order_id`/`child_order_ids`); the `MatchingEngine`/`SimulatedExchange` matches and emits `FillEvent`s; `ReconcileManager` reconciles the mirror in `on_fill`.

### Float arithmetic on money

**What happens:** `Decimal(some_float)` or float math on prices/cash/PnL.
**Why it's wrong:** Carries the binary float-repr artifact; float-for-money is a locked correctness defect.
**Do this instead:** Enter the Decimal domain via `to_money(x)` / `Decimal(str(x))` (`core/money.py`); carry full precision; `quantize` only at money boundaries.

## Error Handling

**Strategy:** Run-mode-specific error policy at the dispatch seam — backtest fail-fast, live publish-and-continue. Domain failures surface as typed exceptions or as `FillEvent(REFUSED)` events, never as silent drops.

**Patterns:**
- `EventHandler._on_handler_error` is the policy seam: backtest re-raises (fail-fast, abort the run); `LiveTradingSystem` overrides to emit `ErrorEvent` and keep draining.
- `EventHandler._log_error_event` is the ERROR-route consumer (structured log sink, severity-mapped).
- `SimulatedExchange.execute_order` returns an `ExecutionResult(success=False, ...)` and emits `FillEvent(REFUSED)` so the order mirror reconciles — rejections flow as events, not exceptions.
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`, `strategy.py`); execution error codes in `core/enums/execution.py::ExecutionErrorCode`.

## Cross-Cutting Concerns

**Logging:** structlog with bound component context — `self.logger = get_itrader_logger().bind(component="ClassName")`. `info` for ops/init, `warning` for non-fatal, `error` with `exc_info=True` for caught exceptions.
**Validation:** `EnhancedOrderValidator` (`order_handler/order_validator.py`) at the domain boundary; `SimulatedExchange.validate_order` at the exchange boundary (intentional dual-layer defense-in-depth, D-03a). Pydantic validates config.
**Authentication:** N/A on the backtest engine path; live providers (OANDA/Binance/CCXT) read credentials from `.env` / `oanda.cfg`.

---

*Architecture analysis: 2026-06-27*
