<!-- refreshed: 2026-06-22 -->
# Architecture

**Analysis Date:** 2026-06-22

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Entry Points / Run Modes                               │
│  BacktestTradingSystem.run()          LiveTradingSystem.start()               │
│  itrader/trading_system/backtest_trading_system.py  live_trading_system.py   │
│  Synchronous for-loop (BacktestRunner) | Daemon thread (queue.get timeout)   │
└─────────────────────────────┬────────────────────────────────────────────────┘
                              │  events on global_queue (queue.Queue)
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           EventHandler                                        │
│  itrader/events_handler/full_event_handler.py                                 │
│  _routes: dict[EventType, list[Callable]]  —  list order IS execution order   │
└───┬───────────────┬───────────────┬───────────────┬──────────────────────────┘
    │ TIME          │ BAR           │ SIGNAL        │ ORDER / FILL / ERROR
    ▼               ▼               ▼               ▼
┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐
│Screeners │  │Portfolio     │  │ Order        │  │ Execution               │
│Handler   │  │Handler       │  │ Handler      │  │ Handler                 │
│(deferred)│  │(mark+carry+  │  │(on_signal → │  │(on_order / on_market_   │
│          │  │ liquidation  │  │ OrderEvent)  │  │  data → FillEvent)      │
│feed.     │  │  check)      │  │(on_fill →   │  │ SimulatedExchange        │
│generate_ │  │(on_fill →    │  │ reconcile)  │  │  └── MatchingEngine      │
│bar_event │  │ positions)   │  │             │  │  └── FeeModel            │
└──────────┘  └──────────────┘  └──────────────┘  └── SlippageModel         │
                                                    └─────────────────────────┘
                              │ read-models (not queue)
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│   StrategiesHandler  (BAR route — calculate_signals → SignalEvent)            │
│   itrader/strategy_handler/strategies_handler.py                              │
│   Strategy / PairStrategy base  →  concrete: SMA_MACD, EthBtcPairStrategy    │
└──────────────────────────────────────────────────────────────────────────────┘
                              │ read-model (not queue)
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│   Data Layer                                                                  │
│   CsvPriceStore  (eager-load)  →  BacktestBarFeed (look-ahead-safe slices)   │
│   itrader/price_handler/store/csv_store.py                                    │
│   itrader/price_handler/feed/bar_feed.py                                      │
└──────────────────────────────────────────────────────────────────────────────┘
                              │ read-only
                              ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│   Core / Config (depend on nothing inside itrader)                            │
│   itrader/core/  —  enums, exceptions, ids, money, clock, instrument,        │
│                      portfolio_read_model, sizing, bar                        │
│   itrader/config/ — SystemConfig, PortfolioConfig, ExchangeConfig, OrderConfig│
└──────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self._routes` (list order = execution order); fail-fast/publish-and-continue error seam | `itrader/events_handler/full_event_handler.py` |
| `BacktestTradingSystem` | Thin holder of pre-built `Engine` + `BacktestRunner`; exposes `run()` | `itrader/trading_system/backtest_trading_system.py` |
| `build_backtest_system(spec)` | Factory: selects mode-specific backends, seeds symbol set, calls `compose_engine`, adds strategies/portfolios | `itrader/trading_system/backtest_trading_system.py` |
| `compose_engine(...)` | Shared, mode-agnostic wiring seam: instantiates every handler around one queue | `itrader/trading_system/compose.py` |
| `BacktestRunner` | Drives the synchronous fail-fast for-loop; `_initialise_backtest_session` (membership, bind, ping-grid, precompute); `_run_backtest` (per-tick clock/queue/dispatch/metrics/on_tick) | `itrader/trading_system/backtest_runner.py` |
| `LiveTradingSystem` | Background daemon thread; start/stop/status lifecycle; overrides `_on_handler_error` with publish-and-continue | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and live system | `itrader/trading_system/trading_interface.py` |
| `SystemSpec` / `PortfolioSpec` / `Action` | Declarative, frozen value objects consumed by the factory | `itrader/trading_system/system_spec.py` |
| `TimeGenerator` | Yield `TimeEvent`s across the union ping-grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per bar; dispatch `PairStrategy` via `_dispatch_pair`; fan signal intents per portfolio; enqueue `SignalEvent` | `itrader/strategy_handler/strategies_handler.py` |
| `Strategy` (ABC) | Pure-alpha abstract base: declares sizing policy / direction / tickers as class attrs; implements `generate_signal` | `itrader/strategy_handler/base.py` |
| `PairStrategy` (ABC) | Two-leg pure-alpha base: declares pair of tickers, `entry_z`/`exit_z`/`z_lookback`/`beta_warmup`; implements `evaluate_pair` | `itrader/strategy_handler/pair_base.py` |
| `SMA_MACD_strategy` | Reference long-only golden strategy | `itrader/strategy_handler/strategies/SMA_MACD_strategy.py` |
| `EthBtcPairStrategy` | Reference pair strategy: log-OLS β-weighted ETH/BTC spread, z-score band trigger | `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py` |
| `OrderHandler` | Thin interface: `on_signal` → delegates to `OrderManager`; `on_fill` → delegates to reconcile; `cancel_order` / `modify_order` / `expire_all_resting` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | Coordinator: delegates to `AdmissionManager`, `BracketManager`, `LifecycleManager`, `ReconcileManager`; returns `OperationResult` carrying `OrderEvent`s; never touches the queue | `itrader/order_handler/order_manager.py` |
| `AdmissionManager` | Signal→order pipeline: direction gate → max_positions → increase gate → sizing → entity construction → cash reservation | `itrader/order_handler/admission/admission_manager.py` |
| `BracketBook` / `BracketManager` | Pending-bracket map (`_PendingBracket`) + bracket-assembly seam (PercentFromFill child construction on parent fill) | `itrader/order_handler/brackets/bracket_book.py`, `bracket_manager.py` |
| `LifecycleManager` | Modify / cancel / expire operations on the order mirror | `itrader/order_handler/lifecycle/lifecycle_manager.py` |
| `ReconcileManager` | Reconcile order mirror from `FillEvent` status (`EXECUTED`→`FILLED`, `CANCELLED`, `REFUSED`→`REJECTED`, `EXPIRED`) | `itrader/order_handler/reconcile/reconcile_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s and `BarEvent`s to named exchanges via `on_order` / `on_market_data`; swallow per-exchange exceptions | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit/trailing-stop; apply fee/slippage; emit `FillEvent`; compose `MatchingEngine` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger evaluation; OCO priority; trailing-stop ratchet (`TrailState`); gap-aware fills | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `update_portfolios_market_value` (mark→carry→liquidation pass); `on_fill` routing; `PortfolioReadModel` Protocol implementation | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to `CashManager`, `PositionManager`, `TransactionManager`, `MetricsManager`; shares `PortfolioStateStorage` | `itrader/portfolio_handler/portfolio.py` |
| `CashManager` | Cash balance; reservations (per-`OrderId`); audit trail (`CashOperation`) | `itrader/portfolio_handler/cash/cash_manager.py` |
| `PositionManager` | Open/close positions; scale-in/out; market-value update; carry accrual dispatch | `itrader/portfolio_handler/position/position_manager.py` |
| `Position` | Per-open-position state; `leverage` (isolated margin); `_last_accrual_time` (borrow carry) | `itrader/portfolio_handler/position/position.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar-window read-model; `precompute` once per strategy at session init; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `Universe` | Thin facade over `members` list + `Instrument` map; injected into exchange, order handler, portfolio handler | `itrader/universe/universe.py` |
| `Instrument` | Frozen per-symbol value object: `price_precision`, `quantity_precision`, `min_order_size`, `maintenance_margin_rate`, `max_leverage`, `borrow_rate`, `liquidation_fee_rate` | `itrader/core/instrument.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam); set to bar business time per tick | `itrader/core/clock.py` |
| `Engine` | Dumb dataclass holder of all wired components returned by `compose_engine` | `itrader/trading_system/compose.py` |

## Pattern Overview

**Overall:** Queue-mediated event-driven architecture with data-driven dispatch.

**Key Characteristics:**
- All handler-to-handler writes go through `global_queue` (a `queue.Queue`); direct cross-domain calls are forbidden.
- Dispatch is a single reviewable `dict[EventType, list[Callable]]` literal in `EventHandler._routes`; list order IS execution order.
- Events are frozen dataclasses (`frozen=True, slots=True, kw_only=True`); they carry a UUIDv7 `event_id` and a business `time` (never wall clock).
- Read-model seams bypass the queue for synchronous reads: `PortfolioReadModel` Protocol (order domain reads portfolios) and `BacktestBarFeed` (strategies read price windows).
- Money is `Decimal` end-to-end; `float()` appears only at serialization/logging edges.
- Determinism: one seeded `random.Random` (seed from `config.performance.rng_seed`, default 42) injected at wiring; an injected `BacktestClock` staged on the determinism seam.
- Handler/Manager split: `<Domain>Handler` (thin event interface, queue access) + `<Domain>Manager` (business logic, no queue, returns `OperationResult`).

## Layers

**Composition / Run Layer:**
- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: `BacktestTradingSystem`, `LiveTradingSystem`, `TradingInterface`, `BacktestRunner`, `TimeGenerator`, `SystemSpec`, `compose_engine`, `Engine`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers.

**Dispatch Layer:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain Handler Layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`
- Contains: Thin handler classes (queue-aware) + manager/sub-component collaborators (queue-blind).
- Depends on: `events_handler/events/`, `core/`, `global_queue`.
- Used by: `EventHandler`.

**Data / Price Layer:**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event`.

**Core Layer:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, instrument, read-model protocols.
- Location: `itrader/core/`
- Contains: `OrderType`, `OrderStatus` + `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `PositionSide`, `IDGenerator`, `PortfolioReadModel`, `Instrument`, `money.py`, `clock.py`, `sizing.py`, `bar.py`, `constants.py`, `commission_estimator.py`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.

**Config Layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig` + `TradingRules`, `ExchangeConfig`, `OrderConfig` + `TrailType`. Registry/provider getters were removed (M2-06); `SystemConfig.default()` constructed directly.
- Depends on: `pydantic`, `pydantic-settings`, optional YAML in `settings/`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`, `OrderHandler`.

**Process-wide Singletons:**
- Location: `itrader/__init__.py`
- Initialized on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `BacktestRunner._initialise_backtest_session()`: derive membership → `Universe` build → inject into exchange / order handler / portfolio handler → `feed.bind(universe.members)` → ping-grid union → `time_generator.set_dates` → per-strategy `feed.precompute` (`itrader/trading_system/backtest_runner.py:47`)
2. `BacktestRunner._run_backtest()`: for each `TimeEvent` from `TimeGenerator` → `clock.set_time` → `queue.put(time_event)` → `event_handler.process_events()` → `portfolio.record_metrics(bar_time)` → optional `on_tick` hook (`itrader/trading_system/backtest_runner.py:130`)
3. TIME route: `screeners_handler.screen_markets(time_event)` + `feed.generate_bar_event(time_event)` → `BarEvent` on queue (`itrader/events_handler/full_event_handler.py:69`)
4. BAR route (in order): `portfolio_handler.update_portfolios_market_value(bar_event)` → `execution_handler.on_market_data(bar_event)` → `strategies_handler.calculate_signals(bar_event)` (`itrader/events_handler/full_event_handler.py:74`)
5. `update_portfolios_market_value`: mark positions at close → per-short borrow-carry accrual → liquidation breach pass (`itrader/portfolio_handler/portfolio_handler.py:727`)
6. `execution_handler.on_market_data` → `SimulatedExchange.on_bar` → `MatchingEngine.on_bar` → `FillDecision`/`CancelDecision` list → `SimulatedExchange` applies fee/slippage → `FillEvent` on queue (`itrader/execution_handler/matching_engine.py`)
7. SIGNAL route: `order_handler.on_signal(signal_event)` → `OrderManager.on_signal` → `AdmissionManager.process_signal` (gates + sizing + cash reservation) → `OrderEvent` on queue (`itrader/order_handler/admission/admission_manager.py`)
8. ORDER route: `execution_handler.on_order(order_event)` → `SimulatedExchange.on_order` → rest in `MatchingEngine._resting` → market orders fill next bar (`itrader/execution_handler/exchanges/simulated.py`)
9. FILL route (in order): `portfolio_handler.on_fill(fill_event)` (update positions/cash) → `order_handler.on_fill(fill_event)` (reconcile order mirror; if bracket parent filled, `BracketManager` assembles children and emits child `OrderEvent`s) (`itrader/events_handler/full_event_handler.py:81`)
10. Run-end sweep: `order_handler.expire_all_resting()` → final `event_handler.process_events()` drain (`itrader/trading_system/backtest_runner.py:165`)

### Margin / Leverage Path (v1.4)

1. `PortfolioConfig.TradingRules.enable_margin = True` and `allow_short_selling = True` required.
2. `compose_engine` reads `trading_rules` and threads `enable_margin` + `max_leverage` into `OrderHandler` and `StrategiesHandler` (`itrader/trading_system/compose.py:192`).
3. `SignalEvent.leverage` carries the per-signal requested leverage from the strategy.
4. `AdmissionManager.process_signal` clamps leverage to `portfolio_max_leverage`; the clamped value is carried as `OrderEvent.leverage` and `Position.leverage`.
5. `CashManager` locks isolated margin (`quantity × price / leverage`) as a separate ledger entry per position id; remaining collateral stays available.
6. `PortfolioReadModel.maintenance_margin()` computes on demand: `Σ (instrument.maintenance_margin_rate × |size| × current_price)`.

### Short / Borrow-Carry Path (v1.4)

1. Strategy emits `SignalEvent` with `Side.SELL` and direction `LONG_SHORT`.
2. `AdmissionManager` admits the short; `Position.side = PositionSide.SHORT`.
3. Per bar in `update_portfolios_market_value`: `portfolio.update_market_value_of_portfolio(prices, bar_time, universe)` → `PositionManager` accrues borrow carry via `position._last_accrual_time` and `instrument.borrow_rate` (annualized, daily-prorated).
4. Carry is debited from cash as a `CashOperation`; realized PnL is unaffected (D-08: carry never folds into realized PnL).

### Liquidation Path (v1.4)

1. After mark-to-market each bar, `_run_liquidation_pass(prices, bar_time, marked_portfolio_ids)` iterates active portfolios.
2. `_collect_breaches_over_prices`: for each open position, compute `_isolated_liq_price(position, wb, mmr)` (`itrader/portfolio_handler/portfolio_handler.py:401`) and check `_is_breached(close, liq_price, side)`.
3. `_liquidate_position`: emit a `OrderEvent(command=NEW, trigger_source=LIQUIDATION)` directly onto the queue via `_order_storage` (bypasses the normal signal→admission path); emit a `FillEvent` settled at `liq_price` (NOT the close; see WR-04/CR-01); deduct liquidation penalty `_liquidation_penalty(fee_rate, size, liq_price)` (`itrader/portfolio_handler/portfolio_handler.py:436`).

### Trailing Stop Path (v1.4)

1. Strategy emits `SignalEvent` with `order_type = TRAILING_STOP`, `trail_type` (`TrailType.PRICE` or `TrailType.PERCENT`), `trail_value`.
2. `AdmissionManager` constructs an `Order` and `OrderEvent` carrying `trail_type`/`trail_value`.
3. `MatchingEngine` rests the order and allocates a `TrailState(hwm, lwm, current_stop)` in its side-table (`itrader/execution_handler/matching_engine.py:62`).
4. Each bar: `MatchingEngine.on_bar` ratchets `hwm`/`lwm` from the bar's high/low; recalculates `current_stop`; evaluates the trigger against intrabar low (long) or high (short); on trigger emits `FillDecision` with `fill_price = current_stop` (or gap fill).

### Pair Strategy Path (v1.4)

1. `EthBtcPairStrategy` (a `PairStrategy` subclass) declares `tickers = ["ETHUSD", "BTCUSD"]` and `direction = LONG_SHORT`.
2. `StrategiesHandler.calculate_signals` detects `isinstance(strategy, PairStrategy)` and routes to `_dispatch_pair(strategy, event)`.
3. `_dispatch_pair` fetches BOTH ticker windows from `feed`, calls `strategy.evaluate_pair(win_A, win_B)` which returns two `SignalIntent`s (one per leg).
4. Each leg intent is fanned out per subscribed portfolio and enqueued as a separate `SignalEvent`.
5. Both signals flow through the normal `SIGNAL` route independently.

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers read/write through a shared `PortfolioStateStorage` (`itrader/portfolio_handler/storage/`).
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` for backtest, `postgresql` placeholder for live).
- Resting-order book + trail states: `MatchingEngine._resting` + `MatchingEngine._trail_states`, one per `SimulatedExchange`.
- Signal records: `SignalStore` (in-memory for backtest), read post-run via `BacktestTradingSystem.get_signal_records()`.
- `Universe`: constructed once at session init; held by `Engine.universe`; injected into exchange, order handler, portfolio handler.

## Key Abstractions

**Events:**
- Purpose: All inter-component messages; immutable.
- Examples: `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent` (`itrader/events_handler/events/`).
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.

**Strategy / PairStrategy:**
- Purpose: Pure-alpha base for all strategies; zero queue/portfolio access.
- Examples: `itrader/strategy_handler/base.py` (single-ticker); `itrader/strategy_handler/pair_base.py` (two-leg).
- Concretes: `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, `eth_btc_pair_strategy.py`, `my_strategies/` (user-supplied).
- Pattern: Subclass declares class-attr knobs; base introspects annotations and applies `**kwargs`; implements `generate_signal` (single) or `evaluate_pair` (pair) returning `SignalIntent | None` (or pair of intents).

**AbstractExchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange`.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`.

**PortfolioReadModel Protocol:**
- Purpose: Narrow read boundary so the order domain reads portfolios without importing the handler.
- File: `itrader/core/portfolio_read_model.py`
- Surface: `available_cash`, `get_position` (returns frozen `PositionView`), `reserve`, `release`, `exchange_for`, `open_position_count`, `active_portfolio_ids`, `total_equity`, `maintenance_margin`, `margin_ratio`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally (no adapter, no inheritance); `mypy --strict` enforces the narrow boundary.

**Instrument:**
- Purpose: Frozen per-symbol trading metadata; replaces hard-coded scale table.
- File: `itrader/core/instrument.py`
- Fields: `symbol`, `price_precision`, `quantity_precision`, `min_order_size`, `maintenance_margin_rate`, `max_leverage`, `borrow_rate`, `liquidation_fee_rate`, `settles_funding`.
- Pattern: Constructed by `derive_instruments` at session init; `Universe.instrument(symbol)` is the lookup path.

**Universe:**
- Purpose: Composed read-model over membership list + `Instrument` map; injectable seam.
- File: `itrader/universe/universe.py`
- Pattern: Constructed once in `BacktestRunner._initialise_backtest_session`; injected via `set_universe` into exchange, order handler, portfolio handler.

**OrderStorage / PortfolioStateStorage:**
- Purpose: Pluggable order-mirror / portfolio-state persistence.
- Files: `itrader/order_handler/storage/`, `itrader/portfolio_handler/storage/`; built via respective `StorageFactory`.
- Pattern: In-memory for backtest; PostgreSQL placeholder for live.

**FeeModel / SlippageModel:**
- Purpose: Pluggable execution cost.
- Files: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`); `slippage_model/` (`zero`, `fixed`, `linear`).
- Pattern: Constructed from `ExchangeConfig` by `SimulatedExchange`; fee model is late-bound (read at call time via `FeeModelCommissionEstimator`).

**SystemSpec / PortfolioSpec / Action:**
- Purpose: Declarative, frozen run description consumed by `build_backtest_system`.
- File: `itrader/trading_system/system_spec.py`
- Pattern: `dataclass(frozen=True)`; `Action` carries scheduled MODIFY/CANCEL for the per-bar `on_tick` operator hook.

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `BacktestTradingSystem.run()` or `build_backtest_system(spec).run()`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks, e2e tests.
- Responsibilities: Wire components, initialise session (membership → Universe → feed.bind → ping-grid → precompute), drive for-loop, run-end TIF sweep, print metrics summary.

**Live trading start:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Wire components, launch background daemon thread, manage lifecycle (start/stop/status).

**Live order injection:**
- Location: `itrader/trading_system/trading_interface.py`
- Triggers: Web API / external caller.
- Responsibilities: Validate running state; construct and enqueue `OrderEvent`s.

**Strategy signal generation:**
- Location: `itrader/strategy_handler/base.py` — strategy `generate_signal` / `pair_base.py` — `evaluate_pair`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. Collection lock removed from `PortfolioHandler` (D-19 single-writer contract). Individual portfolio `RLock` removed.
- **Threading (live):** Event processing runs on one daemon thread; `LiveTradingSystem._status_lock` + `threading.Event` for lifecycle.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` + `_trail_states` are instance-level. `Engine.universe` is `None` until the runner wires it at Trap-4.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. `OrderEvent` imports `TrailType` under `TYPE_CHECKING` only to keep the events package free of config import side effects.
- **Bar-timing contract:** Seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging/probability-boundary edges.
- **Determinism:** One shared seeded `random.Random` injected at wiring; injected `BacktestClock`; runs are reproducible.
- **Universe wiring (Trap-4):** `Universe` is built AFTER `compose_engine` returns (in `BacktestRunner._initialise_backtest_session`). `set_universe` / `set_order_storage` are the write seams; accessing `universe.instrument()` before wiring raises `KeyError`.
- **Indentation:** Handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** Component A holds a reference to handler B and calls `handler_b.some_method()` from inside an event callback.
**Why it's wrong:** Bypasses the queue; breaks backtest ordering guarantees; violates the D-14/D-19 single-writer contract.
**Do this instead:** Emit an event onto `global_queue`; the handler processes it in the next `process_events()` drain. Cross-domain reads go through an injected read-model Protocol (e.g. `PortfolioReadModel`).

### Adding a new event type without registering it

**What happens:** A new `EventType` member is added to `core/enums/event.py` but no entry is added to `EventHandler._routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on unrouted types (KB1 — silent drops are a tampering risk).
**Do this instead:** Add the member to `EventType`; add a branch (`EventType.NEW: [handler_fn]`) to `EventHandler._routes` in `itrader/events_handler/full_event_handler.py:68`.

### Matching orders inside OrderHandler / OrderManager

**What happens:** A new developer adds price-trigger logic (e.g. stop/limit evaluation) to `OrderManager` or `OrderHandler`.
**Why it's wrong:** Matching lives exclusively in `MatchingEngine` (`itrader/execution_handler/matching_engine.py`). Duplicating it creates two sources of truth for fills.
**Do this instead:** Add the trigger logic to `MatchingEngine.on_bar`; emit `FillDecision`; let `SimulatedExchange` apply fee/slippage and publish `FillEvent`.

### Float arithmetic on money

**What happens:** `Decimal(some_float)` or `float(price) * quantity` in a financial calculation.
**Why it's wrong:** Binary float representation artifacts corrupt monetary values (locked correctness defect).
**Do this instead:** Enter the Decimal domain via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). Carry full 28-digit precision; call `quantize(value, instrument, kind)` only at money boundaries (ledger write, reported PnL, serialization).

### Accessing Universe before Trap-4 wiring

**What happens:** Code in `compose_engine` or a handler constructor calls `engine.universe.instrument(symbol)`.
**Why it's wrong:** `Engine.universe` is `None` until `BacktestRunner._initialise_backtest_session` builds it (Trap-4 timing).
**Do this instead:** Use the `set_universe` write seam or guard with `if self._universe is None: return`.

## Error Handling

**Backtest policy (fail-fast):** `EventHandler._on_handler_error` re-raises the active exception so a handler failure aborts the run rather than silently corrupting state (D-16).
**Live policy (publish-and-continue):** `LiveTradingSystem` overrides `_on_handler_error` to emit `ErrorEvent` and keep draining.
**ERROR route:** `EventHandler._log_error_event` is the real consumer; structured log sink; severity-mapped (`WARNING`/`CRITICAL`/default `ERROR`) (`itrader/events_handler/full_event_handler.py:146`).
**Portfolio errors:** `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
**Execution rejections:** `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles without an exception propagating.
**Mark failures:** `update_portfolios_market_value` publishes `PortfolioErrorEvent` then re-raises (backtest fail-fast contract; stale equity must never silently propagate to metrics).
**Domain exceptions:** `itrader/core/exceptions/` — `base.py` (`ITraderError`, `ValidationError`, `ConfigurationError`, `StateError`), `order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `portfolio.py` (`InsufficientFundsError`, `PortfolioNotFoundError`), `data.py` (`MalformedDataError`, `MissingPriceDataError`), `strategy.py`.

## Cross-Cutting Concerns

**Logging:** Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")`. Levels: `info` for successful ops; `warning` for non-fatal issues; `error` for caught exceptions with `exc_info=True`.
**Validation:** Pydantic `BaseModel` for all config; `EnhancedOrderValidator` for order entities; typed exceptions carry structured fields.
**IDs:** Single UUIDv7 scheme via `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils` Rust extension.
**Determinism seam:** `BacktestClock` (`itrader/core/clock.py`) + one seeded `random.Random` injected at wiring. Runs are reproducible given the same seed and data.

---

*Architecture analysis: 2026-06-22*
