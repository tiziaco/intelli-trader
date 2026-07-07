<!-- refreshed: 2026-07-07 -->
# Architecture

**Analysis Date:** 2026-07-07

## System Overview

iTrader is an event-driven algorithmic trading framework. Every component
communicates through a single FIFO `global_queue` (`queue.Queue`); handlers emit
events and never call across domains directly. The same component graph is wired
for two run modes — a synchronous fail-fast backtest loop and a threaded
publish-and-continue live/paper daemon.

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  COMPOSITION ROOTS                                                         │
│  build_backtest_system → compose_engine (shared graph)                     │
│  `trading_system/backtest_trading_system.py` · `trading_system/compose.py` │
│  LiveTradingSystem.__init__ (live/paper/okx arms)                          │
│  `trading_system/live_trading_system.py`                                   │
└───────────────┬─────────────────────────────────────────┬────────────────┘
                │ drives                                    │ drives
                ▼                                           ▼
┌──────────────────────────────┐          ┌───────────────────────────────────┐
│ BacktestRunner (for-loop)    │          │ Live processing thread (daemon)   │
│ `trading_system/             │          │ + poll-timer thread + connector    │
│  backtest_runner.py`         │          │   asyncio loop thread              │
└───────────────┬──────────────┘          └───────────────┬───────────────────┘
                │ put(TimeEvent)                            │ put(BarEvent) on bar arrival
                ▼                                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  EventHandler.process_events() — drains global_queue, dispatches via       │
│  self.routes: dict[EventType, list[Callable]]  (LIST ORDER = EXEC ORDER)   │
│  `events_handler/full_event_handler.py`                                    │
└───────────────┬────────────────────────────────────────────────────────────┘
                ▼   (per-domain handlers, queue-mediated)
┌────────────┬────────────┬────────────┬────────────┬────────────┬──────────┐
│ strategies │ screeners  │ order      │ execution  │ portfolio  │ universe │
│ _handler   │ _handler   │ _handler   │ _handler   │ _handler   │ (live)   │
└─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┴─────┬──────┴────┬─────┘
      │ SIGNAL     │ SCREENER   │ ORDER      │ FILL       │ mark2mkt  │ POLL
      ▼            ▼            ▼            ▼            ▼           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  DATA ENGINE: price_handler/store (CSV/SQL) · feed (Backtest/Live bar     │
│  feed) · providers (OKX/CCXT/OANDA/Binance/Replay)                        │
│  DURABLE STORE: storage/ SqlBackend spine + Alembic · per-domain          │
│  storage/ backends (order · portfolio · signal)                           │
│  LIVE VENUE: connectors/okx (session/transport) · VenueAccount · reconcile │
└──────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (list order = exec order); handler-error policy seam | `itrader/events_handler/full_event_handler.py` |
| `compose_engine` | SHARED, mode-agnostic component-graph wiring; returns an `Engine` holder | `itrader/trading_system/compose.py` |
| `BacktestTradingSystem` | Thin backtest holder + `build_backtest_system` factory | `itrader/trading_system/backtest_trading_system.py` |
| `BacktestRunner` | Synchronous fail-fast for-loop over the `Engine`; byte-exact session setup + per-tick ordering | `itrader/trading_system/backtest_runner.py` |
| `LiveTradingSystem` | Live/paper composition root; daemon processing thread; start/stop/status + halt/pause lifecycle; venue wiring | `itrader/trading_system/live_trading_system.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid (backtest driver) | `itrader/trading_system/simulation/time_generator.py` |
| `SystemSpec` | Declarative backtest run spec (strategies, portfolios, window) | `itrader/trading_system/system_spec.py` |
| `StrategiesHandler` | Run strategies per BAR; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Thin event interface: `on_signal`/`on_fill`/`on_order_ack`; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | Coordinator over 5 collaborators: admission, brackets, lifecycle, reconcile, sizing | `itrader/order_handler/order_manager.py` |
| `AdmissionManager` | Signal→order pipeline: admission gates, sizing, reservation, bracket assembly | `itrader/order_handler/admission/admission_manager.py` |
| `BracketManager` / `BracketBook` | Bracket assembly (create-all-then-emit) + pending-bracket map | `itrader/order_handler/brackets/` |
| `LifecycleManager` | `modify_order` / `cancel_order` verbs + reservation release | `itrader/order_handler/lifecycle/lifecycle_manager.py` |
| `ReconcileManager` | `on_fill` order-mirror reconciliation (EXECUTED→FILLED, etc.) | `itrader/order_handler/reconcile/reconcile_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`/`BarEvent` to exchanges by `event.exchange` | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `OkxExchange` | Live OKX order arm (submit/cancel through connector; stream supervisor) | `itrader/execution_handler/exchanges/okx.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol; drift-halt signal | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to `Account` + cash/position/transaction/metrics managers | `itrader/portfolio_handler/portfolio.py` |
| `Account` (ABC) | Balance/margin truth contract; `Simulated*` (compute) vs `VenueAccount` (cache) leaves | `itrader/portfolio_handler/account/base.py` |
| `VenueAccount` | Venue-cached balance/position leaf (live truth cache, never recomputes) | `itrader/portfolio_handler/account/venue.py` |
| `VenueReconciler` | Two-sided restart reconcile: store-intent vs venue-truth → reconciling events / halt | `itrader/portfolio_handler/reconcile/venue_reconciler.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `LiveBarFeed` | Push-driven ring-buffer feed; monotonic guard; emits BarEvent on bar arrival | `itrader/price_handler/feed/live_bar_feed.py` |
| `OkxConnector` | Authenticated OKX session/transport: one asyncio loop, one ccxt.pro client | `itrader/connectors/okx.py` |
| `SqlBackend` | Shared SQL spine (Engine + MetaData); composed by every SQL storage concern | `itrader/storage/backend.py` |
| `UniverseHandler` | Live-only dynamic universe poll host + add/remove ticker consumer | `itrader/universe/universe_handler.py` |

## Pattern Overview

**Overall:** Event-driven pipeline with a single shared FIFO queue and data-driven dispatch.

**Key Characteristics:**
- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler.routes` is one `dict[EventType, list[Callable]]` literal — list order IS execution order. Adding/changing routing happens only there.
- **Shared graph, two run modes.** `compose_engine` builds one mode-agnostic component graph; the mode-specific factory selects concrete backends (storage/signal-store/exchange config) and injects them.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`), carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol), `BacktestBarFeed`/`LiveBarFeed`, and `CommissionEstimator` are injected read-models; the queue-only rule governs handler *writes*, not injected reads.
- **Handler/Manager split.** `<Domain>Handler` is a thin queue interface; `<Domain>Manager` (and, in the order domain, five injected collaborators) owns the business logic with no queue access.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One shared seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.
- **Backtest inertness gate.** The live stack (async/ccxt/SQL) is LAZY-imported only inside `LiveTradingSystem.__init__` arms so the backtest import path never pulls it (proven by `tests/integration/test_okx_inertness.py`).

## Layers

**Composition / run-driver layer:**
- Purpose: Wire the component graph around one `global_queue` and drive the run.
- Location: `itrader/trading_system/`
- Contains: `compose_engine`, `Engine` holder, `BacktestTradingSystem` (holder + factory), `BacktestRunner`, `LiveTradingSystem`, `TimeGenerator`, `SystemSpec`, `alert_sink.py`.
- Depends on: All handlers, `EventHandler`, feeds/stores, `reporting`, `results`, `connectors` (live arm only).
- Used by: `scripts/run_backtest.py`, `scripts/run_live_paper.py`, notebooks.

**Dispatch layer:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()` (policy seam), `_log_error_event()`.
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.

**Domain-handler layer:**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners, universe).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`, `itrader/universe/`.
- Contains: Thin handler classes + fat managers/collaborators/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.

**Data-engine layer:**
- Purpose: Look-ahead-safe price storage, per-tick/push bar windows, and BarEvent production.
- Location: `itrader/price_handler/store/`, `feed/`, `providers/`, `exchange/`, `ingestion.py`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, `LiveBarFeed`, OKX/CCXT/OANDA/Binance/Replay providers.
- Depends on: `pandas`; stores are read-only on the backtest run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, the TIME route factory, and the live feed sink.

**Durable-store layer (live/post-loop):**
- Purpose: Shared SQL spine + per-domain persistence and schema migrations.
- Location: `itrader/storage/` (`SqlBackend`, `types.py`, `halt_record_store.py`, `migrations/` Alembic), plus `<domain>/storage/` (`order_handler/storage/`, `portfolio_handler/storage/`, `strategy_handler/storage/`), `results/`.
- Contains: `SqlBackend`, `CachedSql*Storage`, `Sql*Storage`, in-memory fallbacks, storage factories, Alembic `versions/`.
- Depends on: `sqlalchemy`, `pydantic-settings` (`SqlSettings`). Structurally inert on the backtest hot loop.
- Used by: `LiveTradingSystem` (durable arm), `SqlResultsStore`.

**Live venue / connector layer:**
- Purpose: Authenticated venue session/transport and venue-truth caching + reconciliation.
- Location: `itrader/connectors/` (`base.py` `LiveConnector` Protocol, `okx.py`), `portfolio_handler/account/` (`VenueAccount`), `portfolio_handler/reconcile/` (`VenueReconciler`, `drift.py`).
- Contains: `OkxConnector`, `LiveConnector` Protocol, `VenueAccount`, `VenueReconciler`.
- Depends on: `ccxt.pro`, asyncio; all lazy-imported at the live composition root only.
- Used by: `LiveTradingSystem` OKX arm, `OkxExchange`, `OkxDataProvider`.

**Shared core layer:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `instrument.py`, `commission_estimator.py`, `portfolio_read_model.py`, `constants.py`), `itrader/outils/`.
- Depends on: Nothing inside `itrader`.
- Used by: All layers.

**Config layer:**
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig` (+ `PerformanceSettings`, `MonitoringSettings`), `PortfolioConfig`, `ExchangeConfig`, `OrderConfig`, `SqlSettings`, `OkxSettings`.
- Used by: `itrader/__init__.py`, both composition roots.

**Singleton bootstrap:**
- Location: `itrader/__init__.py`
- Initialised on import: `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

1. `BacktestRunner.run()` per-tick: `clock.set_time` → `global_queue.put(TimeEvent)` (`trading_system/backtest_runner.py`).
2. `EventHandler.process_events()` drains and dispatches (`events_handler/full_event_handler.py:117`).
3. **TIME** route → `screeners_handler.screen_markets` then `feed.generate_bar_event` (emits `BarEvent`s).
4. **BAR** route → `portfolio_handler.update_portfolios_market_value` (mark-to-market) → `execution_handler.on_market_data` (resting-order match → `FillEvent`) → `strategies_handler.calculate_signals` (→ `SignalEvent`).
5. **SIGNAL** route → `order_handler.on_signal` → `OrderManager`/`AdmissionManager` (validate + size + reserve → `OrderEvent`).
6. **ORDER** route → `execution_handler.on_order` → `SimulatedExchange` (fills/rests → `FillEvent`).
7. **FILL** route → `portfolio_handler.on_fill` (positions/cash) then `order_handler.on_fill` (mirror reconcile).
8. `BacktestRunner` calls `record_metrics` DIRECTLY (not an event) after each drain (Trap 4).

### Live Trading Path

1. `LiveTradingSystem.start()` connects the OKX connector, warms the feed, runs `VenueReconciler` + session-start baseline guard, then spawns the daemon processing thread (`trading_system/live_trading_system.py`).
2. `OkxDataProvider` streams confirm-gated `ClosedBar`s → `LiveBarFeed.update()` (monotonic guard) → `global_queue.put(BarEvent)` — the bar's arrival IS the event (replaces `TimeGenerator`).
3. The engine-thread drain follows the SAME BAR/SIGNAL/ORDER/FILL routes; `on_order` routes by `event.exchange` to `OkxExchange`; venue fills return as `FillEvent`s.
4. Handler failures use the live `_publish_and_continue` policy (emit `ErrorEvent`, keep draining) instead of fail-fast re-raise.
5. Disconnect/halt seams: connector-loop callbacks flip thread-safe flags (`pause_submission` / `_pending_stream_resume` / `_pending_connector_halt`); the engine thread drains them — no blocking venue I/O on the loop thread.

### Paper Replay Path

1. `scripts/run_live_paper.py --mode replay` constructs `LiveTradingSystem(exchange='paper')`.
2. `ReplayDataProvider` replays the golden `CsvPriceStore` as Decimal-edge `ClosedBar`s through `LiveBarFeed.update` — SYNCHRONOUS, single-thread, CI-safe; reuses the `simulated` exchange as-is.
3. `run_paper_replay()` keeps the base fail-fast re-raise (never calls `start()`), so a parity gate can never false-green on a swallowed error. Paper/backtest parity anchors on shared `PAPER_PARITY_*` window constants.

**State Management:**
- Portfolio positions/cash: each `Portfolio`'s injected `Account` leaf (`SimulatedCashAccount`/`SimulatedMarginAccount`/`VenueAccount`); sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over pluggable `OrderStorage` (`in_memory` / `cached_sql`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live lifecycle: `LiveTradingSystem._status` + `_status_lock` (single `_update_status` writer), `VALID_STATUS_TRANSITIONS`, durable `HaltRecordStore` latch.

## Key Abstractions

**Event:**
- Purpose: All inter-component messages; immutable frozen facts.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent` (`market.py`), `SignalEvent` (`signal.py`), `OrderEvent` (`order.py`), `OrderAckEvent` (`ack.py`), `FillEvent` (`fill.py`), `ErrorEvent` (`error.py`), universe/command events (`universe.py`).
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.

**LiveConnector (Protocol):**
- Purpose: Session/transport seam for a live venue — `call`/`spawn`/`client`/`sandbox`/`connect`/`disconnect`, no domain ops.
- Examples: `itrader/connectors/base.py`; concrete `OkxConnector` (`connectors/okx.py`).
- Pattern: `runtime_checkable` Protocol; the three OKX arms type against it and receive the session injected.

**Account (ABC):**
- Purpose: Balance/margin truth contract for one portfolio's account.
- Examples: `itrader/portfolio_handler/account/base.py`; leaves `SimulatedCashAccount`, `SimulatedMarginAccount` (`simulated.py`), `VenueAccount` (`venue.py`).
- Pattern: cash-vs-margin axis by inheritance; simulated-vs-venue axis by sibling leaves (compute vs cache).

**PortfolioReadModel (Protocol):**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py`; `PortfolioHandler` satisfies it structurally.

**Strategy base:**
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; reference `strategies/SMA_MACD_strategy.py`; user strategies in `my_strategies/`.
- Pattern: subclass implements `calculate_signal(...)`; emits a `SignalEvent`.

**AbstractExchange:**
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange`, `OkxExchange`.

**BarFeed / PriceStore:**
- Purpose: Look-ahead-safe data access.
- Examples: `price_handler/feed/base.py`, `store/base.py`; concrete `BacktestBarFeed`, `LiveBarFeed`, `CsvPriceStore`, `SqlHandler`.

**SqlBackend:**
- Purpose: Shared SQL spine (Engine + MetaData) composed by every SQL storage concern.
- Examples: `itrader/storage/backend.py`; composed by `CachedSql*Storage`, `SqlResultsStore`, price/portfolio/order/signal stores.

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `build_backtest_system(spec)` / `TradingSystem.run()`.
- Triggers: `scripts/run_backtest.py` (`make backtest`), oracle test `tests/integration/test_backtest_oracle.py`, notebooks.
- Responsibilities: Select backends, seed the complete symbol set, `compose_engine`, add strategies/portfolios in spec order, drive the fail-fast for-loop.

**Live run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`.
- Triggers: `scripts/run_live_paper.py --mode okx`, external caller.
- Responsibilities: Connect venue, warm feed, reconcile + baseline-guard, launch processing thread, manage halt/pause lifecycle.

**Paper replay:**
- Location: `itrader/trading_system/live_trading_system.py` — `run_paper_replay()`.
- Triggers: `scripts/run_live_paper.py --mode replay` (default, offline, CI-safe).

**External ingress:**
- Location: `LiveTradingSystem.add_event` — FAIL-CLOSED external/web ingress (D-10). Only `SIGNAL` and `STRATEGY_COMMAND` event types are admissible; every internal-fact type is rejected by default.

**Strategy signal source:**
- Location: `itrader/strategy_handler/base.py` — `calculate_signal` → `SignalEvent`, invoked by `StrategiesHandler.calculate_signals` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness (D-19 single-writer contract; portfolio collection lock removed).
- **Threading (live):** Three thread classes — the engine processing daemon, an optional universe poll-timer daemon, and the connector asyncio loop (one per `OkxConnector`). Connector-loop callbacks ONLY flip thread-safe flags; blocking venue I/O (REST snapshot, durable SQL halt write) runs on the engine thread (Pitfall 9). Portfolios/`VenueAccount` use `threading.RLock`.
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting`, `LiveBarFeed` ring, and `VenueAccount` cache are instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init.
- **Backtest inertness gate:** the whole live stack (async/ccxt/SQL/`LiveBarFeed`) is LAZY-imported inside `LiveTradingSystem.__init__` arms and NOT re-exported from package barrels, so the backtest import path stays async/ccxt/SQL-free (`tests/integration/test_okx_inertness.py`).
- **Circular imports:** `OrderHandler` ↔ `OrderManager` and its five collaborators resolved by constructor injection, not module imports.
- **Bar-timing contract:** the look-ahead-safety rules live in `price_handler/feed/bar_feed.py`; enforced in the window slice, never in strategies.
- **HALTED latch:** `HALTED` has no legal exit in `VALID_STATUS_TRANSITIONS`; the sole sanctioned exit is operator `reset_halt()` (a forced write) which re-arms reconciliation on the next `start()` (verify-then-trust). A durable `HaltRecordStore` latch survives process restart.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges. Account math skips mid-stream `quantize` (byte-exact oracle).
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, the events package, and the `account/`/`reconcile/`/`storage/` (4-space) siblings use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports another handler and calls its method to read or mutate state.
**Why it's wrong:** Breaks the single-queue contract, creates cross-domain coupling and circular imports, and bypasses ordering/error policy.
**Do this instead:** Emit an event onto `global_queue`; for read-only cross-domain access, inject a read-model (`PortfolioReadModel` in `core/portfolio_read_model.py`, the feed, or `CommissionEstimator`).

### Adding a new event type without registering it

**What happens:** A new frozen event dataclass is emitted but no route exists in `EventHandler.routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` on an unrouted type (silent drops are a tampering risk).
**Do this instead:** Add the member to `core/enums/event.py::EventType`, define the dataclass under `events_handler/events/<domain>.py`, and add a route entry in `events_handler/full_event_handler.py` — even an explicit empty list for a deferred/live-only consumer.

### Matching orders inside OrderHandler / OrderManager

**What happens:** Order code evaluates stop/limit triggers or fills itself.
**Why it's wrong:** Matching is the exchange's job; the exchange holds the resting-order book and is the source of truth for fills.
**Do this instead:** Emit `OrderEvent`s; let `SimulatedExchange`/`MatchingEngine` (or `OkxExchange`) match and emit `FillEvent`s; the order domain only reconciles its mirror in `ReconcileManager.on_fill`.

### Float arithmetic on money

**What happens:** `Decimal(float_value)` or float math on prices/cash.
**Why it's wrong:** Binary-float repr artifacts; float-for-money is a locked correctness defect and breaks the byte-exact oracle.
**Do this instead:** Enter the Decimal domain via `to_money(x)` (`core/money.py`); carry full precision; `quantize` only at money boundaries.

### Blocking venue I/O on the connector loop thread

**What happens:** A reconnect/halt callback does a `connector.call` REST snapshot or a durable SQL halt write inline on the asyncio loop.
**Why it's wrong:** Stalls every stream sharing the loop and can deadlock (Pitfall 9).
**Do this instead:** The callback flips a thread-safe flag (`_pending_stream_resume`, `_pending_connector_halt`, `pause_submission`); the engine thread drains it and performs the blocking work.

## Error Handling

**Strategy:** Backtest is FAIL-FAST (`EventHandler._on_handler_error` re-raises → run aborts); live is PUBLISH-AND-CONTINUE (`LiveTradingSystem._publish_and_continue` overrides the seam: emit `ErrorEvent`, keep draining). Paper replay keeps fail-fast so parity gates can't false-green.

**Patterns:**
- `EventHandler._log_error_event` is the ERROR-route consumer: structured log sink, severity-mapped, CRITICAL escalated to the injected `AlertSink`. The route is TERMINAL and self-guarded against error→error recursion (WR-06).
- Domain rejections flow as events, not exceptions: `SimulatedExchange` emits `FillEvent(REFUSED)` so the mirror reconciles.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Live safety states: `halt(reason)` (freeze-in-place, latched, durable record + CRITICAL alert) and `pause_submission(reason)` (reversible quiesce with deferred protective-order replay on resume).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`, `strategy.py`, `results.py`).

## Cross-Cutting Concerns

**Logging:** structlog; bind context via `get_itrader_logger().bind(component="ClassName")`; `self.logger` convention.
**Validation:** `EnhancedOrderValidator` (order domain, run in `AdmissionManager` on every signal→order path) + defense-in-depth exchange-level `validate_order` re-checking structural preconditions at the fill boundary (D-03a; not a bypass — the live `add_event` ingress is fail-closed/SIGNAL-form, so orders are domain-validated upstream); Pydantic config models.
**Authentication:** venue credentials owned solely by `OkxConnector` from `OkxSettings`; SQL credentials from unified `ITRADER_DATABASE_*` / `SqlSettings`; no secret ever bound onto an `ErrorEvent`/alert (field-bind discipline).
**Determinism/money:** injected seeded RNG + `BacktestClock`; Decimal end-to-end.

---

*Architecture analysis: 2026-07-07*
