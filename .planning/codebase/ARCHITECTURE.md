<!-- refreshed: 2026-06-12 -->
# Architecture

**Analysis Date:** 2026-06-12

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                    Composition Root / Run Loop                            │
│   TradingSystem (backtest)          LiveTradingSystem (live)              │
│   `itrader/trading_system/          `itrader/trading_system/              │
│    backtest_trading_system.py`       live_trading_system.py`              │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │  global_queue (queue.Queue)
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        EventHandler                                       │
│          `itrader/events_handler/full_event_handler.py`                   │
│   self._routes: dict[EventType, list[Callable]]  (list order = exec order)│
└───┬──────────┬──────────────┬──────────────┬──────────────┬──────────────┘
    │TIME      │BAR           │SIGNAL        │ORDER         │FILL
    ▼          ▼              ▼              ▼              ▼
┌──────────┐ ┌─────────────┐ ┌────────────┐ ┌───────────┐ ┌──────────────┐
│Screeners │ │Portfolio    │ │Order       │ │Execution  │ │Portfolio     │
│Handler   │ │Handler      │ │Handler     │ │Handler    │ │Handler       │
│+BarFeed  │ │(mark-to-mkt)│ │(on_signal) │ │(on_order) │ │(on_fill)     │
│(generate │ │+Execution   │ │            │ │           │ │+Order Handler│
│_bar_event│ │(on_market   │ │            │ │           │ │(on_fill      │
│)         │ │_data)       │ │            │ │           │ │ reconcile)   │
│          │ │+Strategies  │ │            │ │           │ │              │
│          │ │(calc_signals│ │            │ │           │ │              │
└──────────┘ └─────────────┘ └────────────┘ └───────────┘ └──────────────┘
                                                │FillEvent
                                                ▼
                                       ┌─────────────────┐
                                       │SimulatedExchange │
                                       │(MatchingEngine + │
                                       │fee/slippage)     │
                                       └─────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch through `self.routes` (list order = execution order); fail-fast error seam | `itrader/events_handler/full_event_handler.py` |
| `TradingSystem` | Backtest composition root; synchronous for-loop over `TimeGenerator`; wires all components | `itrader/trading_system/backtest_trading_system.py` |
| `LiveTradingSystem` | Live composition root; background daemon thread; start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yields `TimeEvent`s across a pinned bar-date grid derived from the store index | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Fan-out strategies per BAR tick; stamps time/price; emits `SignalEvent`s; records to signal store | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem, `ignore_errors` mypy override) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Thin event interface: `on_signal` → orders via `OrderManager`; `on_fill` → mirror reconcile; API surface | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic: signal processing, admission/sizing, bracket declaration, lifecycle | `itrader/order_handler/order_manager.py` |
| `AdmissionManager` | Signal admission gate: cash reservation, position limits, sizing validation | `itrader/order_handler/admission/admission_manager.py` |
| `BracketManager` | Bracket (SL/TP) declaration and OCO sibling tracking | `itrader/order_handler/brackets/bracket_manager.py` |
| `LifecycleManager` | Order state machine transitions (PENDING → FILLED/CANCELLED/REJECTED) | `itrader/order_handler/lifecycle/lifecycle_manager.py` |
| `ReconcileManager` | Reconcile order mirror against exchange `FillEvent`s | `itrader/order_handler/reconcile/reconcile_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation; no queue/logging/fee deps | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; satisfies `PortfolioReadModel` Protocol structurally | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to four sub-managers (cash, position, transaction, metrics) | `itrader/portfolio_handler/portfolio.py` |
| `CashManager` | Cash balance, reservations, ledger writes | `itrader/portfolio_handler/cash/cash_manager.py` |
| `PositionManager` | Open/close positions; P&L calculation | `itrader/portfolio_handler/position/position_manager.py` |
| `MetricsManager` | Equity snapshots per tick; `PortfolioSnapshot` records | `itrader/portfolio_handler/metrics/metrics_manager.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed CSV(s); offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock seam; `set_time` advanced each tick | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven Domain Handler Architecture with data-driven dispatch.

**Key Characteristics:**
- **Queue-only cross-domain communication.** Handlers receive `global_queue` as a constructor argument and emit events; they never call other handler methods directly across domains. Read-only access goes through injected read-model Protocols, not handler imports.
- **Data-driven dispatch.** `EventHandler._routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Adding/changing routing happens ONLY in that dict.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`) carrying a UUIDv7 `event_id` and business `time` (never wall clock).
- **Handler/Manager split.** `<Domain>Handler` is a thin interface; `<Domain>Manager` owns business logic with NO queue access and NO back-reference to its handler.
- **Decimal end-to-end.** Float for money is a locked correctness defect. `float()` appears only at serialization/logging edges.
- **Determinism.** One shared seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` seam is advanced each tick.
- **Structural Protocol conformance.** `PortfolioHandler` satisfies `PortfolioReadModel` Protocol without inheritance; enforced by `mypy --strict`.

## Layers

**Composition / Run Layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`, `CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers.

**Dispatch Layer:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Handler Layer:**
- Purpose: Encapsulate domain event handling (strategy, order, execution, portfolio, screener).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes (`on_<event>` methods) + fat managers/sub-components owning business logic.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Price / Feed Layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed` (zero per-tick resample via precomputed frames + `searchsorted`), CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Core Layer:**
- Purpose: Cross-cutting enums, exceptions, IDs, money utilities, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`).
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`, `SizingPolicy` types.
- Depends on: Nothing inside `itrader`. This is the dependency root.
- Used by: All handlers and the config layer.

**Config Layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, `BaseStrategyConfig`. `SystemConfig.default()` is constructed directly; no registry/provider getters exist.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`, strategies.

**Reporting Layer:**
- Purpose: Pure builders for run artifacts and derived metrics; no handler imports.
- Location: `itrader/reporting/`
- Contains: `frames.py` (trade log + equity curve builders), `metrics.py` (CAGR, Sharpe, etc.), `plots.py` (Plotly charts), `summary.py`, `orders.py`, `cash_operations.py`.
- Depends on: `pandas`, `scipy`, stdlib only.
- Used by: `TradingSystem._print_metrics_summary()`, `scripts/run_backtest.py`.

**Process-level Singletons:**
- Location: `itrader/__init__.py`
- Initialized on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen`, `from itrader.logger import get_itrader_logger`.
- Warning: importing anything from `itrader` triggers this singleton initialization; do not import `itrader` in fixtures without understanding this.

## Data Flow

### Primary Backtest Request Path

1. `TradingSystem.run()` calls `_initialise_backtest_session()` — derives membership, binds `BacktestBarFeed`, sets ping grid, precomputes resampled frames per strategy. (`itrader/trading_system/backtest_trading_system.py:152`)
2. `_run_backtest()` for-loops over `TimeGenerator` — yields `TimeEvent` per tick. (`itrader/trading_system/simulation/time_generator.py`)
3. Each `TimeEvent` is put on `global_queue`; `EventHandler.process_events()` drains.
4. **TIME route** (dispatch order matters):
   - `ScreenersHandler.screen_markets` (deferred subsystem)
   - `BacktestBarFeed.generate_bar_event` → puts `BarEvent` for each active ticker. (`itrader/price_handler/feed/bar_feed.py`)
5. **BAR route** (dispatch order matters):
   - `PortfolioHandler.update_portfolios_market_value` — mark-to-market positions at current close. (`itrader/portfolio_handler/portfolio_handler.py`)
   - `ExecutionHandler.on_market_data` — `MatchingEngine` evaluates resting stop/limit against bar high/low; fills become `FillEvent`s. (`itrader/execution_handler/matching_engine.py`)
   - `StrategiesHandler.calculate_signals` — strategies run against look-ahead-safe bar windows; emit `SignalEvent`s. (`itrader/strategy_handler/strategies_handler.py`)
6. **SIGNAL route**: `OrderHandler.on_signal` → `OrderManager.process_signal` → admission checks → `BracketManager` for SL/TP → `OrderEvent`s put on queue. (`itrader/order_handler/order_handler.py`)
7. **ORDER route**: `ExecutionHandler.on_order` → routed to `SimulatedExchange.on_order` → market fills immediately or rests in `MatchingEngine`. (`itrader/execution_handler/exchanges/simulated.py`)
8. **FILL route** (dispatch order matters):
   - `PortfolioHandler.on_fill` — only EXECUTED fills update positions/cash via sub-managers. (`itrader/portfolio_handler/portfolio_handler.py`)
   - `OrderHandler.on_fill` → `ReconcileManager` reconciles order mirror (FILLED/CANCELLED/REJECTED). (`itrader/order_handler/reconcile/reconcile_manager.py`)
9. After `process_events()`, `portfolio.record_metrics(time_event.time)` snapshots equity. (`itrader/portfolio_handler/portfolio.py`)

### Bracket / Resting-Order Flow

1. Strategy emits `SignalEvent` with `sltp_policy` or explicit `stop_loss`/`take_profit`.
2. `OrderManager` via `BracketManager` declares bracket children linked by `parent_order_id`/`child_order_ids`.
3. `MatchingEngine` enforces OCO: when one child fills, the sibling is cancelled (same-bar priority: STOP beats LIMIT).
4. `ReconcileManager` on subsequent `FillEvent`s orphan-cancels any children whose parent hit a terminal state.

### Live Path

1. `LiveTradingSystem.start()` launches a daemon processing thread.
2. External events (tick data, user orders via `TradingInterface`) arrive on `global_queue`.
3. `EventHandler.process_events()` runs on the daemon thread; `_on_handler_error` is overridden to emit `ErrorEvent` and continue (publish-and-continue vs backtest fail-fast).

**State Storage:**
- Portfolio positions/cash: owned by each `Portfolio`'s sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over pluggable `OrderStorage` (`in_memory_storage.py` for backtest, `postgresql_storage.py` placeholder for live).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange` instance.
- Signal records: `SignalStore` (in-memory) injected into `StrategiesHandler`; read post-run via `TradingSystem.get_signal_records()`.

## Key Abstractions

**Events (`itrader/events_handler/events/`):**
- Purpose: All inter-component messages; immutable facts.
- Examples: `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`, `PortfolioErrorEvent`.
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods (`Order.new_order()`, `FillEvent.new_fill()`). UUIDv7 `event_id` auto-generated; business `time` is the simulation clock, never wall clock.

**Strategy Base (`itrader/strategy_handler/base.py`):**
- Purpose: Abstract base for all concrete strategies. Pure function of market data.
- Pattern: Subclass implements `generate_signal(ticker, bars) -> SignalIntent | None`. Declares `sizing_policy`, `direction`, `subscribed_portfolios`, `tickers`, `timeframe` at construction. Never touches the queue; `StrategiesHandler` owns fan-out and event emission.

**AbstractExchange (`itrader/execution_handler/exchanges/base.py`):**
- Purpose: Pluggable exchange interface.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`. Concrete: `SimulatedExchange`.

**PortfolioReadModel (`itrader/core/portfolio_read_model.py`):**
- Purpose: Narrow read boundary for order-domain reads of portfolio state (D-13..D-17).
- Pattern: `runtime_checkable` Protocol with six members: `available_cash`, `get_position`, `reserve`, `release`, `exchange_for`, `open_position_count`, `total_equity`. `PortfolioHandler` satisfies it structurally. `get_position` returns a frozen `PositionView` snapshot, never the live `Position`.

**PriceStore / BarFeed (`itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`):**
- Purpose: Look-ahead-safe data access seam.
- Pattern: Store loads OHLCV frames eagerly; feed slices per-tick windows via `searchsorted` (precompute once at session init, zero per-tick resample). Seven bar-timing rules enforced in `bar_feed.py`, never in strategies.

**OrderStorage (`itrader/order_handler/storage/`):**
- Purpose: Pluggable order-mirror persistence.
- Pattern: Interface in `base.py`; concrete `in_memory_storage.py` (backtest), `postgresql_storage.py` (live placeholder); selected via `OrderStorageFactory.create('backtest'|'postgresql')`.

**SizingPolicy (`itrader/core/sizing.py`):**
- Purpose: Typed sizing vocabulary. Strategy DECLARES, engine RESOLVES.
- Pattern: Three frozen dataclass policy kinds — `FractionOfCash`, `FixedQuantity`, `RiskPercent` — plus `SLTPPolicy` subtypes (`PercentFromFill`, `PercentFromDecision`). `SizingResolver` in `itrader/order_handler/sizing_resolver.py` match-dispatches on the kind.

**Fee/Slippage Models (`itrader/execution_handler/fee_model/`, `itrader/execution_handler/slippage_model/`):**
- Purpose: Pluggable execution cost.
- Pattern: Abstract base + three concrete implementations each: fee (`zero`, `percent`, `maker_taker`); slippage (`zero`, `fixed`, `linear`). `SimulatedExchange` composes one of each.

**ID Types (`itrader/core/ids.py`):**
- Purpose: Ten `NewType` aliases over `uuid.UUID` for compile-time type safety.
- Examples: `OrderId`, `PortfolioId`, `StrategyId`, `FillId`, `TransactionId`, etc. All UUIDv7 via `idgen` singleton.

## Entry Points

**Backtest Entry Point:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks, E2E test harness.
- Responsibilities: Wire components, init session (derive membership + ping grid, precompute resampled frames), drive the for-loop, print/record metrics.

**Live Entry Point:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch processing thread, manage lifecycle.

**Trading Interface:**
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.

**Strategy Signal:**
- Location: `itrader/strategy_handler/base.py` — `generate_signal(ticker, bars) -> SignalIntent | None`
- Triggers: `StrategiesHandler.calculate_signals` per BAR event.
- Reference implementation: `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`

**Data Ingestion:**
- Location: `itrader/price_handler/ingestion.py`
- Triggers: `scripts/normalize_data.py`, `scripts/cross_validate.py`

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed. `PortfolioHandler` collection lock was removed (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual `Portfolio` instances use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialized at import time. `MatchingEngine._resting` is instance-level per exchange.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in test fixtures without accounting for this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. The facade → manager → storage layering is strictly one-directional (D-18).
- **Bar-timing contract:** The seven rules in `itrader/price_handler/feed/bar_feed.py` are the single enforcement point for look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges. Enter Decimal domain via `to_money(x)` → `Decimal(str(x))` in `itrader/core/money.py`. NEVER `Decimal(float_val)`.
- **Determinism:** One shared seeded `random.Random` injected at wiring; injected `BacktestClock` advanced per tick.
- **Indentation:** Handler modules (`order_handler/`, `portfolio_handler/`, `execution_handler/`, `strategy_handler/`) use **tabs**; `config/`, `core/money.py`, `core/bar.py`, `core/ids.py`, events package use **4 spaces**. Always match the file being edited; never normalize.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** Importing and calling `PortfolioHandler.get_portfolio()` from inside `OrderManager`.
**Why it's wrong:** Bypasses the queue contract; creates hidden coupling; breaks the threading model.
**Do this instead:** Inject `PortfolioReadModel` (Protocol) into the manager constructor. All state reads go through the protocol; all state WRITES go through queue events.

### Adding a new event type without registering it

**What happens:** Adding a new `EventType` member and a new `Event` dataclass but forgetting to add a branch in `EventHandler._routes`.
**Why it's wrong:** `_dispatch()` raises `NotImplementedError` on an unrouted type — silent drops are explicitly prohibited (KB1/T-04-18).
**Do this instead:** Define the frozen dataclass under `itrader/events_handler/events/<domain>.py`, add the member to `itrader/core/enums/event.py::EventType`, add a branch to `EventHandler._routes` in `full_event_handler.py`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Writing trigger evaluation logic (stop/limit price checks) in `OrderManager.on_fill` or `OrderHandler`.
**Why it's wrong:** The exchange is the sole source of truth for fills. `MatchingEngine` in the execution layer owns the resting-order book and trigger evaluation.
**Do this instead:** Let `MatchingEngine.on_bar` handle trigger evaluation; `OrderManager.on_fill` only reconciles the mirror from the `FillEvent` the exchange emits.

### Float arithmetic on money

**What happens:** `total = float(price) * float(quantity)` inside a cash or position calculation.
**Why it's wrong:** Binary-float representation artifacts corrupt ledger values and break byte-exact oracle gates.
**Do this instead:** Enter Decimal via `to_money(x)` (`itrader/core/money.py`). Use `quantize(value, instrument, kind)` only at ledger-write/serialization boundaries, never inside intermediate math.

## Error Handling

**Backtest policy — fail-fast:** `EventHandler._on_handler_error` re-raises the active exception (`raise`). A handler failure aborts the run rather than silently corrupting state (`itrader/events_handler/full_event_handler.py:144`).

**Live policy — publish-and-continue:** `LiveTradingSystem` overrides `_on_handler_error` to emit an `ErrorEvent` onto the queue and keep draining. `ExecutionHandler.on_order` / `on_market_data` additionally catch per-exchange exceptions and log without re-raising (prevents queue stalls).

**Rejection flow:** `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False)` and emits `FillEvent(REFUSED)` so the order mirror reconciles without raising an exception.

**Portfolio errors:** `PortfolioHandler._operation_context()` (context manager) tracks active operations and publishes `PortfolioErrorEvent` on failure.

**Domain exception hierarchy (`itrader/core/exceptions/`):**
- Root: `ITraderError`
- Base categories: `ValidationError`, `ConfigurationError`, `StateError`, `ConcurrencyError`, `NotFoundError`
- Domain-specific: `PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError` (`portfolio.py`); `OrderError`, `UnsizedSignalError`, `SizingPolicyViolation` (`order.py`); `DataError`, `MalformedDataError`, `MissingPriceDataError` (`data.py`)
- Execution failures flow as `FillEvent(REFUSED)` events, not exceptions; error codes in `core/enums/execution.py::ExecutionErrorCode`.

## Cross-Cutting Concerns

**Logging:** structlog (`itrader/logger.py`). Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")`. Levels: `info` for successful ops/init; `warning` for non-fatal issues; `error` with `exc_info=True` for caught exceptions; `debug` rarely.

**Validation:** `EnhancedOrderValidator` (`itrader/order_handler/order_validator.py`) validates orders at the `create_order`/live path; `SimulatedExchange` has an internal second validation layer (defense-in-depth — justified by decision; see CONVENTIONS.md). Fee/validation models raise `ValidationError`, never return `False`.

**Authentication/API Keys:** Loaded from `.env` at repo root (never committed); read by `pydantic-settings` `Settings` with `env_prefix="ITRADER_"` (`itrader/config/settings.py`).

**Determinism seam:** `BacktestClock` is constructed in `TradingSystem.__init__` and `clock.set_time(time_event.time)` is called each iteration (`itrader/trading_system/backtest_trading_system.py:217`). The clock has no domain consumer yet (domain timestamps still use wall clock on some paths); consumer-wiring is a future phase (D-09/D-10).

---

*Architecture analysis: 2026-06-12*
