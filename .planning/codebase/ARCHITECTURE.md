<!-- refreshed: 2026-06-14 -->
# Architecture

**Analysis Date:** 2026-06-14

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          Composition / Run Layer                          │
├──────────────────────────┬───────────────────────┬───────────────────────┤
│  BacktestTradingSystem   │   LiveTradingSystem   │   TradingInterface    │
│ `backtest_trading_       │ `live_trading_        │ `trading_interface.py`│
│  system.py` (holder)     │  system.py` (threaded)│  (web/API bridge)     │
│   + BacktestRunner       │                       │                       │
│   `backtest_runner.py`   │                       │                       │
└────────────┬─────────────┴───────────┬───────────┴───────────────────────┘
             │   compose_engine()       │
             │ `trading_system/compose.py` wires one shared graph
             ▼                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                EventHandler — data-driven dispatch                        │
│         `events_handler/full_event_handler.py` (self.routes)             │
│   drains one `global_queue`; list order in routes IS execution order      │
└────┬──────────┬──────────┬───────────┬───────────┬──────────┬────────────┘
     │ TIME     │ BAR       │ SIGNAL    │ ORDER     │ FILL     │ ERROR
     ▼          ▼           ▼           ▼           ▼          ▼
┌──────────┬──────────┬──────────┬───────────┬──────────┬─────────────────┐
│ Screeners│Strategies│  Order   │ Execution │Portfolio │ _log_error_event│
│ Handler  │ Handler  │ Handler  │  Handler  │ Handler  │   (log sink)    │
│          │          │ +Manager │ +Exchange │ +managers│                 │
└──────────┴────┬─────┴────┬─────┴─────┬─────┴────┬─────┴─────────────────┘
                │ reads     │ delegates │ matches  │ delegates
                ▼           ▼           ▼          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Data engine `price_handler/` (store + feed + providers)                  │
│  Order mirror `order_handler/storage/`  |  Matching `matching_engine.py`  │
│  Portfolio state `portfolio_handler/` (cash/position/transaction/metrics) │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (list order = execution order); fail-fast error seam | `itrader/events_handler/full_event_handler.py` |
| `compose_engine` | Mode-agnostic shared wiring seam; builds the component graph into an `Engine` holder | `itrader/trading_system/compose.py` |
| `build_backtest_system` | Backtest factory: selects backends, seeds symbols (D-13), wires strategies/portfolios in spec order | `itrader/trading_system/backtest_trading_system.py` |
| `BacktestTradingSystem` | Thin holder of a pre-built `Engine` + `BacktestRunner`; exposes `run()` | `itrader/trading_system/backtest_trading_system.py` |
| `BacktestRunner` | Order-sensitive session setup + synchronous fail-fast per-tick for-loop | `itrader/trading_system/backtest_runner.py` |
| `SystemSpec` | Declarative, run-mode-agnostic spec (strategies/portfolios/data/dates) the factory consumes | `itrader/trading_system/system_spec.py` |
| `LiveTradingSystem` | Live composition root; background processing thread + start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per BAR; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | Coordinator over four collaborators; owns storage; no queue access (returns `OperationResult`s) | `itrader/order_handler/order_manager.py` |
| `AdmissionManager` | Signal→order admission: direction/max-positions/increase gates, sizing, validation, cash reservation | `itrader/order_handler/admission/admission_manager.py` |
| `BracketManager` | Bracket (SLTP/OCO) assembly and pending-bracket book | `itrader/order_handler/brackets/bracket_manager.py` |
| `LifecycleManager` | `modify_order` / `cancel_order` entry points | `itrader/order_handler/lifecycle/lifecycle_manager.py` |
| `ReconcileManager` | Fill-reconciliation: mirror EXECUTED→FILLED, CANCELLED, REFUSED→REJECTED; cash release | `itrader/order_handler/reconcile/reconcile_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol implementation | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

**Overall:** Event-driven, queue-only architecture with a data-driven dispatch table and a declarative-spec + factory composition root.

**Key Characteristics:**
- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler.routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Routing changes happen only there.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Shared mode-agnostic wiring seam.** `compose_engine` builds the graph; mode-specific factories (`build_backtest_system`, a future `build_live_system`) select backends and pass them in.
- **Facade → coordinator → collaborators.** `OrderHandler` (facade) → `OrderManager` (coordinator) → four single-responsibility managers (`admission`/`brackets`/`lifecycle`/`reconcile`).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol) and `BacktestBarFeed` are injected as read-models; the queue-only rule governs handler writes, not read-models.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.

## Layers

**Composition / Run layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `compose_engine` + `Engine` holder (`compose.py`), `BacktestTradingSystem` + `build_backtest_system` (`backtest_trading_system.py`), `BacktestRunner` (`backtest_runner.py`), `SystemSpec` (`system_spec.py`), `LiveTradingSystem`, `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`, `universe`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers, the e2e harness.

**Event dispatch layer:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run drivers (`BacktestRunner`, `LiveTradingSystem`).

**Domain handler layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes + fat coordinators/managers/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data engine layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.

**Shared core layer:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `commission_estimator.py`, `bar.py`, `sizing.py`, `constants.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`, `CommissionEstimator`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Config layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, `OrderConfig`, `Settings` (env layer), `deep_merge`/`merge` helpers, exchange presets.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`, `OrderManager`, the composition layer.

**Singleton bootstrap:**
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `BacktestRunner._initialise_backtest_session` — derive membership → `feed.bind` → derive ping grid → `time_generator.set_dates` → per-strategy `feed.precompute` (`itrader/trading_system/backtest_runner.py:46`)
2. Per tick: `clock.set_time` → `global_queue.put(time_event)` → `event_handler.process_events()` (`itrader/trading_system/backtest_runner.py:95`)
3. TIME route → `screeners_handler.screen_markets` + `feed.generate_bar_event` (emits `BarEvent`) (`itrader/events_handler/full_event_handler.py:69`)
4. BAR route → `portfolio_handler.update_portfolios_market_value` (mark-to-market) → `execution_handler.on_market_data` (resting-order matching → `FillEvent`) → `strategies_handler.calculate_signals` (`itrader/events_handler/full_event_handler.py:73`)
5. SIGNAL route → `order_handler.on_signal` → `OrderManager`/`AdmissionManager` validate + size → emit `OrderEvent` (`itrader/events_handler/full_event_handler.py:78`)
6. ORDER route → `execution_handler.on_order` → exchange fills or rests → `FillEvent` (`itrader/events_handler/full_event_handler.py:79`)
7. FILL route → `portfolio_handler.on_fill` (positions/cash) → `order_handler.on_fill` (mirror reconcile) (`itrader/events_handler/full_event_handler.py:80`)
8. Post-events: `portfolio.record_metrics(time_event.time)` DIRECT call (never an event reroute) → optional `on_tick` operator hook (`itrader/trading_system/backtest_runner.py:102`)
9. Run end: `order_handler.expire_all_resting()` → one final `process_events()` drain sweeps resting orders to EXPIRED (`itrader/trading_system/backtest_runner.py:118`)

### Live Trading Path

1. `LiveTradingSystem.start()` wires the same component graph and launches a daemon processing thread (`itrader/trading_system/live_trading_system.py`)
2. The thread drains `global_queue` via `event_handler.process_events()` with `queue_timeout`/`max_idle_time` lifecycle
3. `_on_handler_error` is overridden to publish-and-continue (emit `ErrorEvent`, keep draining) instead of re-raising
4. `TradingInterface` validates running state and enqueues externally-created `OrderEvent`s (bypasses the domain validator — see Anti-Patterns / CONVENTIONS dual-validator note)

### Bracket / Resting-Order Flow

1. `AdmissionManager` admits a signal and `BracketManager` declares a bracket via `parent_order_id`/`child_order_ids` (the order handler NEVER matches)
2. `SimulatedExchange` rests stop/limit children in `MatchingEngine._resting` (one book per exchange)
3. On each BAR, `MatchingEngine` evaluates triggers against intrabar high/low with gap-aware fills and same-bar OCO priority; `SimulatedExchange` applies fee/slippage and emits the `FillEvent`
4. `ReconcileManager` reconciles the stored order mirror from the `FillEvent` (EXECUTED→FILLED, CANCELLED, REFUSED→REJECTED) and releases reserved cash

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `postgresql`).
- Pending brackets: `BracketBook` (`order_handler/brackets/bracket_book.py`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `LiveTradingSystem` status lock + `threading.Event`.

## Key Abstractions

**Event:**
- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent` (`market.py`), `SignalEvent` (`signal.py`), `OrderEvent` (`order.py`), `FillEvent` (`fill.py`), `ErrorEvent`/`PortfolioErrorEvent` (`error.py`); base in `base.py`.
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.

**SystemSpec:**
- Purpose: Declarative, run-mode-agnostic description of WHAT to run, consumed by the factory.
- Examples: `itrader/trading_system/system_spec.py` — `SystemSpec`, `PortfolioSpec`, `Action`.
- Pattern: Frozen dataclass; `build_backtest_system(spec)` reads it by name.

**Strategy:**
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, `empty_strategy.py`; user strategies under `my_strategies/`.
- Pattern: Subclass implements `calculate_signal(...)`; emits a `SignalEvent` onto `global_queue`.

**Exchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py` (`AbstractExchange`); concrete `SimulatedExchange`.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.

**PortfolioReadModel:**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — `available_cash`, `get_position`, `reserve`, `release`, `total_equity`, `open_position_count`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.

**CommissionEstimator:**
- Purpose: `(quantity, price) -> Decimal` estimate for the admission cash-reservation gate.
- Examples: `itrader/core/commission_estimator.py` (Protocol); `FeeModelCommissionEstimator` adapter in `compose.py` (late-binds `exchange.fee_model`).

**PriceStore / Feed:**
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`.
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, positional slice per tick).

**OrderStorage / SignalStore:**
- Purpose: Pluggable order-mirror and signal-record persistence.
- Examples: `itrader/order_handler/storage/` (`in_memory_storage.py`, `postgresql_storage.py`, `storage_factory.py`); `itrader/strategy_handler/storage/`.

**Fee / Slippage models:**
- Purpose: Pluggable execution cost.
- Examples: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`), `slippage_model/` (`zero`, `fixed`, `linear`).

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `BacktestTradingSystem.run()` / `build_backtest_system(spec)`
- Triggers: `scripts/run_backtest.py` (`make backtest`), the e2e harness, notebooks.
- Responsibilities: Build the engine (`compose_engine`), construct `BacktestRunner`, drive the for-loop, print/record metrics.

**Live run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch processing thread, manage lifecycle.

**External order API:**
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.

**Strategy signal emission:**
- Location: `itrader/strategy_handler/base.py` — strategy `calculate_signal` → `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop in `BacktestRunner`; no locking needed for correctness. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses a lock for config updates.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this. `full_event_handler.py` keeps the events package import `TYPE_CHECKING`-only so loading the dispatcher does not pull pandas.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` and the four order collaborators resolve by constructor injection, not module-level cross-imports. Avoid new module-level cross-imports between handlers.
- **Wiring order is byte-exact-sensitive:** `compose_engine` builds components in a pinned order (execution handler BEFORE order handler so the commission estimator can adapt the exchange's fee model); `BacktestRunner._initialise_backtest_session` is order-sensitive (membership → bind → ping-grid → set_dates → precompute). Do not reorder.
- **Bar-timing contract:** the rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler and `trading_system/` modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports and calls another handler's method to read or mutate its state.
**Why it's wrong:** Breaks the queue-only contract; couples domains and bypasses the single dispatch order, corrupting determinism and the audit trail.
**Do this instead:** Emit an event onto `global_queue`; for reads use an injected read-model (`PortfolioReadModel` in `itrader/core/portfolio_read_model.py`, or `BacktestBarFeed`).

### Adding a new event type without registering it

**What happens:** A new frozen event dataclass is defined and emitted, but `EventHandler.routes` and `core/enums/event.py::EventType` are not updated.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on an unrouted type (`itrader/events_handler/full_event_handler.py:120`) — silent drops are a tampering risk.
**Do this instead:** Define the dataclass under `events_handler/events/<domain>.py`, add the `EventType` member, and add a `routes` entry in `full_event_handler.py`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Order-handler code evaluates stop/limit triggers or decides fills itself.
**Why it's wrong:** Matching is the execution layer's responsibility; the exchange holds the resting-order book and is the source of truth for fills.
**Do this instead:** Declare brackets via `parent_order_id`/`child_order_ids` in `BracketManager`; let `MatchingEngine`/`SimulatedExchange` match, and reconcile the mirror from `FillEvent`s in `ReconcileManager`.

### Float arithmetic on money

**What happens:** A monetary value is computed with `float` or constructed via `Decimal(float)`.
**Why it's wrong:** Binary-float repr artifacts make results non-reproducible; float-for-money is a locked correctness defect.
**Do this instead:** Enter the Decimal domain via `to_money(x)` and round only at money boundaries with `quantize(...)` (`itrader/core/money.py`).

### Reordering the composition / session-setup steps

**What happens:** Wiring in `compose_engine` or setup steps in `BacktestRunner` are reordered for readability.
**Why it's wrong:** The order is byte-exact-sensitive (commission-estimator late binding, ping-grid derivation, registration-order precompute) and breaks the golden-master oracle.
**Do this instead:** Treat both sequences as fixed; tidy in place without changing order (`compose.py`, `backtest_runner.py`).

## Error Handling

**Strategy:** Run-mode-split — backtest is fail-fast (re-raise), live is publish-and-continue (emit `ErrorEvent`, keep draining).

**Patterns:**
- `EventHandler._on_handler_error` re-raises in backtest; `LiveTradingSystem` overrides it to publish-and-continue (`full_event_handler.py:129`).
- `EventHandler._log_error_event` is the ERROR-route consumer (structured log sink, severity-mapped).
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles (no exception across the queue).
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`, `strategy.py`).

## Cross-Cutting Concerns

**Logging:** structlog via `get_itrader_logger().bind(component="...")`; bound per component as `self.logger`.
**Validation:** `EnhancedOrderValidator` (`order_handler/order_validator.py`) at admission; `SimulatedExchange.validate_order` as defense-in-depth on the live/`TradingInterface` path (dual-layer overlap is justified-by-decision, see CONVENTIONS.md); Pydantic config validation in `config/`.
**Authentication:** Not applicable to the backtest engine; live providers read credentials from `.env` / `oanda.cfg`.
**Determinism:** seeded `random.Random` + injected `BacktestClock` threaded through wiring.

---

*Architecture analysis: 2026-06-14*
