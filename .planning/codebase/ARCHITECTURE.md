---
last_mapped_commit: 6b15b25
---
<!-- refreshed: 2026-06-30 -->
# Architecture

**Analysis Date:** 2026-06-30

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          COMPOSITION ROOTS                                    │
├──────────────────────────────┬────────────────────────────────────────────────┤
│   BacktestTradingSystem      │           LiveTradingSystem                    │
│  `backtest_trading_system.py`│        `live_trading_system.py`                │
│   (façade → Engine+Runner)   │   (background daemon thread + lifecycle)       │
│   compose_engine() seam      │   compose_engine()-shape inline wiring         │
│  `compose.py` / `system_spec`│   `trading_interface.py` (web/API bridge)      │
└──────────────┬───────────────┴────────────────────┬───────────────────────────┘
               │  both wire the identical graph around ONE shared queue
               ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EventHandler  (the dispatcher)                            │
│        `events_handler/full_event_handler.py`                                 │
│   self.routes: dict[EventType, list[Callable]]  — LIST ORDER = EXEC ORDER     │
│   drains `global_queue` (queue.Queue) via get_nowait; _dispatch per event     │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │ emits/consumes frozen Event dataclasses
   ┌───────────┼───────────┬───────────────┬───────────────┬─────────────────┐
   ▼           ▼           ▼               ▼               ▼                 ▼
┌────────┐ ┌─────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐
│strategy│ │ order   │ │execution │ │ portfolio  │ │ price      │ │ screeners    │
│_handler│ │_handler │ │_handler  │ │ _handler   │ │ _handler   │ │ _handler     │
│signals │ │mirror + │ │exchange +│ │positions/  │ │store+feed+ │ │ market       │
│        │ │brackets │ │matching  │ │cash/metrics│ │providers   │ │ screening    │
└───┬────┘ └────┬────┘ └────┬─────┘ └─────┬──────┘ └─────┬──────┘ └──────────────┘
    │           │           │             │              │
    │           ▼           │             ▼              │  (read-model seam)
    │   ┌───────────────────────────────────────────┐    │
    │   │     PERSISTENCE / STORAGE LAYER (v1.6)     │    │
    │   ├───────────────────────────────────────────┤    │
    │   │ per-concern narrow ABC → one Sql<Concern>  │    │
    │   │ Storage → composes the SHARED SQL SPINE    │    │
    │   │   `itrader/storage/` SqlBackend (Engine +  │    │
    │   │    MetaData), types.py, migrations/        │    │
    │   │ Cached* wrappers (store-first write-through)│   │
    │   └───────────────────────────────────────────┘    │
    │                                                     ▼
    └────────────► reads slices from BacktestBarFeed (look-ahead-safe)
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (list order = exec order); fail-fast error seam | `itrader/events_handler/full_event_handler.py` |
| `BacktestTradingSystem` | Backtest façade holding `Engine` + `BacktestRunner`; `run(persist=...)` triggers post-loop results dump | `itrader/trading_system/backtest_trading_system.py` |
| `Engine` / `compose_engine` | Composition-root dataclass + the single mode-agnostic wiring seam (both run modes call it) | `itrader/trading_system/compose.py` |
| `BacktestRunner` | Synchronous run loop over the `TimeGenerator` ping grid | `itrader/trading_system/backtest_runner.py` |
| `ScenarioSpec` | Declarative backtest spec the e2e/factory harness duck-types into wiring | `itrader/trading_system/system_spec.py` |
| `LiveTradingSystem` | Live composition root; background processing thread + start/stop/status lifecycle | `itrader/trading_system/live_trading_system.py` |
| `TradingInterface` | Bridge between external/web API and `LiveTradingSystem` | `itrader/trading_system/trading_interface.py` |
| `StrategiesHandler` | Run strategies per BAR; emit `SignalEvent`s; capture `SignalRecord`s | `itrader/strategy_handler/strategies_handler.py` |
| `OrderHandler` / `OrderManager` | Event interface (`on_signal`→orders, `on_fill` mirror reconcile) + business logic (admission/sizing/brackets/lifecycle/reconcile) | `itrader/order_handler/order_handler.py`, `order_manager.py` |
| `ExecutionHandler` / `SimulatedExchange` / `MatchingEngine` | Route orders to exchange; rest stop/limit; intrabar trigger/OCO; emit `FillEvent` | `itrader/execution_handler/execution_handler.py`, `exchanges/simulated.py`, `matching_engine.py` |
| `PortfolioHandler` / `Portfolio` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol impl; cash/position/transaction/metrics sub-managers | `itrader/portfolio_handler/portfolio_handler.py`, `portfolio.py` |
| `BacktestBarFeed` / `CsvPriceStore` | Look-ahead-safe per-tick bar window read-model; offline golden-CSV store | `itrader/price_handler/feed/bar_feed.py`, `store/csv_store.py` |
| `SqlBackend` | **Shared SQL spine** — a configured Engine + fresh MetaData, NO business logic; composed (has-a) by every storage concern | `itrader/storage/backend.py` |
| `OrderStorage` / `SqlOrderStorage` / `CachedSqlOrderStorage` | Order-mirror persistence ABC + SQL store (system of record) + live store-first cache wrapper | `itrader/order_handler/base.py`, `storage/sql_storage.py`, `storage/cached_sql_storage.py` |
| `PortfolioStateStorage` / `SqlPortfolioStateStorage` / `CachedSqlPortfolioStateStorage` | Portfolio-state persistence ABC + SQL store + cache wrapper | `itrader/portfolio_handler/base.py`, `storage/sql_storage.py`, `storage/cached_sql_storage.py` |
| `SignalStore` / SQL + cached variants | Signal-record persistence ABC + backends | `itrader/strategy_handler/storage/base.py`, `sql_storage.py`, `cached_sql_storage.py` |
| `ResultsStore` / `SqlResultsStore` | Results-store ABC (4th spine concern) + SQL backend for post-run dump + cross-run queries | `itrader/results/base.py`, `itrader/results/sql_storage.py` |
| Alembic migration chain | Versioned schema for the durable Postgres operational store ONLY | `itrader/storage/migrations/env.py`, `versions/*.py` |

## Pattern Overview

**Overall:** Event-driven, single-queue, data-driven dispatch — with a composed-spine persistence layer (v1.6).

**Key Characteristics:**
- **Queue-only cross-domain writes.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains. Cross-domain *reads* go through injected read-models (`PortfolioReadModel` Protocol, `BacktestBarFeed`).
- **Data-driven dispatch.** `EventHandler.routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Routing changes happen only there; an unrouted type raises `NotImplementedError`.
- **Frozen event facts.** Every event subclasses `Event` (`frozen=True, slots=True, kw_only=True`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Composed SQL spine, never inherited.** Each storage concern is one narrow ABC implemented by exactly one `Sql<Concern>Storage` that holds a `SqlBackend` by reference (has-a). There is deliberately NO shared `SqlStorageBase` god class. Four concerns compose the spine: `OrderStorage`, `PortfolioStateStorage`, `SignalStore`, `ResultsStore`.
- **Store-first write-through caches.** The live arm wraps each SQL store in a `Cached*` decorator that persists store-first (persist-then-acknowledge) then mirrors into an in-memory working set, with terminal-state eviction and restart rehydration. The composed SQL store is never modified — the cache is always rebuildable from it.
- **GATE-01 import inertness.** The backtest hot path stays SQL-free: SQL imports are lazy inside each factory's `'live'` arm, and concrete `Sql*Storage` classes are NOT re-exported from package `__init__`s. Importing `itrader.storage` / `itrader.results` pulls only the ABCs + spine, never SQLAlchemy query code on the per-tick path.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge. Money columns are `sqlalchemy.Numeric` (asdecimal) — there is deliberately no money TypeDecorator on the spine (D-13).
- **Determinism.** One seeded `random.Random` injected at wiring (`performance.rng_seed`, default 42); an injected `BacktestClock` staged on the determinism seam.

## Layers

**Composition / Run-loop:**
- Purpose: Wire all components around one `global_queue`; drive the run; trigger the post-loop persistence dump.
- Location: `itrader/trading_system/`
- Contains: `Engine` + `compose_engine` (the seam), `BacktestRunner` (for-loop), `BacktestTradingSystem` (façade), `ScenarioSpec`, `LiveTradingSystem` (threaded), `TradingInterface`, `TimeGenerator`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`, the storage factories.
- Used by: `scripts/run_backtest.py` (`make backtest`), notebooks, external/web callers.

**Dispatch:**
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`, `_on_handler_error()`, `_log_error_event()`.

**Handlers (domain logic):**
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/{strategy,order,execution,portfolio,screeners}_handler/`
- Pattern: Thin `<Domain>Handler` facade + fat `<Domain>Manager`/sub-components. The order domain is now split into sub-packages: `admission/`, `brackets/`, `lifecycle/`, `reconcile/`.

**Data engine (read path):**
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `feed/`, `providers/`, `exchange/`.
- Contains: `CsvPriceStore`, `SqlHandler` (hardened read-only SQL price store on the spine), `BacktestBarFeed`, CCXT/OANDA/Binance providers.

**Persistence / storage (v1.6 foundation):**
- Purpose: Durable SQL persistence + working-set caching for the live path; post-run results dump + cross-run queries.
- Location: `itrader/storage/` (shared spine), `itrader/{order,portfolio}_handler/storage/`, `itrader/strategy_handler/storage/`, `itrader/results/`.
- Contains: `SqlBackend`, cross-dialect `types`, Alembic `migrations/`; four narrow ABCs; one `Sql<Concern>Storage` + one `CachedSql<Concern>Storage` per concern; `SqlResultsStore`.
- Depends on: `sqlalchemy`, `alembic`, `pydantic-settings` (`SqlSettings`). Inert on the backtest import path (GATE-01).
- Used by: The storage factories (`OrderStorageFactory`, `PortfolioStateStorageFactory`, `SignalStorageFactory`) on the `'live'` arm; the composition root on `run(persist=True)`.

**Config:**
- Purpose: Pydantic-modelled system + SQL configuration.
- Location: `itrader/config/`
- Contains: `SystemConfig.default()`, domain models, and `SqlSettings` (`config/sql.py`) — the driver-by-config SQL backend selector (`env_prefix="ITRADER_DATABASE_"`).

**Shared core:**
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/`, `itrader/outils/`.
- Depends on: Nothing inside `itrader`.

**Singletons:**
- Location: `itrader/__init__.py` — `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()` initialised on import.

## Data Flow

### Primary Backtest Request Path

1. `BacktestRunner` iterates the `TimeGenerator` grid, enqueuing a `TimeEvent` (`itrader/trading_system/backtest_runner.py`)
2. TIME route → `screeners_handler.screen_markets` + `bar_event_source` (`BacktestBarFeed.generate_bar_event`) → `BarEvent` (`full_event_handler.py:69`)
3. BAR route, in order: `portfolio_handler.update_portfolios_market_value` (mark-to-market) → `execution_handler.on_market_data` (resting-order matching → `FillEvent`) → `strategies_handler.calculate_signals` (`full_event_handler.py:73`)
4. SIGNAL route → `order_handler.on_signal` (admission + sizing → `OrderEvent`) (`full_event_handler.py:78`)
5. ORDER route → `execution_handler.on_order` (`SimulatedExchange` fills/rests → `FillEvent`) (`full_event_handler.py:79`)
6. FILL route, in order: `portfolio_handler.on_fill` (positions/cash) → `order_handler.on_fill` (order-mirror reconcile) (`full_event_handler.py:80`)
7. After the loop, `run(persist=True)` calls `_persist_results()` → assembles a `RunRecord` + artifact frames and writes them through the injected `ResultsStore` (`backtest_trading_system.py:259`)

### Live Trading Path

1. `LiveTradingSystem.start()` launches a background daemon thread draining the queue (`live_trading_system.py`)
2. Same route table as backtest; `_on_handler_error` is overridden to publish-and-continue (emit `ErrorEvent`, keep draining) instead of fail-fast
3. Storage is the live arm: `OrderStorageFactory.create('live', backend=SqlBackend(...))` returns `CachedSqlOrderStorage(SqlOrderStorage(...))` (`live_trading_system.py:123`)
4. `TradingInterface` validates running state and enqueues externally-originated `OrderEvent`s

### Persistence Write/Read Flow (live caches)

1. **Write:** `CachedSql*Storage.add_order`/`update_order` persists store-first (`self._store.add_order` → one `engine.begin()` txn), THEN mirrors into the in-memory cache under one `threading.RLock` (`cached_sql_storage.py:114`)
2. **Evict:** a terminalized standalone order is purged from the working set on the `_can_evict` terminal-state gate (D-02); a bracket parent stays resident until ALL children terminalize (`cached_sql_storage.py:74`)
3. **Read split:** the open/active set serves from the cache (hot path); terminal/historical/time-range/audit queries read through to the SQL store (`cached_sql_storage.py:200`)
4. **Rehydrate:** on restart, `rehydrate()` loads the open set (PENDING/PARTIALLY_FILLED) plus parents of live children — never standalone terminal history (`cached_sql_storage.py:264`)

### Results Dump Flow (post-loop)

1. `_persist_results` short-circuits if no active portfolios; else builds per-portfolio + aggregate `RunMetrics` from the same pure `reporting.frames` builders (`backtest_trading_system.py:259`)
2. Writes `runs` + `run_portfolios` atomically via `store.save_run(record)`, then equity_curve/trade_log artifacts via `store.save_artifact(...)` (`backtest_trading_system.py:376`)
3. Dump-failure policy (D-17): re-raise when `SqlSettings.strict_persist` is True; otherwise log-and-swallow so a sweep never loses good in-memory runs

**State Management:**
- Portfolio positions/cash: owned by each `Portfolio`; sub-managers in `cash/`, `position/`, `transaction/`, `metrics/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (in-memory for backtest, `CachedSqlOrderStorage` for live).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live working-set caches: in-memory store inside each `Cached*Storage`, guarded by one `threading.RLock`.
- Durable state: the SQL spine engine (`SqlBackend.engine`), one operational Postgres DB + one on-disk SQLite results DB (`output/results.db`).

## Key Abstractions

**Event:**
- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent`.
- Pattern: `@dataclass(frozen=True, slots=True, kw_only=True)` subclass of `Event`; `type` pinned via `field(default=EventType.X, init=False)`; factory class methods for safe construction.

**SqlBackend (the shared SQL spine):**
- Purpose: A configured SQLAlchemy Engine + a fresh `MetaData` carrying a stable `NAMING_CONVENTION` — and NOTHING else.
- Examples: `itrader/storage/backend.py`; cross-dialect column types in `itrader/storage/types.py` (`Uuid`, `UtcIsoText`, `json_variant`).
- Pattern: Composed by reference (has-a). Driver selected at wiring from `SqlSettings` (`config/sql.py`). `dispose()` lives on the owning layer.

**Narrow storage ABC + composed concrete:**
- Purpose: One queryable persistence surface per domain, with no cross-concern god base.
- Examples: `OrderStorage` (`order_handler/base.py`), `PortfolioStateStorage` (`portfolio_handler/base.py`), `SignalStore` (`strategy_handler/storage/base.py`), `ResultsStore` (`results/base.py`).
- Pattern: ABC → one `Sql<Concern>Storage` (holds a `SqlBackend`) → optional `CachedSql<Concern>Storage` decorator. Tables registered by idempotent `build_*_tables(metadata)` registrars in each `storage/models.py` — the SINGLE SOURCE OF TRUTH for both test-path `create_all` and deploy-path Alembic `--autogenerate`.

**Cache wrapper (store-first decorator):**
- Purpose: Live working-set cache over the proven SQL store.
- Examples: `CachedSqlOrderStorage` (`order_handler/storage/cached_sql_storage.py`), plus portfolio/signal analogs.
- Pattern: Implements the same ABC, forwards store-first, mirrors into an in-memory store, evicts on terminal-state gate, rehydrates open-only on restart. Classified in `docs/CACHE-CLASSIFICATION.md` (class (d), live-retention cache).

**PortfolioReadModel (read-model seam):**
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py`. `PortfolioHandler` satisfies the Protocol structurally.

**Price store/feed contract:**
- Purpose: Look-ahead-safe data access (the bar-timing contract).
- Examples: `itrader/price_handler/store/base.py`, `feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`, hardened `SqlHandler` (`store/sql_store.py`).

## Entry Points

**Backtest run:**
- Location: `itrader/trading_system/backtest_trading_system.py` — `BacktestTradingSystem.run(persist=...)`
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks, `tests/integration/test_backtest_oracle.py`.
- Responsibilities: Wire via `compose_engine`, drive `BacktestRunner`, print/record metrics, optionally dump results post-loop.

**Live run:**
- Location: `itrader/trading_system/live_trading_system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API (via `TradingInterface`).
- Responsibilities: Wire components (live SQL-backed storage), launch processing thread, manage lifecycle.

**Strategy signal:**
- Location: `itrader/strategy_handler/base.py` — strategy `calculate_signal` → `SignalEvent`.
- Triggers: `StrategiesHandler.calculate_signals` per BAR.

**Alembic migrations:**
- Location: `itrader/storage/migrations/env.py` (config in `alembic.ini`).
- Triggers: `alembic upgrade head` against the durable Postgres operational store. Lazily resolves the URL from `SqlSettings`; never imported on the runtime hot path.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed. `PortfolioHandler` removed its collection lock (D-19 single-writer contract).
- **Threading (live):** Event processing runs on one daemon thread; individual portfolios use `threading.RLock`; `SimulatedExchange` uses `threading.RLock` for config updates; each `Cached*Storage` guards cache mutation + read-through with one `threading.RLock` (API-thread-safe for the imminent FastAPI layer).
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` and each cache's in-memory store are instance-level.
- **Import side effects (GATE-01):** importing `itrader` triggers singleton init; importing `itrader.storage` / `itrader.results` pulls only ABCs + spine, NOT concrete `Sql*Storage` (kept off the backtest import graph). `SqlSettings` is never constructed at import time (`config/sql.py` is import-inert). `migrations/env.py` resolves the DB URL lazily, never at import.
- **Two-store split (MIG-01/D-14):** the durable Postgres operational store runs the Alembic chain (has an `alembic_version` table); the ephemeral SQLite results/research store is built by `MetaData.create_all()` and never runs Alembic. `NAMING_CONVENTION` (in `storage/backend.py`) is the single source of constraint/index names so `create_all` and `--autogenerate` emit byte-identical names.
- **No money TypeDecorator on the spine (D-13):** money columns are `sqlalchemy.Numeric` (asdecimal, unbounded); money never lands on a SQLite-family backend this milestone.
- **No `'postgresql'` factory arm (D-06):** the `'live'` arm IS the Postgres path. Factories route `backtest`/`test` → in-memory; `live` → cached SQL wrapper; unknown → `ConfigurationError`.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection. `Cached*Storage` imports `Sql*Storage`/domain types under `TYPE_CHECKING` only.
- **Bar-timing contract:** the rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, `events_handler/events/`, `itrader/storage/`, and the `*/storage/` SQL/cache/model files use 4 spaces — match the file (a mixed-indent diff raises `TabError`).

## Anti-Patterns

### Calling handlers directly across domains

**What happens:** A handler imports and calls another handler's method instead of emitting an event.
**Why it's wrong:** Breaks the queue-only contract and the deterministic single-dispatch ordering; bypasses the route table that is the one reviewable record of execution order.
**Do this instead:** Emit an event onto `global_queue`; for reads, inject a read-model (`PortfolioReadModel`, `BacktestBarFeed`). See `full_event_handler.py:68`.

### Adding a new event type without registering it

**What happens:** A new `EventType` is enqueued but absent from `EventHandler.routes`.
**Why it's wrong:** `_dispatch` raises `NotImplementedError` (silent drops are a tampering risk).
**Do this instead:** Define the frozen dataclass under `events_handler/events/<domain>.py`, add the member to `core/enums/event.py::EventType`, and add a route in `full_event_handler.py`.

### Importing a concrete `Sql*Storage` from a package `__init__`

**What happens:** Re-exporting `SqlOrderStorage`/`SqlResultsStore` at package level pulls SQLAlchemy onto the backtest import path.
**Why it's wrong:** Breaks GATE-01 inertness — a store-free backtest run should never import SQL query code.
**Do this instead:** Keep concrete stores out of `__init__.py` (`itrader/storage/__init__.py`, `itrader/results/__init__.py` only export the spine + ABCs). Import them lazily inside the factory `'live'` arm or explicitly on the persistence path.

### Inheriting a shared SQL base class

**What happens:** A storage concern subclasses a common `SqlStorageBase` to share query helpers.
**Why it's wrong:** Collapses the per-concern ABC boundary the architecture rejects and creates a cross-concern god base.
**Do this instead:** *Compose* a `SqlBackend` by reference (has-a). Each concern is one narrow ABC + one `Sql<Concern>Storage`. See `itrader/storage/backend.py` docstring.

### Mutating the cache before the store commit

**What happens:** A `Cached*Storage` updates its in-memory working set before the SQL write returns.
**Why it's wrong:** A cache that leads the store can mask an unpersisted write (a cache bug could compromise the store's proven correctness); the cache must stay rebuildable from the store.
**Do this instead:** Persist store-first (persist-then-acknowledge), then mirror into the cache under the lock. See `cached_sql_storage.py:114`.

### Float arithmetic on money

**What happens:** Money math touches `float`, or `Decimal(float)` is called directly.
**Why it's wrong:** Float-for-money is a locked correctness defect; `Decimal(float)` carries binary-repr artifacts.
**Do this instead:** Enter the Decimal domain via `to_money(x)`; `quantize` only at money boundaries; money columns are `Numeric` (D-13).

## Error Handling

**Strategy:** Backtest fail-fast (`_on_handler_error` re-raises → run aborts rather than corrupting state); live publish-and-continue (override emits `ErrorEvent` and keeps draining).

**Patterns:**
- `EventHandler._log_error_event` is the real ERROR-route consumer (structured log sink, severity-mapped).
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles (rejections flow as events, not exceptions).
- `ExecutionHandler.on_order`/`on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- Results dump: `strict_persist` gates re-raise vs log-and-swallow (`backtest_trading_system.py:382`).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`); config/factory failures raise `ConfigurationError`.

## Cross-Cutting Concerns

**Logging:** `get_itrader_logger().bind(component="ClassName")` (structlog); console or JSON renderer; `error(..., exc_info=True)` on caught exceptions.
**Validation:** `EnhancedOrderValidator` in the order domain; `SqlSettings` Pydantic validators fail loud on missing Postgres credentials (`_require_pg_credentials`); SQL allow-list (`MetricName`) prevents `ORDER BY` injection in the results store.
**Authentication / secrets:** DB credentials are `SecretStr` sourced only from `ITRADER_DATABASE_*` env; no credential-bearing URL is ever written to `alembic.ini` or VCS.
**Persistence inertness:** GATE-01 keeps SQL off the backtest hot loop and import graph.

---

*Architecture analysis: 2026-06-30*
