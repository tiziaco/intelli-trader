<!-- refreshed: 2026-06-10 -->
# Architecture

**Analysis Date:** 2026-06-10

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          Composition / Run Layer                          │
├──────────────────────────┬──────────────────────────┬────────────────────┤
│      TradingSystem        │    LiveTradingSystem      │  TradingInterface  │
│ `trading_system/          │ `trading_system/          │ `trading_system/   │
│  backtest_trading_        │  live_trading_            │  trading_          │
│  system.py`               │  system.py`               │  interface.py`     │
│ (synchronous for-loop)    │ (background daemon thread)│ (web/API bridge)   │
└────────────┬──────────────┴────────────┬─────────────┴──────────┬─────────┘
             │     all wire one shared    │   global_queue          │
             ▼              ▼              ▼                         │
┌─────────────────────────────────────────────────────────────────────────┐
│                       EventHandler (dispatcher)                           │
│  `events_handler/full_event_handler.py`                                   │
│  Drains global_queue; routes each event via `self._routes`                │
│  (dict[EventType, list[Callable]]; LIST ORDER IS EXECUTION ORDER)         │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
   │ TIME     │ BAR      │ SIGNAL   │ ORDER    │ FILL     │ ERROR
   ▼          ▼          ▼          ▼          ▼          ▼
┌──────────┐┌──────────┐┌─────────┐┌─────────┐┌─────────────────┐┌────────┐
│screeners ││portfolio ││ order   ││execution││ portfolio_h.    ││ _log_  │
│ + feed   ││ + exec   ││ handler ││ handler ││ on_fill         ││ error_ │
│(BarEvent)││ + strats ││on_signal││on_order ││ + order_h.      ││ event  │
│          ││          ││         ││         ││ on_fill         ││        │
└────┬─────┘└────┬─────┘└────┬────┘└────┬────┘└────────┬────────┘└────────┘
     │           │           │          │              │
     ▼           ▼           ▼          ▼              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Domain Handlers / Managers                       │
│  strategy_handler/   order_handler/   execution_handler/  portfolio_h/    │
│  screeners_handler/  universe/        reporting/                          │
└─────────────────────────────┬─────────────────────────────────────────────┘
                              │ read-model seams (NOT queue)
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   price_handler/ (store + feed + providers)   core/ (enums/money/ids/...) │
│   `price_handler/store/csv_store.py`          `core/portfolio_read_       │
│   `price_handler/feed/bar_feed.py`             model.py`                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain `global_queue`; dispatch each event through `self._routes` (list order = execution order); fail-fast/publish error seam | `itrader/events_handler/full_event_handler.py` |
| `TradingSystem` | Backtest composition root + synchronous `for`-loop over `TimeGenerator`; in-memory storage; prints metrics | `itrader/trading_system/backtest_trading_system.py` |
| `LiveTradingSystem` | Live composition root; background daemon processing thread + start/stop/status lifecycle; publish-and-continue error seam | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` (order creation, validation, status) | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per BAR; emit `SignalEvent`s; sink to signal store | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Thin event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; admission/sizing; bracket declaration; no queue access | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR (`on_market_data`) | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `update_portfolios_market_value`; implements `PortfolioReadModel` Protocol | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven architecture with a single FIFO `global_queue` and data-driven dispatch.

**Key Characteristics:**
- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler._routes` is a single `dict[EventType, list[Callable]]` literal in `itrader/events_handler/full_event_handler.py`. List order IS execution order (D-14). Adding or changing routing happens only there.
- **Handler/Manager split.** Each domain pairs a thin `<Domain>Handler` (queue interface, no business logic) with a fat `<Domain>Manager` (business logic, no queue access).
- **Frozen event facts.** Every event subclasses `Event` (`@dataclass(frozen=True, slots=True, kw_only=True)`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol, `itrader/core/portfolio_read_model.py`) and `BacktestBarFeed` are injected read-models; the queue-only rule governs handler-to-handler *writes*, not injected *reads*.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One shared seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.

## Layers

**Composition / Run Layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface`, `TimeGenerator` (`simulation/`).
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`, `universe`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers, the E2E harness.

**Dispatch Layer:**
- Purpose: Drain the queue and route each event to its registered handler callables in list order.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain Handler Layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes + fat managers/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data / Read-Model Layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlPriceStore`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Shared Core Layer:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`, `constants.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Config Layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig` (`portfolio.py`), `ExchangeConfig` (`exchange.py`), `Settings` env-var layer (`settings.py`), domain models (`models.py`). The registry/provider getters were removed (M2-06); `SystemConfig.default()` is constructed directly.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`.

**Singletons (import side effects):**
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `TradingSystem.run()` calls `_initialise_backtest_session()` then `_run_backtest()` (`itrader/trading_system/backtest_trading_system.py:231`).
2. The for-loop pulls each `TimeEvent` from `TimeGenerator` and puts it on `global_queue` (`backtest_trading_system.py:211`).
3. `EventHandler.process_events()` drains the queue, dispatching via `_routes` (`itrader/events_handler/full_event_handler.py:91`).
4. **TIME** → `screeners_handler.screen_markets` + `feed.generate_bar_event` (produces `BarEvent`) (`full_event_handler.py:69`).
5. **BAR** → `portfolio_handler.update_portfolios_market_value` (mark-to-market) → `execution_handler.on_market_data` (resting-order matching → `FillEvent`) → `strategies_handler.calculate_signals` (`full_event_handler.py:73`).
6. **SIGNAL** → `order_handler.on_signal` (validate + size → `OrderEvent`) (`itrader/order_handler/order_handler.py:82`).
7. **ORDER** → `execution_handler.on_order` (exchange fills/rests → `FillEvent`) (`itrader/execution_handler/execution_handler.py:65`).
8. **FILL** → `portfolio_handler.on_fill` (EXECUTED only: update positions/cash) → `order_handler.on_fill` (reconcile order mirror) (`full_event_handler.py:80`).
9. After each tick, every active portfolio records metrics via `portfolio.record_metrics(time_event.time)` (`backtest_trading_system.py:221`).

### Bracket / Resting-Order Flow

1. `OrderManager` declares brackets via `parent_order_id`/`child_order_ids` on entry; it never matches orders.
2. `SimulatedExchange` composes `MatchingEngine`, which holds the resting-order book (`MatchingEngine._resting`) and evaluates stop/limit triggers against intrabar high/low with gap-aware fills and same-bar OCO priority.
3. On each BAR, `execution_handler.on_market_data` drives matching; the exchange applies fee/slippage and emits `FillEvent`s (EXECUTED, CANCELLED via OCO, or REFUSED).
4. `order_handler.on_fill` reconciles the stored mirror (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED).

### Live Trading Path

1. `LiveTradingSystem.start()` launches a background daemon thread that drains `global_queue` (`itrader/trading_system/live_trading_system.py`).
2. `TradingInterface` validates running state and enqueues `OrderEvent`s from the web/external API.
3. The same handler graph processes events, but `_on_handler_error` is overridden to publish-and-continue (emit `ErrorEvent`, keep draining).

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`).
- Signal record sink: `SignalStore` (in-memory for backtest) injected into `StrategiesHandler`.
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `LiveTradingSystem._status_lock` + `threading.Event`.

## Key Abstractions

**Event (frozen dataclass):**
- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`/`BarEvent` (`market.py`), `SignalEvent` (`signal.py`), `OrderEvent` (`order.py`), `FillEvent` (`fill.py`), `ErrorEvent`/`PortfolioErrorEvent` (`error.py`).
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event` (`base.py`); `type` pinned via `field(default=EventType.X, init=False)`; factory class methods (`new_fill`) for safe construction.

**Strategy base:**
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, `itrader/strategy_handler/my_strategies/`.
- Pattern: Subclass implements `calculate_signal(...)`; emits a `SignalEvent` onto `global_queue`.

**Exchange (abstract):**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange` (`simulated.py`).
- Pattern: Implements `on_order`, `on_market_data`, `connect`/`disconnect`/`health_check`/`validate_order`.

**PortfolioReadModel (Protocol):**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.

**Store + Feed (read-models):**
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`.
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, `searchsorted` per tick — zero per-tick resample).

**Pluggable cost/storage models:**
- Fee: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`).
- Slippage: `itrader/execution_handler/slippage_model/` (`zero`, `fixed`, `linear`).
- Order mirror: `itrader/order_handler/storage/` (`in_memory_storage.py`, `postgresql_storage.py`) via `OrderStorageFactory`.

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks, `tests/e2e/` harness.
- Responsibilities: Wire components, derive membership + ping grid, precompute resampled frames, drive the for-loop, print/record metrics.

**Live run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch daemon processing thread, manage start/stop/status lifecycle.

**External order injection:**
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.

**Strategy signal emission:**
- Location: `itrader/strategy_handler/base.py` — strategy `calculate_signal` → `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR (`itrader/strategy_handler/strategies_handler.py:52`).

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Bar-timing contract:** the seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock` (`core/clock.py`).
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the `events_handler/events/` package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports another handler and calls its method directly instead of emitting an event.
**Why it's wrong:** Breaks the queue-only contract; ordering and error policy bypass `EventHandler._routes` and `_on_handler_error`.
**Do this instead:** Emit the appropriate event onto `global_queue`. For reads, inject a read-model (`PortfolioReadModel` in `itrader/core/portfolio_read_model.py`, or `BacktestBarFeed`).

### Adding a new event type without registering it

**What happens:** A new event subclass is defined but no branch is added to `EventHandler._routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on an unrouted type (silent drops are a tampering risk).
**Do this instead:** Define the frozen dataclass under `events_handler/events/<domain>.py`, add the member to `core/enums/event.py::EventType`, and add a branch to `_routes` in `itrader/events_handler/full_event_handler.py`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Order-fill matching logic creeps into the order layer.
**Why it's wrong:** Matching is the execution layer's job; the exchange holds the resting-order book and is the source of truth for fills.
**Do this instead:** `OrderManager` declares brackets (`parent_order_id`/`child_order_ids`) and reconciles its mirror from `FillEvent`s in `order_handler.on_fill`. Matching lives in `itrader/execution_handler/matching_engine.py`.

### Float arithmetic on money

**What happens:** Money computed with `float`, or `Decimal(float_value)` called directly.
**Why it's wrong:** Float-for-money is a locked correctness defect; `Decimal(float)` carries binary-float repr artifacts.
**Do this instead:** Enter the Decimal domain via `to_money(x)` (`itrader/core/money.py`); `quantize` only at money boundaries. `float()` only at the serialization/logging edge.

## Error Handling

**Strategy:** Typed exceptions raised in domain logic; caught-and-logged at the event boundary; rejections flow as events, not exceptions.

**Patterns:**
- `EventHandler._on_handler_error` is the policy seam: backtest re-raises (fail-fast); live overrides to publish-and-continue.
- `EventHandler._log_error_event` is the ERROR-route consumer (structured log sink, severity-mapped).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles.
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`).

## Cross-Cutting Concerns

**Logging:** structlog via `get_itrader_logger().bind(component="ClassName")`; bound at construction. Levels: `info` for ops/init, `warning` for non-fatal, `error` with `exc_info=True` for caught exceptions.
**Validation:** `EnhancedOrderValidator` (`itrader/order_handler/order_validator.py`); fee/validation models raise `ValidationError` rather than returning `False`. Config validated by Pydantic models in `itrader/config/`.
**Authentication:** Not applicable to the backtest path; live providers read credentials from `.env` / `oanda.cfg` (see INTEGRATIONS.md).

---

*Architecture analysis: 2026-06-10*
