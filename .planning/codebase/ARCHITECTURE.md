<!-- refreshed: 2026-06-03 -->
# Architecture

**Analysis Date:** 2026-06-03

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                           Entry Points                                   │
│   TradingSystem (backtest)         LiveTradingSystem (live)              │
│   `itrader/trading_system/         `itrader/trading_system/              │
│    backtest_trading_system.py`      live_trading_system.py`              │
│           │ synchronous for-loop        │ background thread              │
└───────────┴────────────────────────────┴────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    global_queue  (queue.Queue — FIFO)                    │
│                `itrader/events_handler/event.py`                         │
│         PingEvent │ BarEvent │ SignalEvent │ OrderEvent │ FillEvent       │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                EventHandler.process_events()                             │
│          `itrader/events_handler/full_event_handler.py`                  │
│   Drains queue; dispatches each EventType to correct handler method      │
└────────┬─────────┬───────────────┬───────────────┬────────────────┬─────┘
         │         │               │               │                │
    PING │    BAR  │          SIGNAL│         ORDER │           FILL │
         ▼         ▼               ▼               ▼                ▼
  ScreenersHandler  Portfolio+      OrderHandler   ExecutionHandler  Portfolio+
  Universe           Execution+                                      OrderHandler
  (generate BAR)     Strategies
```

## Component Responsibilities

| Component | Responsibility | Primary File |
|-----------|----------------|--------------|
| `EventHandler` | Queue drain; event dispatch by type | `itrader/events_handler/full_event_handler.py` |
| `StrategiesHandler` | Run all strategies per bar; emit SignalEvents | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening; update symbol universe | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: signal→orders, fill reconciliation | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route OrderEvents to exchanges; drive resting-order matching | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders immediately; rest stop/limit in MatchingEngine | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; thread-safe collection; on_fill routing | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to four sub-managers | `itrader/portfolio_handler/portfolio.py` |
| `Universe` | Tracks full tradable symbol set; generates BarEvents | `itrader/universe/dynamic.py` |
| `PriceHandler` | Data download/storage; resampled bar access | `itrader/price_handler/data_provider.py` |
| `TradingInterface` | Bridge between external/web API and LiveTradingSystem | `itrader/trading_system/trading_interface.py` |

## Pattern Overview

**Overall:** Event-Driven Architecture with domain-separated handler components.

**Key Characteristics:**
- All inter-component communication flows through a single `queue.Queue` (`global_queue`); direct cross-domain calls are forbidden.
- Each handler receives the `global_queue` as a constructor argument and puts events onto it — never calls other handlers.
- Stateless event dataclasses carry all context; handlers are stateful (they own storage, positions, etc.).
- The matching/execution layer is the sole source of truth for fills; the order handler only reconciles its mirror.

## Layers

**Trading System Layer:**
- Purpose: Wires all components together; drives the run loop.
- Location: `itrader/trading_system/`
- Contains: `TradingSystem` (backtest for-loop), `LiveTradingSystem` (threaded), `TradingInterface` (API bridge), `PingGenerator`.
- Depends on: All handlers, `EventHandler`, `PriceHandler`, `Universe`.
- Used by: External callers, notebooks, web APIs.

**Event Dispatch Layer:**
- Purpose: Drain the queue and route events to the correct handler methods.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`.
- Depends on: All handlers.
- Used by: Both trading system run loops.

**Domain Handler Layer:**
- Purpose: Encapsulate domain logic (strategy signals, orders, execution, portfolios).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Public handler classes and their sub-managers/sub-components.
- Depends on: `events_handler/event.py`, `core/`, shared `global_queue`.
- Used by: `EventHandler`.

**Core / Shared Layer:**
- Purpose: Cross-cutting enums, exceptions, and identifiers used by all handlers.
- Location: `itrader/core/enums/`, `itrader/core/exceptions/`, `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `OrderCommand`, `PortfolioState`, `IDGenerator`.
- Depends on: Nothing inside itrader.
- Used by: All handlers.

**Configuration Layer:**
- Purpose: Domain-based configuration registry with YAML-backed presets.
- Location: `itrader/config/`
- Contains: `ConfigRegistry`, `ConfigProvider`, domain configs (`portfolio`, `trading`, `data`, `system`, `exchange`).
- Depends on: `settings/` YAML files (gitignored in production).
- Used by: `PortfolioHandler`, `SimulatedExchange`, and `itrader/__init__.py`.

**Process-Wide Singletons (module import side-effect):**
- Location: `itrader/__init__.py`
- Initialised on first import: `config` (system config), `logger` (structlog), `idgen` (`IDGenerator`).
- Modules import them with: `from itrader import config, idgen` or `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `TradingSystem.run()` calls `_initialise_backtest_session()` then `_run_backtest()` (`itrader/trading_system/backtest_trading_system.py:99`)
2. For each timestamp, `PingGenerator` yields a `PingEvent`; it is placed onto `global_queue`.
3. `EventHandler.process_events()` drains the queue (`itrader/events_handler/full_event_handler.py:54`).
4. `PING` → `ScreenersHandler.screen_markets()` + `Universe.generate_bar_event()` → `BarEvent` pushed onto queue.
5. `BAR` → `PortfolioHandler.update_portfolios_market_value()` + `ExecutionHandler.on_market_data()` (resting order matching) + `StrategiesHandler.calculate_signals()` → may produce `SignalEvent`.
6. `SIGNAL` → `OrderHandler.on_signal()` → `OrderManager.process_signal()` → one or more `OrderEvent`s pushed onto queue.
7. `ORDER` → `ExecutionHandler.on_order()` → routes to `SimulatedExchange.on_order()`. Market orders: `execute_order()` immediately emits `FillEvent`. Stop/Limit orders: `MatchingEngine.submit()` rests them.
8. `FILL` → `PortfolioHandler.on_fill()` (EXECUTED only: update positions/cash) + `OrderHandler.on_fill()` (reconcile order mirror: FILLED/CANCELLED/REJECTED).

### Live Trading Path

1. `LiveTradingSystem.start()` launches `_event_processing_loop()` on a daemon thread (`itrader/trading_system/live_trading_system.py:192`).
2. Thread blocks on `global_queue.get(timeout=queue_timeout)`.
3. On receipt, puts the event back and calls `EventHandler.process_events()` — same dispatch as backtest.
4. External order creation via `TradingInterface.create_market_order()` puts an `OrderEvent` directly on the queue (`itrader/trading_system/trading_interface.py:69`).

### Bracket Order Flow

1. Strategy sets `stop_loss` / `take_profit` on a `SignalEvent`.
2. `OrderManager.process_signal()` creates a parent market/limit order and child stop-loss / take-profit orders with `parent_order_id` / `child_order_ids` linkage.
3. Child `OrderEvent`s are put on queue; `MatchingEngine` rests them.
4. When one child fills, the exchange enforces OCO: the sibling receives a `CANCELLED` fill.

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio` instance, protected by a per-portfolio `threading.RLock` (`itrader/portfolio_handler/portfolio.py:59`).
- Portfolio collection: protected by a `readerwriterlock.RWLockFair` in `PortfolioHandler` (`itrader/portfolio_handler/portfolio_handler.py:66`).
- Order book (resting orders): `MatchingEngine._resting` dict, single-threaded in backtest, protected by `SimulatedExchange._lock` in live (`itrader/execution_handler/exchanges/simulated.py:75`).
- System run status: `LiveTradingSystem._status_lock` + `threading.Event` for stop signalling.

## Key Abstractions

**Event Dataclasses:**
- Purpose: All inter-component messages; carry full context.
- Examples: `itrader/events_handler/event.py` — `PingEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`.
- Pattern: Python `@dataclass` with a class-level `type = EventType.X` attribute. Factory class methods (`FillEvent.new_fill`, `OrderEvent.new_order_event`) for safe construction.

**Strategy Base:**
- Purpose: Abstract base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py` — `Strategy`.
- Pattern: Subclass implements `calculate_signal(ticker, data)`; calls `_generate_signal()` to emit `SignalEvent` onto `global_queue`.

**AbstractExchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py` — `AbstractExchange`; concrete: `SimulatedExchange` (`itrader/execution_handler/exchanges/simulated.py`).
- Pattern: Must implement `on_order(event)`, `on_market_data(bar)`, `connect()`, `disconnect()`, `health_check()`, `validate_order(event)`.

**OrderStorage:**
- Purpose: Pluggable persistence for the order mirror.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `itrader/order_handler/storage/postgresql_storage.py`.
- Pattern: `OrderStorageFactory.create('backtest')` → `InMemoryOrderStorage`; `OrderStorageFactory.create('live', db_url)` → `PostgreSQLStorage` (not yet fully implemented).

**Portfolio Sub-Managers:**
- Purpose: Decompose `Portfolio` into four single-responsibility managers.
- Examples: `CashManager` (`itrader/portfolio_handler/cash_manager.py`), `PositionManager` (`itrader/portfolio_handler/position_manager.py`), `TransactionManager` (`itrader/portfolio_handler/transaction_manager.py`), `MetricsManager` (`itrader/portfolio_handler/metrics_manager.py`).
- Pattern: Each manager holds a reference to its parent `Portfolio` instance; called only from `Portfolio` methods, never from outside.

## Entry Points

**Backtest Run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.run()`
- Triggers: Instantiate `TradingSystem`, add strategies/portfolios, call `.run()`.
- Responsibilities: Initialise universe + price data, iterate `PingGenerator`, drain queue per tick, record metrics.

**Live Trading Run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: Instantiate `LiveTradingSystem`, call `.start()`.
- Responsibilities: Initialise universe, launch background processing thread, manage lifecycle (start/stop/status).

**External Order Creation (Live):**
- Location: `itrader/trading_system/trading_interface.py` — `TradingInterface.create_market_order()`
- Triggers: Web API or external caller.
- Responsibilities: Validate system is running; construct `OrderEvent`; put directly onto `global_queue`.

**Strategy Signal Generation:**
- Location: `itrader/strategy_handler/base.py` — `Strategy._generate_signal()`
- Triggers: Called inside `calculate_signal()` which is called by `StrategiesHandler.calculate_signals()` per bar.
- Responsibilities: Build `SignalEvent` for each subscribed portfolio; put onto `global_queue`.

## Architectural Constraints

- **Queue-only cross-domain communication:** Handlers must never call other handler methods directly. Cross-domain interaction happens exclusively by putting events onto `global_queue`.
- **Import side effects:** `itrader/__init__.py` initializes `config`, `logger`, and `idgen` singletons at import time. Any module that imports from `itrader` triggers this. Do not import `itrader` in test fixtures without understanding this.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`. `MatchingEngine._resting` is instance-level (one per `SimulatedExchange`).
- **Circular imports:** `OrderHandler` → `OrderManager` → `OrderHandler` (reference passed in constructor, not import). Avoid adding new module-level cross-imports between handlers.
- **Threading (live mode):** Event processing runs on one daemon thread. Portfolio collection uses `rwlock`; individual portfolios use `threading.RLock`. `SimulatedExchange` uses `threading.RLock` for config updates.
- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness, but `PortfolioHandler` still acquires locks for API compatibility.
- **Tab indentation:** Most handler modules use tabs. `config/` and some newer modules use spaces. Match the indentation of the file being edited.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A strategy or order handler calls `portfolio_handler.get_portfolio(id)` to make a decision mid-signal.
**Why it's wrong:** Creates tight coupling; breaks the queue-only communication contract; causes ordering bugs when the portfolio state hasn't yet been updated by the current bar's `FILL` events.
**Do this instead:** Emit a `SignalEvent` or `OrderEvent`; let the correct handler respond in the correct dispatch order defined in `EventHandler.process_events()`.

### Adding a new event type without registering it

**What happens:** A new `@dataclass` is created in `event.py` with a `type` attribute but the `EventType` enum is not extended and `process_events()` has no branch for it.
**Why it's wrong:** The event lands in the `else: raise NotImplemented(...)` branch at runtime.
**Do this instead:** Define the dataclass in `itrader/events_handler/event.py`, add the name to `EventType = Enum("EventType", "... NEWTYPE")`, and add `elif event.type == EventType.NEWTYPE:` in `full_event_handler.py`.

### Matching orders inside OrderHandler

**What happens:** OrderHandler or OrderManager evaluates stop/limit triggers against bar prices and emits fills directly.
**Why it's wrong:** The exchange (`SimulatedExchange` / `MatchingEngine`) is the sole source of truth for fills; duplicating trigger logic causes double-fills and OCO inconsistencies.
**Do this instead:** `OrderHandler.on_signal()` → emit `OrderEvent` with correct `order_type` (STOP/LIMIT). `ExecutionHandler.on_market_data()` → `MatchingEngine.on_bar()` → matching engine emits `FillDecision`; `SimulatedExchange` enqueues `FillEvent`.

## Error Handling

**Strategy:** Exceptions in `PortfolioHandler` operations are caught, published as `PortfolioErrorEvent` (reuses `EventType.UPDATE`), and re-raised. `LiveTradingSystem` catches exceptions in the event loop, increments `errors_count`, and continues processing.

**Patterns:**
- `PortfolioHandler._operation_context()` context manager tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange.execute_order()` returns `ExecutionResult(success=False, ...)` on rejection and emits `FillEvent(REFUSED)` so the order mirror can reconcile.
- `ExecutionHandler.on_order()` and `on_market_data()` catch exceptions per exchange and log; they do not re-raise (prevents queue stalls).

## Cross-Cutting Concerns

**Logging:** structlog, initialized in `itrader/__init__.py` via `init_logger(config)`. Each component calls `get_itrader_logger().bind(component="ComponentName")` to get a bound logger. Do not use `print()` or the standard `logging` module directly.

**ID Generation:** `IDGenerator` in `itrader/outils/id_generator.py`, accessed via the `idgen` singleton. Call `idgen.generate_portfolio_id()`, `idgen.generate_strategy_id()`, `idgen.generate_transaction_id()`.

**Validation:** `EnhancedOrderValidator` in `itrader/order_handler/order_validator.py`; used by `OrderHandler` and `OrderManager`. Portfolio validators in `itrader/portfolio_handler/validators.py`.

**Configuration:** Domain-based, registry-driven. Access via convenience functions in `itrader/config/__init__.py`: `get_portfolio_config_provider()`, `get_exchange_preset('default')`, etc. YAML sources live in `settings/domains/`.

---

*Architecture analysis: 2026-06-03*
