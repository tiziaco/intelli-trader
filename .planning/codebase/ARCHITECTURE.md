<!-- refreshed: 2026-06-07 -->
# Architecture

**Analysis Date:** 2026-06-07

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Trading System Layer                                 │
│  TradingSystem (backtest for-loop)   LiveTradingSystem (threaded daemon)    │
│  `itrader/trading_system/backtest_trading_system.py`                        │
│  `itrader/trading_system/live_trading_system.py`                            │
│  Composition root: wires all components around one shared global_queue      │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ puts TimeEvent per tick
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   EventHandler — Queue Drain & Dispatch                      │
│  `itrader/events_handler/full_event_handler.py`                             │
│  _routes: dict[EventType, list[Callable]] — list order IS execution order   │
└──────┬──────────┬────────────────┬──────────────┬──────────────┬────────────┘
       │ BAR      │ SIGNAL         │ ORDER        │ FILL         │ TIME/BAR
       ▼          ▼                ▼              ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐  ┌──────────────────┐
│Portfolio │ │ Order    │ │ Execution    │ │Portfolio │  │ Strategies       │
│Handler   │ │ Handler  │ │ Handler      │ │ Handler  │  │ Handler          │
│`portfolio│ │`order_   │ │`execution_   │ │`on_fill` │  │`strategies_      │
│_handler/ │ │handler/  │ │handler/      │ │          │  │handler/          │
│portfolio │ │order_    │ │execution_    │ │ Order    │  │strategies_       │
│_handler.p│ │handler.py│ │handler.py`   │ │ Handler  │  │handler.py`       │
│y`        │ │          │ │              │ │`on_fill` │  │                  │
└──────────┘ └────┬─────┘ └──────┬───────┘ └──────────┘  └──────────────────┘
                  │ OrderEvent   │ FillEvent via global_queue
                  ▼              ▼
          ┌────────────────────────────────────────────────────────┐
          │         SimulatedExchange + MatchingEngine              │
          │  `itrader/execution_handler/exchanges/simulated.py`    │
          │  `itrader/execution_handler/matching_engine.py`        │
          │  Pure resting-order book: stop/limit/market next-bar   │
          └────────────────────────────────────────────────────────┘
                                 │
                                 ▼
          ┌────────────────────────────────────────────────────────┐
          │        Data Layer (read-only on the run path)           │
          │  CsvPriceStore `itrader/price_handler/store/csv_store.py`│
          │  BacktestBarFeed `itrader/price_handler/feed/bar_feed.py`│
          │  TimeGenerator `itrader/trading_system/simulation/      │
          │                 time_generator.py`                      │
          └────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | Primary File |
|-----------|----------------|--------------|
| `TradingSystem` | Composition root + synchronous backtest for-loop | `itrader/trading_system/backtest_trading_system.py` |
| `LiveTradingSystem` | Composition root + daemon-thread event loop | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and LiveTradingSystem | `itrader/trading_system/trading_interface.py` |
| `EventHandler` | Drain global_queue; route each event via `_routes` registry | `itrader/events_handler/full_event_handler.py` |
| `StrategiesHandler` | Iterate strategies per BAR; push data windows from feed | `itrader/strategy_handler/strategies_handler.py` |
| `Strategy` (ABC) | Abstract base; concrete subclasses emit `SignalEvent` via `_generate_signal` | `itrader/strategy_handler/base.py` |
| `ScreenersHandler` | Dynamic market screening on TIME events; updates universe | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: translate SignalEvent → OrderEvent; reconcile fills | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; bracket declaration; signal→order sizing | `itrader/order_handler/order_manager.py` |
| `EnhancedOrderValidator` | Order admission validation against `PortfolioReadModel` | `itrader/order_handler/order_validator.py` |
| `ExecutionHandler` | Route OrderEvents to exchanges; drive resting-order matching per bar | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Compose MatchingEngine; apply fee/slippage; emit FillEvents | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; stop/limit/market trigger evaluation; OCO | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle management; `on_fill` routing; cash reservations | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to four sub-managers | `itrader/portfolio_handler/portfolio.py` |
| `CashManager` | Cash ledger; reservations (`reserve`/`release`) | `itrader/portfolio_handler/cash/cash_manager.py` |
| `PositionManager` | Open/close positions | `itrader/portfolio_handler/position/position_manager.py` |
| `TransactionManager` | Transaction audit log | `itrader/portfolio_handler/transaction/transaction_manager.py` |
| `MetricsManager` | Equity-curve and performance metric recording | `itrader/portfolio_handler/metrics/metrics_manager.py` |
| `DynamicUniverse` | Maintains symbol set; generates BarEvent per tick from feed | `itrader/universe/dynamic.py` |
| `BacktestBarFeed` | Look-ahead-safe OHLCV window provider; zero resample on hot path | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Read-only golden-dataset store; loads CSV eagerly at construction | `itrader/price_handler/store/csv_store.py` |
| `TimeGenerator` | Iterates bar timestamps from the store's index; yields `TimeEvent` | `itrader/trading_system/simulation/time_generator.py` |
| `BacktestClock` | Injected deterministic clock advanced per tick | `itrader/core/clock.py` |
| `IDGenerator` | UUIDv7 generation via `uuid-utils` Rust backend | `itrader/outils/id_generator.py` |

## Pattern Overview

**Overall:** Event-driven handler pipeline with a single shared FIFO queue (`queue.Queue`)

**Key Characteristics:**
- All inter-component communication via `global_queue.put(event)` — cross-domain direct calls are forbidden
- `EventHandler._routes` is a single literal dict mapping `EventType` to ordered handler lists; list order is execution order
- Events are immutable frozen dataclasses (`frozen=True, slots=True, kw_only=True`); mutation raises `FrozenInstanceError`
- Handler/Manager split: each Handler is a thin queue-facing facade; the Manager owns all business logic
- Execution layer (MatchingEngine + SimulatedExchange) is the sole source of truth for fills; OrderHandler only reconciles its mirror
- `PortfolioReadModel` Protocol is the narrow read boundary crossing from order domain to portfolio domain

## Layers

**Trading System Layer (Composition Root):**
- Purpose: Wire all components together around one `global_queue`; drive the run loop
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (sync for-loop), `LiveTradingSystem` (threaded), `TradingInterface` (API bridge), `TimeGenerator`, `SimulationEngine` base
- Depends on: All handler layers, data layer, `EventHandler`
- Used by: External callers, scripts, notebooks, web APIs

**Event Dispatch Layer:**
- Purpose: Drain the `global_queue` and route events to registered handlers in declared order
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler`, `_routes` registry, `_on_handler_error` policy seam
- Depends on: All handler layers (injected at construction)
- Used by: Both trading system run loops

**Handler Layer (Domain Facades):**
- Purpose: Receive events from queue; validate; delegate business logic; emit result events back to queue
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`
- Contains: Public handler classes and their sub-managers / sub-components
- Depends on: `events_handler/events/`, `core/`, shared `global_queue`; order domain reads portfolio via `PortfolioReadModel` Protocol
- Used by: `EventHandler` only

**Core / Cross-Cutting Layer:**
- Purpose: Shared enums, exceptions, identity types, money policy — no dependencies on any handler
- Location: `itrader/core/enums/`, `itrader/core/exceptions/`, `itrader/core/money.py`, `itrader/core/ids.py`, `itrader/core/bar.py`, `itrader/core/clock.py`, `itrader/core/portfolio_read_model.py`
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `FillStatus`, `PortfolioState`, `Side`, domain exception hierarchies, `to_money`, `quantize`, all `NewType` id aliases
- Depends on: Nothing inside itrader
- Used by: All layers

**Data Layer:**
- Purpose: Price ingestion, storage, and look-ahead-safe read-model for the engine hot path
- Location: `itrader/price_handler/`
- Contains: `CsvPriceStore`, `BacktestBarFeed` (look-ahead enforcer), SQL store, CCXT/OANDA providers, Binance streaming
- Depends on: `core/`, `config/`
- Used by: Composition root (injected into `DynamicUniverse`, `StrategiesHandler`); never called directly by handlers

**Config Layer:**
- Purpose: Domain-based Pydantic v2 configuration models constructed directly (no registry)
- Location: `itrader/config/`
- Contains: `SystemConfig`, `PortfolioConfig`, `TradingConfig`, `DataConfig`, `ExchangeConfig`, `Settings` (pydantic-settings)
- Depends on: `itrader/settings/` YAML files (optional; gitignored in prod)
- Used by: Composition roots, `PortfolioHandler`, `SimulatedExchange`, `itrader/__init__.py`

**Process-Wide Singletons (initialized on package import):**
- Location: `itrader/__init__.py`
- `config` — `SystemConfig.default()` Pydantic model
- `logger` — `ITraderStructLogger` (structlog)
- `idgen` — `IDGenerator` (UUIDv7 via `uuid-utils`)

## Data Flow

### Primary Backtest Tick Path

1. `TimeGenerator.__iter__` yields `TimeEvent(time=T)` — `itrader/trading_system/simulation/time_generator.py`
2. `TradingSystem._run_backtest` advances `BacktestClock.set_time(T)`, puts `TimeEvent` on `global_queue` — `itrader/trading_system/backtest_trading_system.py:164`
3. `EventHandler.process_events()` drains queue; dispatches `TimeEvent` to `_routes[TIME]`:
   - `ScreenersHandler.screen_markets(time_event)` (deferred subsystem, screener flow)
   - `DynamicUniverse.generate_bar_event(time_event)` → builds `BarEvent` → puts on queue
4. `EventHandler` dispatches `BarEvent` to `_routes[BAR]` in order:
   - `PortfolioHandler.update_portfolios_market_value(bar)` — mark-to-market at bar close
   - `ExecutionHandler.on_market_data(bar)` — drive `MatchingEngine.on_bar(bar)` → may produce `FillEvent`s → put on queue
   - `StrategiesHandler.calculate_signals(bar)` — push window from `BacktestBarFeed.window()` to each strategy
5. Each `Strategy.calculate_signal(ticker, data)` calls `_generate_signal(ticker, action)` → puts `SignalEvent` on queue
6. `EventHandler` dispatches `SignalEvent` to `_routes[SIGNAL]`:
   - `OrderHandler.on_signal(signal)` → `OrderManager.process_signal(signal)` → constructs `Order`, validates via `EnhancedOrderValidator`, sizes position, reserves cash via `PortfolioReadModel.reserve()`, builds `OrderEvent` → `global_queue.put(order_event)`
7. `EventHandler` dispatches `OrderEvent` to `_routes[ORDER]`:
   - `ExecutionHandler.on_order(order_event)` → `SimulatedExchange.on_order(order_event)` → `MatchingEngine` receives order (rests it for next-bar fill)
8. On the next bar's `on_market_data` pass, `MatchingEngine` fires `FillDecision`/`CancelDecision` → `SimulatedExchange` applies fee/slippage → emits `FillEvent` via `global_queue`
9. `EventHandler` dispatches `FillEvent` to `_routes[FILL]` in order:
   - `PortfolioHandler.on_fill(fill)` — update positions/cash ledger (EXECUTED fills only)
   - `OrderHandler.on_fill(fill)` — reconcile order mirror; release cash reservation; emit orphan-child CANCEL events if needed
10. After the for-loop tick: `portfolio.record_metrics(time_event.time)` captures equity point

### Bracket Order Flow

1. `OrderManager` sets `parent_order_id` on child stop/limit orders and `child_order_ids` on the parent entry `OrderEvent`
2. `MatchingEngine` holds all resting orders; children are DORMANT until parent entry fills (`parent-filled gate`)
3. When parent fills (pass 1), children unlock against the same bar's high/low (pass 2)
4. The first child to trigger fills; its sibling receives an OCO `CancelDecision` — both outcomes emit via `global_queue`

### Live System Path

1. External event sources put events directly onto `global_queue` via `LiveTradingSystem.add_event()` or `TradingInterface.create_market_order()`
2. Background thread runs `_event_processing_loop()`; calls `event_handler._dispatch(event)` directly (bypassing `process_events` drain to preserve FIFO order)
3. On `TIME` events, `portfolio.record_metrics(event.time)` is called on the engine thread (single-writer contract, D-19)

## Key Abstractions

**Event dataclasses:**
- Purpose: All inter-component messages; carry full immutable context
- Location: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `PortfolioUpdateEvent`, `ErrorEvent`, `PortfolioErrorEvent`
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)`, each pins `type` via `field(default=EventType.X, init=False)`. Factory class methods (`FillEvent.new_fill`, `OrderEvent.new_order_event`) for safe construction. `event_id` is auto-generated UUIDv7.

**Strategy (ABC):**
- Purpose: Abstract base for all trading strategies
- Location: `itrader/strategy_handler/base.py`
- Pattern: Subclass implements `calculate_signal(ticker, data: pd.DataFrame)`; calls `self._generate_signal(ticker, action)` to emit `SignalEvent` onto `global_queue`. Subclasses set `self.max_window` for the feed window size.

**AbstractExchange:**
- Purpose: Pluggable exchange interface
- Location: `itrader/execution_handler/exchanges/base.py` (abstract); `itrader/execution_handler/exchanges/simulated.py` (concrete)
- Pattern: Must implement `on_order(event)`, `on_market_data(bar)`, `connect()`, `disconnect()`, `health_check()`, `validate_order(event)`

**PortfolioReadModel (Protocol):**
- Purpose: Narrow read boundary for order-domain reads of portfolio state; eliminates concrete `PortfolioHandler` import in order domain
- Location: `itrader/core/portfolio_read_model.py`
- Pattern: `runtime_checkable` Protocol; `PortfolioHandler` satisfies it structurally (no adapter). Six members: `available_cash`, `get_position`, `reserve`, `release`, `exchange_for`, `open_position_count`. `get_position` returns frozen `PositionView` (never live `Position`).

**OrderStorage:**
- Purpose: Pluggable persistence for the order mirror
- Location: `itrader/order_handler/storage/in_memory_storage.py`, `itrader/order_handler/storage/postgresql_storage.py`
- Pattern: `OrderStorageFactory.create('backtest')` → `InMemoryOrderStorage`; `OrderStorageFactory.create('live', db_url)` → `PostgreSQLOrderStorage` (deferred, raises `NotImplementedError`)

**FeeModel / SlippageModel:**
- Purpose: Pluggable cost simulation
- Location: `itrader/execution_handler/fee_model/`, `itrader/execution_handler/slippage_model/`
- Pattern: Abstract base + concrete implementations (`ZeroFeeModel`, `PercentFeeModel`, `MakerTakerFeeModel`; `ZeroSlippageModel`, `FixedSlippageModel`, `LinearSlippageModel`). Selected from `ExchangeConfig`.

**Portfolio sub-managers:**
- Purpose: Single-responsibility decomposition of `Portfolio` state
- Location: `itrader/portfolio_handler/cash/cash_manager.py`, `itrader/portfolio_handler/position/position_manager.py`, `itrader/portfolio_handler/transaction/transaction_manager.py`, `itrader/portfolio_handler/metrics/metrics_manager.py`
- Pattern: Each holds a reference to its parent `Portfolio`; called only from `Portfolio` methods, never from outside

## Entry Points

**Backtest entry point:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: Instantiate `TradingSystem(exchange, start_date, end_date, timeframe)`, add strategies/portfolios, call `.run()`
- Responsibilities: `_initialise_backtest_session()` (init universe, precompute feed windows) → `_run_backtest()` (tick loop)
- Reference script: `scripts/run_backtest.py`

**Live system entry point:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: Instantiate `LiveTradingSystem`, call `.start()`
- Responsibilities: `_initialize_live_session()` → launch `_event_processing_loop` daemon thread; supports context manager protocol

**External order injection (live):**
- Location: `itrader/trading_system/trading_interface.py` — `TradingInterface.create_market_order()`
- Triggers: Web API or external caller
- Responsibilities: Validates system is running; constructs `OrderEvent` with UUIDv7 `order_id`; puts directly onto `global_queue`

**Strategy signal emission:**
- Location: `itrader/strategy_handler/base.py` — `Strategy._generate_signal()`
- Triggers: Called inside `calculate_signal()` per bar per ticker
- Responsibilities: Build `SignalEvent` for each subscribed portfolio; put onto `global_queue`

**Package import side effect:**
- Location: `itrader/__init__.py`
- Triggers: Any `import itrader` or `from itrader import ...`
- Responsibilities: Constructs `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()` as process-wide singletons

## Architectural Constraints

- **Queue-only cross-domain communication:** Handlers must never call other handler methods directly. Cross-domain interaction happens exclusively by putting events onto `global_queue`.
- **Single-writer contract (D-19):** ALL portfolio state mutations happen on the engine thread. The `queue.Queue` is the thread boundary — other threads only enqueue events. Collection and portfolio locks were removed after this contract was formalized.
- **Import side effects:** `itrader/__init__.py` initializes `config`, `logger`, and `idgen` singletons at import time. Test fixtures must import `itrader` deliberately; unexpected initialization can break isolated tests.
- **Decimal money end-to-end:** `float` for money is a correctness defect. Enter via `to_money()` (`itrader/core/money.py`). Quantize only at money boundaries (ledger write, serialization), never on intermediate arithmetic.
- **UUIDv7 identity scheme:** All entity IDs use `itrader/core/ids.py` `NewType` aliases over `uuid.UUID`. Generated by `IDGenerator` (Rust-backed `uuid-utils`). No sequential ints on new code.
- **Immutable events:** All event dataclasses are `frozen=True`/`slots=True`. Never mutate after construction. Use factory class methods (`new_fill`, `new_order_event`) to construct.
- **Look-ahead prohibition:** Strategies must never peek beyond the `asof` time passed by `StrategiesHandler`. The `BacktestBarFeed.window()` enforces this by slicing the resampled frame at or before the bar's open timestamp. Do not call `resample()` inside strategy code.
- **Next-bar-open fill convention:** Market orders decided at tick T rest in `MatchingEngine` and fill at the OPEN of the bar stamped `T + timeframe`. There is no immediate-execution path in backtest.
- **Circular imports:** `OrderHandler` → `OrderManager` → back-reference to `OrderHandler` is avoided via constructor injection. Do not add new module-level cross-imports between handler packages.
- **Tab indentation:** Most handler modules under `itrader/` use tabs. `itrader/config/` and newer refactored modules use 4 spaces. Match the file being edited.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports and calls another handler's methods directly (e.g., `order_handler.portfolio_handler.get_position()`).
**Why it's wrong:** Bypasses the queue; breaks the single-dispatch ordering contract; creates tight coupling that prevents independent testing.
**Do this instead:** Emit an event onto `global_queue`; let `EventHandler._routes` dispatch it. For synchronous reads across the order/portfolio boundary, use the `PortfolioReadModel` Protocol at `itrader/core/portfolio_read_model.py`.

### Adding a new event type without registering it

**What happens:** A new `EventType` enum member is defined and a new event dataclass is created, but no entry is added to `EventHandler._routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on unknown event types (KB1 — silent drops are explicitly rejected). The backtest FAIL-FAST policy re-raises, aborting the run.
**Do this instead:** Add the enum to `itrader/core/enums/event.py`, add the dataclass in `itrader/events_handler/events/`, add the `__init__.py` re-export, and add a key (even an empty list) to `_routes` in `itrader/events_handler/full_event_handler.py`.

### Matching orders inside OrderHandler

**What happens:** `OrderHandler` or `OrderManager` evaluates whether a stop/limit price has triggered against bar data.
**Why it's wrong:** `MatchingEngine` is the single matching path (D-13). Duplicate matching logic produces different fill prices and diverges from the canonical next-bar-open convention.
**Do this instead:** Put the `OrderEvent` onto `global_queue`; `ExecutionHandler.on_order` routes it to `SimulatedExchange.on_order`, which rests it in `MatchingEngine._resting`. The trigger fires in the next `on_market_data` pass.

### Calling `Decimal(float_value)` directly

**What happens:** Any code that writes `Decimal(some_float)` rather than `to_money(some_float)`.
**Why it's wrong:** `Decimal(0.1)` captures the binary float repr artifact (`0.1000000000000000055511151231257827021181583404541015625`). This corrupts money arithmetic subtly and non-deterministically.
**Do this instead:** Always enter the Decimal domain via `from itrader.core.money import to_money; to_money(x)` (`itrader/core/money.py:42`).

## Error Handling

**Backtest policy — FAIL-FAST:**
- `EventHandler._on_handler_error` re-raises uncaught exceptions from any handler. A handler failure aborts the run immediately rather than silently corrupting state.

**Live policy — PUBLISH-AND-CONTINUE (seam):**
- `LiveTradingSystem._event_processing_loop` catches exceptions from `_dispatch`, increments `_stats['errors_count']`, and continues processing. Live override of `_on_handler_error` is the D-live design item.

**Domain-specific error events:**
- `PortfolioHandler._operation_context()` context manager catches failures and publishes `PortfolioErrorEvent` onto `global_queue`. Consumed by `EventHandler._routes[ERROR]` → `_log_error_event`.

**Exchange rejections:**
- `SimulatedExchange` emits `FillEvent(status=REFUSED)` on admission rejection. `OrderHandler.on_fill` reconciles the mirror (REFUSED → REJECTED) and releases the cash reservation.

## Cross-Cutting Concerns

**Logging:** structlog (`itrader/logger.py`). Each component binds `self.logger = get_itrader_logger().bind(component="ClassName")`. Severity: `info` for successful ops/init, `warning` for non-fatal skips, `error` for caught exceptions with `exc_info=True`, `debug` for per-tick tracing.

**Validation:** `EnhancedOrderValidator` at `itrader/order_handler/order_validator.py` runs admission checks via `PortfolioReadModel`. Config-layer validation uses Pydantic v2 model construction.

**Determinism:** `BacktestClock` (`itrader/core/clock.py`) advanced per tick. Seeded `random.Random` (`rng_seed=42` default from `SystemConfig`) injected into `SimulatedExchange` and slippage model. Seeded RNG shared as one instance — never re-seeded per call.

**Money precision:** `itrader/core/money.py` defines `to_money()` (entry) and `quantize()` (boundary rounding). Full 28-digit `decimal` precision through intermediate math; quantize only at ledger writes and serialization.

**Identity:** `itrader/core/ids.py` defines eight `NewType` aliases over `uuid.UUID` (`OrderId`, `PortfolioId`, `PositionId`, `TransactionId`, `StrategyId`, `ScreenerId`, `FillId`, `EventId`). Generated by `itrader/outils/id_generator.py::IDGenerator`.

---

*Architecture analysis: 2026-06-07*
