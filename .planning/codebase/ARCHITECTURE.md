<!-- refreshed: 2026-06-08 -->
# Architecture

**Analysis Date:** 2026-06-08

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Composition / Run Loop                            │
│   `itrader/trading_system/backtest_trading_system.py` (TradingSystem)     │
│   `itrader/trading_system/live_trading_system.py`     (LiveTradingSystem) │
│   `itrader/trading_system/trading_interface.py`       (TradingInterface)  │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ puts/drains
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         global_queue  (queue.Queue)                       │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ drained by
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                EventHandler — data-driven dispatch (`self._routes`)       │
│             `itrader/events_handler/full_event_handler.py`                │
└───────────┬───────────────┬───────────────┬───────────────┬───────────────┘
            │ TIME          │ BAR           │ SIGNAL/ORDER  │ FILL
            ▼               ▼               ▼               ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│ Screeners +    │ │ Portfolio MtM  │ │ OrderHandler   │ │ Portfolio      │
│ BarFeed factory│ │ + Execution    │ │ → OrderManager │ │ on_fill +      │
│                │ │ matching       │ │ ExecutionHandler│ │ Order mirror   │
│ `screeners_*`  │ │ + Strategies   │ │ → Exchanges    │ │ reconcile      │
│ `price_handler`│ │                │ │ MatchingEngine │ │                │
└────────────────┘ └────────────────┘ └────────────────┘ └────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  State stores (per-handler) + Reporting frames/metrics                    │
│  Portfolio managers (cash/position/transaction/metrics) · Order storage   │
│  `itrader/reporting/` (equity curve, trade log, derived metrics)          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self._routes` (list order = execution order); fail-fast error seam | `itrader/events_handler/full_event_handler.py` |
| `TradingSystem` | Backtest composition root + synchronous run loop over `TimeGenerator` | `itrader/trading_system/backtest_trading_system.py` |
| `LiveTradingSystem` | Live composition root; background processing thread + start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per bar; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; admission/sizing; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol implementation | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven pipeline over a single FIFO `queue.Queue` (`global_queue`), with a handler-per-domain decomposition and a thin-handler / fat-manager split.

**Key Characteristics:**
- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler._routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Adding/changing routing happens only there.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol) and `BacktestBarFeed` are injected as read-models; the queue-only rule governs handlers, not read-models.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.

## Layers

**Composition / Run loop:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers.

**Dispatch:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain handlers:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes + fat managers/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data engine:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlPriceStore`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Shared core:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Configuration:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, domain models. The registry/provider getters were removed (M2-06); `SystemConfig.default()` is constructed directly.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`.

**Process singletons:**
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `TradingSystem.run()` calls `_initialise_backtest_session()` then `_run_backtest()` (`itrader/trading_system/backtest_trading_system.py:204`).
2. For each tick the loop advances the clock, puts the `TimeEvent`, and calls `process_events()` (`backtest_trading_system.py:188`).
3. `EventHandler._dispatch` routes `TIME` → `screeners_handler.screen_markets` then `feed.generate_bar_event` (`full_event_handler.py:69`).
4. `BAR` → `portfolio_handler.update_portfolios_market_value` (mark-to-market), `execution_handler.on_market_data` (resting-order matching → `FillEvent`), `strategies_handler.calculate_signals` (`full_event_handler.py:73`).
5. `SIGNAL` → `order_handler.on_signal` → `OrderManager` validates/sizes → emits `OrderEvent` (`full_event_handler.py:78`).
6. `ORDER` → `execution_handler.on_order` → `SimulatedExchange` fills market now or rests stop/limit in `MatchingEngine` → emits `FillEvent` (`full_event_handler.py:79`).
7. `FILL` → `portfolio_handler.on_fill` (positions/cash on EXECUTED), then `order_handler.on_fill` (mirror reconcile FILLED/CANCELLED/REJECTED) (`full_event_handler.py:80`).
8. After draining, each active portfolio records metrics at `time_event.time` (`backtest_trading_system.py:197`).

### Live Trading Path

1. `LiveTradingSystem.start()` launches a daemon thread (`itrader/trading_system/live_trading_system.py:290`).
2. The thread blocks on `global_queue.get(timeout=...)` and dispatches via the same `EventHandler` (`live_trading_system.py:246`).
3. `TradingInterface` validates the system is running and puts `OrderEvent`s directly onto `global_queue`.

### Bracket / Resting-Order Flow

1. `OrderManager` declares brackets via `parent_order_id` / `child_order_ids`; the exchange enforces OCO.
2. `MatchingEngine.on_bar` evaluates stop/limit triggers against intrabar high/low, applies gap-aware fills and same-bar OCO priority (`itrader/execution_handler/matching_engine.py:184`).
3. Fills land at the next open (D-01 bar-timing contract); orders decided on the final tick never fill.

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `LiveTradingSystem._status_lock` + `threading.Event`.

## Key Abstractions

**Event (frozen fact):**
- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent`.
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.

**Strategy:**
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `itrader/strategy_handler/SMA_MACD_strategy.py`, `itrader/strategy_handler/my_strategies/`.
- Pattern: Subclass implements `calculate_signal(...)`; emits a `SignalEvent` onto `global_queue`.

**AbstractExchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange`.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.

**PortfolioReadModel (Protocol):**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.

**Price Store / BarFeed:**
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`.
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, `searchsorted` per tick — zero per-tick resample).

**OrderStorage:**
- Purpose: Pluggable order-mirror persistence.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `postgresql_storage.py`; built via `OrderStorageFactory`.

**Fee / Slippage models:**
- Purpose: Pluggable execution cost.
- Examples: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`), `slippage_model/` (`zero`, `fixed`, `linear`).

## Entry Points

**Backtest:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks.
- Responsibilities: Wire components, derive membership + ping grid, precompute resampled frames, drive the for-loop, print/record metrics.

**Live:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch processing thread, manage lifecycle.

**External order injection:**
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.

**Signal generation:**
- Location: `itrader/strategy_handler/base.py` — strategy `calculate_signal` → `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Bar-timing contract:** the seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler invokes another domain's handler method instead of emitting an event.
**Why it's wrong:** Breaks the queue-only contract; couples domains and bypasses ordering/error policy.
**Do this instead:** Put an event on `global_queue`; let `EventHandler._routes` dispatch it (`itrader/events_handler/full_event_handler.py:68`). Read-only cross-domain access goes through an injected read-model (`PortfolioReadModel`, `BacktestBarFeed`).

### Adding a new event type without registering it

**What happens:** A new event class is created but no `_routes` branch is added.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on unknown types (silent drops are a tampering risk).
**Do this instead:** Add the member to `EventType` (`itrader/core/enums/event.py`), define the frozen dataclass under `itrader/events_handler/events/`, and add a branch to `EventHandler._routes`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** The order layer evaluates triggers / decides fills.
**Why it's wrong:** The execution layer (exchange + `MatchingEngine`) is the sole source of truth for fills; duplicating match logic desynchronises the mirror.
**Do this instead:** `OrderManager` declares brackets and reconciles its mirror in `on_fill`; matching lives in `itrader/execution_handler/matching_engine.py`.

### Float arithmetic on money

**What happens:** A money value is computed or stored as `float`.
**Why it's wrong:** Float money is a locked correctness defect for this refactor.
**Do this instead:** Keep `Decimal` end-to-end; narrow to `float` only at the logging/serialization edge (e.g. `backtest_trading_system.py:251`).

## Error Handling

**Strategy:** Backtest policy is fail-fast — `EventHandler._on_handler_error` re-raises so a handler failure aborts the run rather than corrupting state. The live system overrides this method with publish-and-continue (emit `ErrorEvent`, keep draining); `_dispatch` stays untouched.

**Patterns:**
- `EventHandler._log_error_event` is the real `ERROR`-route consumer (structured log sink, severity-mapped).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles.
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`).

## Cross-Cutting Concerns

**Logging:** structlog; bind with `get_itrader_logger().bind(component="ClassName")` → `self.logger`. TIME per-tick flow is DEBUG.
**Validation:** `EnhancedOrderValidator` (`itrader/order_handler/order_validator.py`); `PortfolioHandler` validators in `validators.py`; config via Pydantic models.
**Authentication:** Not applicable to the engine path (live providers carry their own credentials).

---

*Architecture analysis: 2026-06-08*
