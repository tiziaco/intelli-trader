# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

iTrader is an event-driven algorithmic trading framework for backtesting and live execution. All components communicate through a shared FIFO event queue rather than direct calls. Python 3.13, managed with Poetry.

## Commands

Environment setup (uses pyenv + Poetry, installs `.venv` in-project):

```bash
make init-env
```

Tests (all run through Poetry):

```bash
make test              # full suite
make test-unit         # only -m "unit"
make test-integration  # only -m "integration"
make test-e2e          # only -m "e2e"
make test-portfolio    # tests/unit/portfolio/
make test-orders       # tests/unit/order/
make test-execution    # tests/unit/execution/
make test-events       # tests/unit/events/
make test-strategy     # tests/unit/strategy/
make test-cov          # coverage -> opens htmlcov/index.html
```

Run a single test file / case:

```bash
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

The test root is `tests/` (NOT `test/`), with type-grouped subtrees — `tests/unit/<domain>/`, `tests/integration/`, `tests/e2e/`, `tests/golden/`. `conftest.py` auto-applies the type marker (`unit`/`integration`/`e2e`) from the folder location; the domain-specific `make` targets are just path shortcuts, not marker selectors.

**Test gotcha:** `pyproject.toml` sets `filterwarnings = ["error", ...]` and `--strict-markers`/`--strict-config`. Any unexpected warning fails the test, and every marker used must be declared in the `markers` list — **`unit`, `integration`, `slow`, `e2e`** (TYPE axis) plus **`smoke`, `live`** (PURPOSE axis, applied by hand) are registered.

## Architecture

### Event-driven core

Everything flows through a single `global_queue` — an `EventBus` (`events_handler/bus.py`, a `runtime_checkable` Protocol; the backtest wires `FifoEventBus`, a thin `queue.Queue` wrapper, the live path wires `PriorityEventBus`). `events_handler/full_event_handler.py::EventHandler.process_events()` drains the queue and dispatches each event through **`self.routes`** (public; `full_event_handler.py:87`, read at `:145`) — a single `dict[EventType, list[Callable]]` literal where **list order IS execution order**. Dispatch is data-driven, not a branch chain. Events are **`msgspec.Struct`s** (`class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)` — `events_handler/events/base.py:21`) defined under `events_handler/events/` (split by domain: `base.py`, `market.py`, `portfolio.py`, `screener.py`, `universe.py`, `signal.py`, `strategy.py`, `order.py`, `fill.py`, `feed.py`, `error.py`, `control.py`); each subclasses `Event`, pins its `type` via `type: ClassVar[EventType] = EventType.X`, and carries a UUIDv7 `event_id` plus a business `time` (never wall clock). The canonical flow:

```
TIME   -> screeners_handler.screen_markets + feed.generate_bar_event   (BacktestBarFeed produces BarEvents)
BAR    -> portfolio_handler.update_portfolios_market_value

        + execution_handler.on_market_data              (exchange matches resting stop/limit -> FillEvent)
        + strategies_handler.on_bar

SIGNAL -> order_handler.on_signal                       (validate + size -> OrderEvent)
ORDER  -> execution_handler.on_order                    (exchange fills/rests -> FillEvent)
FILL   -> portfolio_handler.on_fill                     (EXECUTED only: update positions/cash)

        + order_handler.on_fill                         (reconcile order mirror: FILLED/CANCELLED/REJECTED)

```

Matching lives in the **execution layer**, not the order handler: the exchange holds
the resting-order book and is the source of truth for fills. The order handler
translates signals into orders, declares brackets, and reconciles its mirror from
`FillEvent`s — it never matches orders itself.

Adding a new event type means: define the `msgspec.Struct` subclass of `Event` under `events_handler/events/<domain>.py`, add the member to `core/enums/event.py::EventType`, and add a branch to the public `EventHandler.routes`. `_dispatch` raises `NotImplementedError` on an unrouted type (silent drops are a tampering risk).

**Read-model seams** sidestep the queue-only rule for *reads*: `OrderManager`/`OrderHandler` query portfolios through the injected `PortfolioReadModel` Protocol (`core/portfolio_read_model.py`) rather than importing the handler, and bar windows come from the injected `BacktestBarFeed`. The queue-only contract governs handler-to-handler *writes*, not injected read-models.

### Two run modes, same components

Both roots wire the same mode-blind handler graph (`trading_system/graph.py::build_handler_graph`) around one shared queue, then select their own concrete backends:

- `trading_system/backtest/backtest_trading_system.py::BacktestTradingSystem` — synchronous `for` loop over a `TimeGenerator` (`trading_system/simulation/time_generator.py`, yields `TimeEvent`s across a pinned bar-date grid), uses in-memory order storage. Backtest error policy is **fail-fast**: `EventHandler` takes an injected `HandlerErrorPolicy` (`events_handler/error_policy.py`) and the backtest arm is `FailFastPolicy`, whose `on_handler_error` bare-`raise`s so a handler failure aborts the run rather than corrupting state.
- `trading_system/live/system.py::LiveTradingSystem` (built by `trading_system/live/build.py::build_live_system`) — processes the queue on a background daemon thread with start/stop/status lifecycle; the live arm injects `ErrorPolicy` for publish-and-continue (emit `ErrorEvent`, keep draining). External/web ingress into the live system is `LiveTradingSystem.add_event` (fail-closed / default-deny: `_EXTERNALLY_ADMISSIBLE` admits only `SIGNAL`, `STRATEGY_COMMAND`, and `CONFIG_UPDATE`; every other type is rejected. A `SIGNAL` routes through `OrderHandler.on_signal` → `AdmissionManager` so validation/sizing/cash-reservation engage before any `OrderEvent` is emitted; a `CONFIG_UPDATE` gets synchronous ingress validation and is refused outright when no durable config store is wired). There is no separate `TradingInterface` class.

### Handlers (each owns a domain, talks via the queue)

- **order_handler/** — `OrderHandler` is a thin interface layer; order *management* logic (signal-to-order, lifecycle, modify/cancel, bracket declaration) lives in `OrderManager`. It does **not** match orders: it declares brackets via `parent_order_id`/`child_order_ids` (the exchange enforces OCO) and reconciles the stored order mirror against exchange truth in `on_fill` (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED). Validation via `EnhancedOrderValidator`. Since v1.7 the order-handler internals are decomposed into collaborator subdirs — `admission/`, `brackets/`, `lifecycle/`, `reconcile/` — alongside `storage/`. Persistence is pluggable through the module-level function `storage/storage_factory.py::build_order_storage`, keyed on environment string: `backtest`/`test` → `InMemoryOrderStorage`; `live` → `CachedSqlOrderStorage` wrapping `SqlOrderStorage`. (The portfolio and strategy storage selectors are the same shape — `build_portfolio_state_storage`, `build_signal_store`; none of the three is a class.) The `live` arm lazy-imports the SQL backend inside the branch so the backtest import path stays SQL-free.
- **portfolio_handler/** — `PortfolioHandler` manages portfolio lifecycle and routes `on_fill`; it structurally satisfies the `PortfolioReadModel` Protocol. Each `Portfolio` delegates to three managers in their own subdirs (`position/`, `transaction/`, `metrics/`) plus an injected `Account` leaf under `account/`. The former `CashManager` was absorbed into `SimulatedCashAccount`; `cash/` survives only as an intentionally empty namespace package. Every account leaf computes its own balance — venue truth is **not** an account leaf (see Live trading below). `Portfolio` itself holds no lock; the only `threading.RLock` in the domain guards `CachedSqlPortfolioStateStorage` (`storage/cached_sql_storage.py`). There is no lock on the portfolio *collection* — the **single-writer contract** makes one unnecessary: all portfolio state mutations happen on the engine thread, and `queue.Queue` is the thread boundary (other threads only put events), so composite reads are consistent because nothing mutates concurrently.
- **execution_handler/** — `ExecutionHandler` with pluggable `fee_model/` (`zero`/`percent`/`maker_taker`), `slippage_model/` (`zero`/`fixed`/`linear`), and `exchanges/` (e.g. `simulated`). Routes `on_order` and `on_market_data` to the exchange, turning `OrderEvent`/`BarEvent` into `FillEvent`s. The `SimulatedExchange` composes a pure `MatchingEngine` (`matching_engine.py`) that holds the resting-order book and evaluates stop/limit triggers against intrabar high/low with gap-aware fills and same-bar OCO priority; the exchange then applies fee/slippage and emits the fill.
- **strategy_handler/** — `StrategiesHandler` runs strategies. Concrete strategies live under `strategy_handler/strategies/`; the reference strategy is `strategy_handler/strategies/SMA_MACD_strategy.py` (alongside `empty_strategy.py`). User-supplied strategies go in `strategy_handler/my_strategies/`. The handler also owns instance registration (`registry/` — `catalog.py`, `config_codec.py`, `rehydrate.py`), the lifecycle verbs (`lifecycle/manager.py::StrategyLifecycleManager`), signal recording (`signal_record.py`), and a `storage/` backend.
- **price_handler/** — the data engine, reorganized into `store/` (`CsvPriceStore`, `SqlHandler` in `sql_store.py` — read-only on the run path), `feed/` (`BacktestBarFeed` + the look-ahead-safety **bar-timing contract** in `feed/bar_feed.py`; `LiveBarFeed` for the push-driven live path), and `providers/` (CCXT, OANDA, Binance stream, `okx_provider.py`, `live_provider.py`).
- **screeners_handler/** & **universe/** — dynamic market screening (deferred subsystem) and membership derivation (`universe/membership.py`).
- **reporting/** — pure builders for run artifacts (`frames.py`) and derived metrics (`metrics.py`); plotting in `plots.py`.

### Configuration system

`itrader/config/` is a **Pydantic** config system rooted on `ITraderConfig` (`config/itrader_config.py`), a frozen `BaseModel` constructed directly — there is no registry, provider, or convenience-getter layer. `ITraderConfig` carries **frozen base params** — the determinism/identity guard — `rng_seed` (default 42), `environment`, `name`, `version`, `debug_mode`, and `timezone` (default `"Europe/Paris"`, oracle-critical); plus **mutable overlay sub-models** (each `validate_assignment=True`) `system` (`SystemSettings`), `universe` (`UniverseConfig`), `stream`, `feed_provider`, `safety`, `order`, and `logging` (`LogConfig` — the slim `ITRADER_*` env layer carrying `log_level`/`disable_logs`). The SQL surface stays behind a lazy `sql` `@cached_property` (`SqlSettings`) so `import itrader` pulls no sqlalchemy (GATE-01 inertness). Domain models `PortfolioConfig`/`ExchangeConfig` live in their own `config/` modules; `ExchangeConfig` presets are classmethods (`ExchangeConfig.default()` / `.high_fee()`), not a string registry. The shared config-update deep-merge helper is `itrader/outils/dict_merge.py::recursive_merge` (it lives in `outils/`, not `config/`). **Config is `ITraderConfig` model defaults plus the `ITRADER_*` env layer, and nothing else** — there is no file-based config layer and no YAML anywhere in the repo.

**Import side effects:** `itrader/__init__.py` initializes process-wide singletons on import — `config = ITraderConfig()`, `logger` (structlog, via `init_logger`), and `idgen` (`IDGenerator`). Modules import these directly (`from itrader import config, idgen`). Get a bound logger with `get_itrader_logger().bind(component="...")`.

### Determinism & money

- **Money is `Decimal` end-to-end.** Float for money is a locked correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism:** one shared seeded `random.Random` is built at wiring from `config.rng_seed` (a frozen base param on `ITraderConfig`, default 42), rides on `EngineContext.rng`, and reaches the exchange through the paper venue's build recipe (`execution_handler/exchanges/paper.py::paper_exchange_recipe`); an injected `BacktestClock` (`core/clock.py`) is staged on the determinism seam. Runs are reproducible.

### Shared core

`core/` depends on nothing inside `itrader`. It holds `enums/` (`OrderType`, `OrderStatus` + `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, portfolio/execution enums), `exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`, `strategy.py`, `results.py`, `credential.py`), and the cross-cutting primitives `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `instrument.py`, `portfolio_read_model.py`. Use the enum maps (e.g. `order_type_map`) to convert string inputs to enums.

### Live trading — inert on the backtest hot path

A paper-first live operating mode (OKX) around the same event graph, **structurally inert on the backtest path**: the entire live stack (async/`ccxt.pro`/SQL/`LiveBarFeed`) lives behind a **package import boundary** rather than behind lazy imports. `tests/integration/test_okx_inertness.py` asserts by prefix that no module under `itrader.trading_system.live` (and no `venues.accounts` / `connectors.*` concretion) reaches the backtest import graph — which is exactly why the live modules may import ccxt/SQL/asyncio at module top instead of hiding them in function bodies. The backtest run stays byte-exact (oracle 134 / `46189.87730727451`).

- **Two roots, one graph** — `trading_system/graph.py::build_handler_graph` is the pure, mode-blind wiring seam: it takes an `EngineContext` plus a root-built exchange registry and portfolio factory, selects nothing, and returns an `Engine` holder. The two composition roots are packages that share only that seam and never import each other: `trading_system/backtest/` (`build_backtest_system` + `BacktestRunner`, the synchronous fail-fast for-loop) and `trading_system/live/` (`build.py::build_live_system` → `system.py::LiveTradingSystem`, plus `bootstrap.py`). `LiveTradingSystem` holds no composition knowledge — every collaborator is a **required** constructor parameter.
- **Venue catalogue & accounts** — `venues/catalog.py` answers every pre-build question about a venue as *data* (capabilities, credential model, default data provider): selecting a venue is a dict lookup, not a plugin hierarchy. `venues/accounts.py` owns the venue-account domain — `AccountSpec` (one durable `venue_accounts` row, typed) and `VenueAccountManager`, reached as `system.venue_accounts.provision(...)`. `bring_online` is **registration-last**: the `(venue, account_id)` routing entry the order path reads is the final statement, so any earlier failure leaves the pair unroutable rather than routable against a session that never opened. Each venue's build recipe is a function living next to its adapter (`execution_handler/exchanges/paper.py`, `okx.py`).
- **Connectors** — `connectors/` holds the `LiveConnector` Protocol (`base.py`), `OkxConnector` (`okx.py`: one authenticated asyncio loop + one `ccxt.pro` client, region+sandbox host routing, credentials owned solely by the connector from `OkxSettings`/`SecretStr`), the `ConnectorPool` (`pool.py`, memoizing one session per `(venue, account_id)` plus one public session per venue, with a session-identity guard that refuses a same-pair credential/host disagreement) and `stream_supervisor.py`. `execution_handler/exchanges/okx.py::OkxExchange` is the live order arm.
- **Restart bootstrap** — `trading_system/live/bootstrap.py::bootstrap_session` is the boot contract, and its order is load-bearing: probe for the `portfolios` table (absent = first start, not a fault) → assert distinct accounts → bring every enabled account online (quarantining a failing row with a CRITICAL alert) → rehydrate portfolios with their persisted ids. Assembly **must** precede rehydrate, or a portfolio naming a not-online account silently lands on a compute leaf instead of raising.
- **Live feed** — `price_handler/feed/live_bar_feed.py::LiveBarFeed` is a push-driven ring-buffer feed (monotonic guard); a confirm-gated `ClosedBar` arrival IS the event (replaces `TimeGenerator`). The replay harness (`tests/support/replay_harness.py` — `TestLiveDataProvider`/`TestDataPlugin`/`TestRunner`, each `__test__ = False`) replays the golden CSV through the same feed for the offline, CI-safe **paper-replay parity gate** (`build_paper_replay_system()`, driven by `tests/integration/test_paper_parity.py` and `scripts/run_live_paper.py`, kept fail-fast so a parity gate can't false-green).
- **Venue truth & reconciliation** — `Portfolio` delegates to an injected `Account` leaf (`portfolio_handler/account/base.py` ABC), and **every leaf computes its own balance** (`SimulatedCashAccount`/`SimulatedMarginAccount`). Venue truth is deliberately *not* an account leaf: it is read from the venue by the execution adapter that owns the authenticated session, as an `AccountSnapshot` (`execution_handler/exchanges/base.py::AbstractExchange.snapshot()`; an exchange with no venue behind it returns `AccountSnapshot.empty()`). An account whose balance needs a network round trip cannot be the leaf a portfolio is *constructed* with, since construction reads the balance. On restart, `portfolio_handler/reconcile/reconciliation_coordinator.py` owns the rehydrate → venue-reconcile → baseline-guard sequence, driving `venue_reconciler.py::VenueReconciler` off the account manager's **online records** (not an account-kind predicate) for a two-sided store-intent-vs-venue-truth reconcile (`drift.py`) → reconciling events or `halt`.
- **Live lifecycle** — `LiveTradingSystem` runs the queue on a daemon thread and delegates every safety verb (`halt`/`reset_halt`/`is_halted`/`pause_submission`/`resume_submission`) to an injected `SafetyController` (`trading_system/safety/safety_controller.py`), which owns the `_status`/`_status_lock`/`VALID_STATUS_TRANSITIONS` latch and the public `update_status()` mutation seam; `HALTED` has no legal exit except operator `reset_halt()`. A durable `HaltRecordStore` (`storage/halt_record_store.py`) survives process restart. Safety states: `halt(reason)` (latched freeze + CRITICAL alert) and `pause_submission(reason)` (reversible quiesce with deferred protective-order replay). Connector-loop callbacks only flip thread-safe flags; blocking venue I/O runs on the engine thread (never the asyncio loop).
- **Durable store** — `storage/` is the shared SQL spine: `SqlEngine` (`engine.py`, Engine + MetaData composed by every SQL storage concern), `types.py`, and the durable stores `halt_record_store.py`, `portfolio_definition_store.py`, `strategy_registry_store.py`, `system_stats_store.py`, `system_store.py`, `venue_account_store.py`, `venue_store.py`. The Alembic migration chain lives at the **repo root** in `migrations/` (`alembic.ini::script_location = migrations`) — it is no longer under `storage/`. `SqlSettings` unifies Postgres + a SQLite results store.
- **Universe (live-only)** — `universe/universe_handler.py::UniverseHandler` hosts the dynamic universe poll timer and consumes add/remove-ticker commands.

## Conventions

- **Indentation:** indentation is **per file, not per package** — every handler package is now mixed, so never generalize from a sibling. Older handler modules use **tabs** (`order_handler/order_handler.py`, `order_manager.py`, `execution_handler/execution_handler.py`, `strategy_handler/strategies_handler.py`, `portfolio_handler/portfolio.py`, `events_handler/full_event_handler.py`); `config/`, `core/`, `price_handler/feed/`, the `events_handler/events/` package, `events_handler/error_handler.py`, most of `portfolio_handler/` (incl. `portfolio_handler.py` itself), every `*/storage/` subpackage, `execution_handler/matching_engine.py` + `fee_model/` + `slippage_model/` use **4 spaces**. Measure the bytes of the file you edit, never normalize (a mixed-indentation diff breaks a tab file).
- Components are constructed with the `global_queue` as a constructor argument and never call each other directly across domains — emit an event instead (read-only cross-domain access goes through an injected read-model).
- **Barrels stay import-light on the live side.** `venues/accounts.py`, everything under `trading_system/live/` (beyond `bootstrap`), and every `connectors/` concretion (`OkxConnector`, `ConnectorPool`) are deliberately **not** re-exported from their package `__init__.py` — a barrel re-export of a ccxt/SQL-bearing module makes importing *any* sibling heavy and reddens the inertness gate. Live consumers import by path (`from itrader.trading_system.live.build import build_live_system`). Do not "helpfully" add a re-export or a lazy `__getattr__` shim; both re-create the heaviness the boundary exists to remove.
- **Documented conventions (authoritative home: `.planning/codebase/CONVENTIONS.md`).** Four established conventions are pinned there so they are not re-litigated: (1) the **config-enum exception** — the nine `str, Enum` config-domain enums (`Environment`, `LogLevel`, `TrailType`, `ExchangeVenue`, `FeeModelType`, `SlippageModelType`, `SqlDriver`, `PortfolioType`, `RiskLevel`) live in `config/` not `core/enums/` by design (relocating inverts the core→config dependency); (2) the **broad-`except` run-mode policy** — backtest fail-fast vs live publish-and-continue is intentional, not an inconsistency; (3) the **tab/space indentation hazard** above; (4) the **dual-layer order-validator overlap** (`order_validator.py` / `simulated.py`) is justified-by-decision (defense-in-depth — the exchange is the source of truth for fills, so `SimulatedExchange.validate_order` re-checks structural preconditions (symbol, exchange min/max size, price, connection) at the fill boundary regardless of upstream validation), so it is documented and the code is NOT removed (Phase 6 / W4-09). The rationale is defense-in-depth **only** — there is no bypass to justify it: `LiveTradingSystem.add_event` is fail-closed and SIGNAL-form, so every live order routes through `AdmissionManager`'s `EnhancedOrderValidator` before an `OrderEvent` is emitted. Do not re-derive a bypass argument for this overlap.

<!-- GSD:project-start source:PROJECT.md -->

## Project

**iTrader — Backtest-Correctness Refactor**

iTrader is an event-driven algorithmic trading framework (Python 3.13, Poetry) for backtesting
and live execution, where all components communicate through a shared FIFO event queue. This
project is a **brownfield structural refactor** of that framework: make it run **correctly in
backtest mode** end-to-end on one reference strategy (`SMA_MACD`) over a fixed golden dataset,
fixing every structural issue surfaced in the architecture review, and leave behind an engine
whose results are trustworthy and regression-locked.

**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

### Constraints

- **Tech stack**: Python 3.13, Poetry, event-driven single-`global_queue` architecture — components
  emit events, never call across domains directly

- **Money**: Decimal end-to-end — float for money is a correctness defect (locked decision)
- **IDs**: single UUIDv7 scheme via the Rust-backed `uuid-utils` package (locked decision)
- **Determinism**: seeded RNG + injected clock — runs must be reproducible
- **Golden-master discipline**: M2–M4 are behavior-preserving against the M1 behavioral oracle;
  the numerical oracle re-baselines at exactly two points (after M2, after M5); M5 is the only
  milestone allowed to change results, validated by external cross-validation

- **Test strictness**: `pyproject.toml` sets `filterwarnings=["error"]`, `--strict-markers`,
  `--strict-config` — any unexpected warning fails the suite; every marker must be declared

- **Indentation**: tabs in handler modules; spaces in `config/` and newer modules — match the file
- **Import side effects**: `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons
  on import

- **Definition of done** (program-level, REFACTOR-BRIEF §1): `SMA_MACD` runs end-to-end producing a
  non-trivial trade log + equity curve; `mypy --strict` clean; no float money; single UUIDv7 scheme;
  deterministic; 274 component tests green (migrated to pytest) + a run-path integration test;
  metrics cross-validated against `backtesting.py` and `backtrader`; final numerical reference frozen
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->

## Technology Stack

## Languages

- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.
- Make - Developer task runner (`Makefile`)

## Runtime

- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~503 KB)

## Frameworks

- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`
- pytest ^9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-asyncio ^1.4.0 - `asyncio_mode = "auto"` + `asyncio_default_fixture_loop_scope = "function"` (both keys REQUIRED under `--strict-config`)
- pytest-cov ^7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle
- mypy ^2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems and stubless third-party libs
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)

## Key Dependencies

- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- scipy ^1.17.1 - Declared in `pyproject.toml` but NOT imported anywhere under `itrader/` or `scripts/` (`grep -rn "scipy" itrader/ scripts/` is empty); it is present only as a transitive requirement of scikit-learn/statsmodels
- msgspec ^0.21.1 - The event substrate: `Event` and `core/bar.py::Bar` are `msgspec.Struct`s, not dataclasses
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library used in strategy filters and SLTP models
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `BaseSettings` env-var layers with `env_prefix="ITRADER_"` — `LogConfig` (`itrader/config/log.py`, `log_level`/`disable_logs`) and `SqlSettings` (`itrader/config/sql.py`, `ITRADER_DATABASE_*`)
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`) - Imported by `itrader/price_handler/providers/binance_stream.py` for Binance live kline streaming, but **NOT declared in `pyproject.toml`** and not installed in `.venv` — that module cannot be imported as-is (it is mypy-`ignore_errors`'d and off the backtest path, so nothing catches it)
- tqdm ^4.67.3 - Progress bars during data download loops
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)
- alembic ^1.18.5 - Migration chain at the repo root (`migrations/`, `alembic.ini`); dev-group dependency
- testcontainers ^4.14.2 (extras: postgresql) - Throwaway Postgres for the SQL-store tests; skips cleanly when Docker is absent
- scalene ^2.3.0 - CPU profiler behind the `make perf-profile` / `perf-view` targets
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel

## Configuration

- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). Contains DB URLs and exchange API credentials — see INTEGRATIONS.md for key names.
- `pydantic-settings` `LogConfig` (`itrader/config/log.py`, `extra="ignore"`) reads logging vars with prefix `ITRADER_`; `SqlSettings` (`itrader/config/sql.py`) reads `ITRADER_DATABASE_*`
- Config is `ITraderConfig` model defaults overlaid by the `ITRADER_*` env vars — there is no file-based config layer.
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. `unit`, `integration`, `slow`, `e2e` (folder-derived TYPE axis, in `tests/conftest.py`) plus `smoke`, `live` (hand-applied PURPOSE axis) markers are declared.

## Platform Requirements

- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- PostgreSQL on `localhost:5544` for the price database (`trading_system_prices`) when using SQL price storage — 5544 is the `SqlSettings.port` default (`config/sql.py`), chosen because 5432 is already taken on the dev box
- PostgreSQL for live order storage — `build_order_storage('live', ...)` builds `CachedSqlOrderStorage` wrapping `SqlOrderStorage` (`itrader/order_handler/storage/` holds `cached_sql_storage.py`, `in_memory_storage.py`, `models.py`, `sql_storage.py`, `storage_factory.py`)
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

## Naming Patterns

- `snake_case.py` throughout — no exceptions found.
- Handler modules: `<domain>_handler.py` — `order_handler.py`, `execution_handler.py`, `portfolio_handler.py`.
- Manager modules: `<domain>_manager.py` — `order_manager.py`, `position_manager.py`, `metrics_manager.py`.
- Abstract base modules: `base.py` inside each domain package (e.g. `execution_handler/exchanges/base.py`).
- Storage backends: `<backend>_storage.py` — `in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`.
- Tests mirror source: `test_<module>.py` (e.g. `test_order_manager.py`).
- `snake_case` always.
- Event-handler callbacks: `on_<event>()` — `on_signal()`, `on_order()`, `on_fill()`, `on_market_data()`.
- Factory class methods: `new_<object>()` — `Order.new_order()`, `Order.new_stop_order()`, `FillEvent.new_fill()`.
- Getters: `get_<thing>()` — `get_portfolio()`, `get_cash_operations()`, `get_order()`.
- Private helpers/attributes: single leading underscore — `_admit_order()`, `_emit_rejection()`, `self._resting`, `self._storage`.
- Module-private module-level constants: leading underscore — `_DEFAULT_SCALES` / `_CASH_SCALES` (`core/money.py`), `_EXTERNALLY_ADMISSIBLE` (`trading_system/live/system.py`), `_CONTROL_EVENT_TYPES` (`events_handler/bus.py`). A constant that becomes cross-module public drops the underscore (`core/money.py::ONE`).
- `snake_case` always.
- The shared event queue is always named `global_queue` (constructor parameter) or `events_queue`.
- Bound logger is always `self.logger`.
- Config is always `self.config` (or a typed config object such as `ITraderConfig`).
- Classes: `PascalCase` — `OrderHandler`, `SimulatedExchange`, `MatchingEngine`, `PositionManager`.
- Handler/Manager split: `<Domain>Handler` (thin interface) + `<Domain>Manager` (business logic).
- Abstract bases: `Abstract<Name>` — `AbstractExchange`, `AbstractExecutionHandler`.
- Config classes: `<Domain>Config` — `PortfolioConfig`, `ExchangeConfig`, `LogConfig` (frozen root: `ITraderConfig`).
- Exception classes: `<Specific><Category>Error` — `PortfolioNotFoundError`, `InsufficientFundsError`, `SizingPolicyViolation`.
- Enum names `PascalCase`, members `UPPER_CASE` — `OrderStatus.PENDING`, `FillStatus.EXECUTED`, `Side.BUY`.
- String-to-enum maps: `<domain>_<type>_map` — `order_type_map`, `order_status_map`.

## Code Style

- No autoformatter configured (no black/ruff/prettier config present). Match the surrounding file by hand.
- No standalone linter config (`.flake8`, `.pylintrc`, `ruff.toml`, `.pre-commit-config.yaml` all absent).
- The only static-analysis gate is **mypy** (`pyproject.toml [tool.mypy]`, `strict = true`, `files = ["itrader"]`).
- **Tabs:** the older handler/manager modules under `itrader/` use tab indentation — e.g. `order_handler/order_handler.py`, `order_handler/order_manager.py`, `execution_handler/execution_handler.py`, `strategy_handler/strategies_handler.py`, `portfolio_handler/portfolio.py`, `events_handler/full_event_handler.py`.
- **4 spaces:** newer refactored modules use spaces — `itrader/config/`, `itrader/core/money.py`, `itrader/core/bar.py`, `itrader/core/ids.py`, `itrader/events_handler/events/`, `itrader/events_handler/error_handler.py`, `itrader/execution_handler/matching_engine.py`, and most of `itrader/portfolio_handler/` (including `portfolio_handler.py` itself — 0 tab-indented lines).
- **Every handler package is now MIXED.** Naming a package tells you nothing; `portfolio_handler/` is 3 tab files vs 23 space files, `execution_handler/` 6 vs 12, `order_handler/` 10 vs 10, `strategy_handler/` 21 vs 19.
- **Rule:** ALWAYS match the indentation of the file being edited — measure it (`grep -c $'^\t' <file>`), never infer it from a sibling. Do not normalize. A mixed-indentation diff in a tab file will break the file.
- Required and enforced under `mypy --strict` for in-scope code.
- Modern union syntax preferred: `float | int | str | Decimal`, `"PortfolioId | int"`.
- `typing` imports used where needed: `Any`, `Optional`, `Callable`, `Dict`, `List`, `cast`, `assert_never`.
- Several subsystems are deferred from strict typing via `[[tool.mypy.overrides]]` `ignore_errors` — exactly: `price_handler.providers.{ccxt_provider,oanda_provider,exchange_base,binance_stream}`, `screeners_handler.*`, `strategy_handler.my_strategies.*`. The SQL stores are NOT exempt, and neither is the live stack any more — everything under `trading_system/live/`, `venues/` and `connectors/` is `mypy --strict` clean (the old `trading_system.live_trading_system` override is gone, so dead code and unused imports there no longer pass silently). Do not rely on the exempt modules being typed; new code should be strict-clean.

## Import Organization

- Both relative (`..core.enums`) and absolute (`itrader.core.enums`) styles appear; relative is common inside a domain package, absolute for cross-domain. Match the file.
- Singletons are imported directly from the package root: `from itrader import idgen`, `from itrader import logger, idgen`.
- None — Python package imports only. No `tsconfig`-style aliases.

## Error Handling

- Root: `ITraderError` (`base.py`).
- Base categories (`core/exceptions/base.py`): `ValidationError`, `ConfigurationError`, `StateError`, `NotFoundError`.
- Domain-specific: `itrader/core/exceptions/portfolio.py` (`PortfolioError`, `InsufficientFundsError`, `PortfolioNotFoundError`), `itrader/core/exceptions/order.py` (`OrderError`, `UnsizedSignalError`, `SizingPolicyViolation`), `itrader/core/exceptions/data.py` (`DataError`, `MalformedDataError`, `MissingPriceDataError`). Execution failures flow as `FillEvent(REFUSED)` events, not exceptions; execution error codes live in `core/enums/execution.py::ExecutionErrorCode`.
- Exceptions carry structured fields and build their message in `__init__` (e.g. `ValidationError(field, value, message)`, `StateError(entity_id, current_state, ...)`).
- Raise typed exceptions, not bare `Exception` or boolean returns. Fee/validation models raise `ValidationError` rather than returning `False` (see `fee_model`).
- Handlers catch-and-log at the event boundary and do NOT re-raise — `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions to prevent queue stalls.
- Rejections flow as events, not exceptions — **there is no synchronous result object**: `SimulatedExchange.on_order` runs `_admit_order()`, which on any refusal calls `_emit_rejection()` to enqueue a `FillEvent(REFUSED)` so the order mirror reconciles. (`validate_order()` does return a value — an `OrderPreflightResult` from `execution_handler/result_objects.py` — but it is internal to admission, never the rejection channel.)
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.

## Money Policy (correctness-critical)

- **Decimal end-to-end** — float for money is a defect (locked decision).
- Enter the Decimal domain only via `to_money(x)` → `Decimal(str(x))` (`itrader/core/money.py`). NEVER call `Decimal(float)` directly (binary-float repr artifact).
- Carry full 28-digit precision through intermediate math; `quantize(value, instrument, kind)` ONLY at money boundaries (ledger write, reported PnL, serialization). `kind` ∈ `"price" | "quantity" | "cash"`; rounding is `ROUND_HALF_UP`.
- Per-instrument scales live on the frozen `Instrument` value object (`itrader/core/instrument.py` — `price_precision` / `quantity_precision`, each a Decimal *scale*, built by `itrader/universe/instruments.py`); `money.py` is stateless and reads the scale off the handed-in `Instrument`. The old `_INSTRUMENT_SCALES` table is gone. What remains in `itrader/core/money.py` is `_DEFAULT_SCALES` (no-data fallback) and `_CASH_SCALES` (per-quote-currency cash scale).

## IDs & Determinism

- Single UUIDv7 scheme via the `idgen` singleton (`from itrader import idgen`), backed by `uuid-utils`. Do not introduce a second ID scheme.
- Determinism: a single seeded `random.Random` is constructed at engine wiring from `config.rng_seed` (frozen base param, default 42) and carried on `EngineContext.rng`, reaching `SimulatedExchange._rng` via the paper build recipe (`execution_handler/exchanges/paper.py`). `ExecutionHandler` holds NO determinism seam. Never seed per-call.

## Logging

- Bind a component context: `self.logger = get_itrader_logger().bind(component="ClassName")` (68 occurrences across `itrader/` at time of writing — treat as "everywhere", not a fixed count).
- Levels: `info` for successful ops/initialization; `warning` for non-fatal issues (unknown exchange, skipped event); `error` for caught exceptions with `exc_info=True` (32 occurrences); `debug` rarely used.

## Comments & Docstrings

- Comments state what is true **now**. The changelog belongs in the commit and in `.planning/`, not in the source. Do not write comments narrating what moved, what was deleted, or which phase did it — a comment describing code that is no longer there is a defect.
- **`D-NN` tags do NOT form a global namespace.** `D-NN` is a per-phase decision counter that restarts every phase, so a bare `D-04` has ~60 unrelated definitions across `.planning/` and resolves to none of them. Do not add bare `D-NN` citations, and do not treat an existing one as a lookup key. When a decision needs citing, either scope it to its phase (`11.2-07 (D-36)` — the form that actually resolves) or, better, just state the claim: `# money enters Decimal via Decimal(str(x)), never Decimal(float)`.
- Classes carry a summary docstring describing responsibilities (often a bulleted list).
- Functions use either a one-line docstring or NumPy-style `Parameters`/`Returns` blocks (see `ExecutionHandler.__init__`).
- Used to explain WHY — the constraint, the pitfall, the reason the obvious alternative is wrong (e.g. `# RESEARCH Pitfall 5`). Avoid restating what the code does.

## Function & Module Design

- `<Domain>Handler` is a thin interface: receives events from the queue, delegates to its `<Domain>Manager`, emits events back to the queue. It has no business logic.
- `<Domain>Manager` owns the business logic and has NO queue access and NO back-reference to its handler (layering is one-directional: facade → manager → storage; `OrderManager` has exclusive ownership of the order storage).
- Components take `global_queue` as a constructor argument and never call other handlers directly across domains — they emit an event onto the queue instead.
- Events are **`msgspec.Struct`s**, NOT dataclasses: `class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)` (`events_handler/events/base.py`), and each subclass pins `type: ClassVar[EventType] = EventType.X`. `core/bar.py::Bar` is a `msgspec.Struct` too.
- Value objects elsewhere are `@dataclass(frozen=True, slots=True)` — e.g. `_PendingBracket` (`order_handler/brackets/bracket_book.py`), `Instrument` (`core/instrument.py`), `ConnectionResult`/`HealthStatus`/`OrderPreflightResult` (`execution_handler/result_objects.py`).
- `__init__.py` files act as barrels that re-export the domain's public surface (e.g. `core/enums/__init__.py` re-exports all enums grouped by domain with comment headers).

<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

## System Overview

`EventHandler.routes` is the authoritative dispatch table (`full_event_handler.py`) — a
single `dict[EventType, list[Callable]]` literal where **list order IS execution order**.
The backtest literal below is the whole of it; live-only routes are appended by
`LiveRouteRegistrar` at live composition.

```text
TimeGenerator ──TIME──▶ screeners_handler.screen_markets
                     └▶ bar_event_source            (BacktestBarFeed.generate_bar_event)
                                │
                                ▼
                              BAR ──▶ 1. portfolio_handler.update_portfolios_market_value
                                      2. execution_handler.on_market_data   (resting stop/limit → FILL)
                                      3. strategies_handler.on_bar          (→ SIGNAL)
                                │
        SIGNAL ─────────────────┴─▶ order_handler.on_signal        (validate + size → ORDER)
        ORDER  ───────────────────▶ execution_handler.on_order     (exchange fills/rests → FILL)
        ORDER_ACK ────────────────▶ order_handler.on_order_ack     (persist venue id)
        FILL   ───────────────────▶ 1. portfolio_handler.on_fill   (EXECUTED only: positions/cash)
                                    2. order_handler.on_fill       (order-mirror reconcile)
        ERROR  ───────────────────▶ error_handler.on_error         (severity-mapped sink)

Routed but empty in backtest (live-only consumers, backtest stays inert):
  SCREENER, UPDATE, UNIVERSE_UPDATE, UNIVERSE_POLL, STRATEGY_COMMAND,
  BARS_LOADED, BARS_LOAD_FAILED, STREAM_STATE, CONNECTOR_FATAL, CONFIG_UPDATE
```

A handler that raises is routed to the injected `HandlerErrorPolicy` — `FailFastPolicy`
(backtest: bare re-raise) or `ErrorPolicy` (live: publish-and-continue). `_dispatch`
raises `NotImplementedError` on an unrouted type; silent drops are a tampering risk.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `EventHandler` | Drain queue; dispatch each event through `self.routes` (list order = execution order); route handler failures to the injected `HandlerErrorPolicy` | `itrader/events_handler/full_event_handler.py` |
| `HandlerErrorPolicy` | Injected handler-failure seam: `FailFastPolicy` (backtest re-raise) / `ErrorPolicy` (live publish-and-continue) | `itrader/events_handler/error_policy.py` |
| `ErrorHandler` | The ERROR-route consumer: severity-mapped log + CRITICAL alert escalation + `last_error` persist | `itrader/events_handler/error_handler.py` |
| `build_handler_graph` | Pure mode-blind wiring of the handler graph; returns an `Engine` holder. Selects nothing — the root supplies the exchange registry and portfolio factory | `itrader/trading_system/graph.py` |
| `BacktestTradingSystem` | Backtest composition root + synchronous run loop over `TimeGenerator` | `itrader/trading_system/backtest/backtest_trading_system.py` |
| `build_live_system` | Live composition root: eight linear build steps, then the facade | `itrader/trading_system/live/build.py` |
| `LiveTradingSystem` | Live facade (no composition knowledge; all collaborators required ctor params); background processing thread + start/stop/status lifecycle | `itrader/trading_system/live/system.py` |
| `LiveTradingSystem.add_event` | External/web ingress into the live system (fail-closed: admits only externally-originated `SIGNAL` / `STRATEGY_COMMAND` / `CONFIG_UPDATE`) | `itrader/trading_system/live/system.py` |
| `bootstrap_session` | Live restart contract: probe → assert distinct accounts → bring accounts online → rehydrate portfolios | `itrader/trading_system/live/bootstrap.py` |
| `VenueAccountManager` | Venue-account records: provision, `bring_online` (registration-last), `bring_offline`, TOFU identity guard | `itrader/venues/accounts.py` |
| `ConnectorPool` | Memoizes one authenticated session per `(venue, account_id)` + one public session per venue; session-identity guard | `itrader/connectors/pool.py` |
| `TimeGenerator` | Yield `TimeEvent`s across a pinned bar-date grid | `itrader/trading_system/simulation/time_generator.py` |
| `StrategiesHandler` | Run all strategies per bar; emit `SignalEvent`s | `itrader/strategy_handler/strategies_handler.py` |
| `ScreenersHandler` | Dynamic market screening on TIME (deferred subsystem) | `itrader/screeners_handler/screeners_handler.py` |
| `OrderHandler` | Event interface: `on_signal` → orders, `on_fill` mirror reconcile; delegates to `OrderManager` | `itrader/order_handler/order_handler.py` |
| `OrderManager` | All order business logic; admission/sizing; bracket declaration | `itrader/order_handler/order_manager.py` |
| `ExecutionHandler` | Route `OrderEvent`s to exchanges; drive resting-order matching on each BAR | `itrader/execution_handler/execution_handler.py` |
| `SimulatedExchange` | Fill market orders; rest stop/limit; apply fee/slippage; emit `FillEvent` | `itrader/execution_handler/exchanges/simulated.py` |
| `MatchingEngine` | Pure resting-order book; intrabar trigger/OCO evaluation | `itrader/execution_handler/matching_engine.py` |
| `PortfolioHandler` | Portfolio lifecycle; `on_fill` routing; `PortfolioReadModel` Protocol implementation | `itrader/portfolio_handler/portfolio_handler.py` |
| `Portfolio` | Per-portfolio state; delegates to position/transaction/metrics managers + an `Account` leaf | `itrader/portfolio_handler/portfolio.py` |
| `BacktestBarFeed` | Look-ahead-safe per-tick bar window read-model; `generate_bar_event` factory | `itrader/price_handler/feed/bar_feed.py` |
| `CsvPriceStore` | Eager-load committed golden CSV; offline read-only store | `itrader/price_handler/store/csv_store.py` |
| `BacktestClock` | Injected deterministic clock (determinism seam) | `itrader/core/clock.py` |

## Pattern Overview

- **Queue-only cross-domain communication.** Handlers receive `global_queue` in the constructor and emit events; they never call other handlers' methods directly across domains.
- **Data-driven dispatch.** `EventHandler.routes` is a single `dict[EventType, list[Callable]]` literal. List order IS execution order. Adding/changing routing happens only there.
- **Frozen event facts.** Every event subclasses `Event` (`msgspec.Struct` — `frozen=True, kw_only=True, gc=False`) carrying a UUIDv7 `event_id` and a business `time` (never wall clock).
- **Read-model seams instead of cross-domain reads.** `PortfolioReadModel` (Protocol) and `BacktestBarFeed` are injected as read-models; the queue-only rule governs handlers, not read-models.
- **Decimal end-to-end for money.** Float for money is a correctness defect; `float()` appears only at the serialization/logging edge.
- **Determinism.** One seeded `random.Random` built at wiring from `config.rng_seed` (default 42) and carried on `EngineContext.rng`; an injected `BacktestClock` staged on the determinism seam.

## Layers

- Purpose: Wire all components around one `global_queue`; drive the run.
- Location: `itrader/trading_system/`
- Contains: the shared `graph.py::build_handler_graph` seam and `EngineContext`; the two composition roots `backtest/` (`BacktestTradingSystem` for-loop, `BacktestRunner`) and `live/` (`build.py`, `system.py`, `bootstrap.py`); `TimeGenerator`; the `safety/` package (`SafetyController`, `StreamRecoveryHandler`, `PreTradeThrottle`). The venue substrate lives outside this package in `itrader/venues/` (`catalog.py`, `accounts.py`) and `itrader/connectors/`.
- Depends on: All handlers, `EventHandler`, `BacktestBarFeed`/`CsvPriceStore`, `reporting`.
- Used by: `scripts/run_backtest.py`, notebooks, external/web callers.
- Purpose: Drain the queue and route each event to its registered handler callables.
- Location: `itrader/events_handler/full_event_handler.py`
- Contains: `EventHandler.process_events()`, `_dispatch()`; the injected `HandlerErrorPolicy` seam (`error_policy.py` — `FailFastPolicy` / `ErrorPolicy`); the ERROR-route consumer `ErrorHandler.on_error()` (`error_handler.py`); the `EventBus` transport substrate (`bus.py`).
- Depends on: All handlers, `core/enums.EventType`.
- Used by: Both run loops.
- Purpose: Encapsulate domain logic (strategies, orders, execution, portfolios, screeners).
- Location: `itrader/strategy_handler/`, `itrader/order_handler/`, `itrader/execution_handler/`, `itrader/portfolio_handler/`, `itrader/screeners_handler/`.
- Contains: Thin handler classes + fat managers/sub-components.
- Depends on: `events_handler/events/`, `core/`, the shared `global_queue`.
- Used by: `EventHandler`.
- Purpose: Look-ahead-safe price storage and per-tick bar windows; `BarEvent` production.
- Location: `itrader/price_handler/store/`, `itrader/price_handler/feed/`, `itrader/price_handler/providers/`.
- Contains: `CsvPriceStore`, `SqlHandler`, `BacktestBarFeed`, CCXT/OANDA/Binance providers.
- Depends on: `pandas`; stores are read-only on the run path.
- Used by: `StrategiesHandler`, `ScreenersHandler`, and the TIME route's `generate_bar_event` factory.
- Purpose: Cross-cutting enums, exceptions, ids, money, clock, read-model protocols.
- Location: `itrader/core/` (`enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `portfolio_read_model.py`, `bar.py`, `sizing.py`), `itrader/outils/`.
- Contains: `OrderType`, `OrderStatus`, `VALID_ORDER_TRANSITIONS`, `EventType`, `Side`, `IDGenerator`, `PortfolioReadModel`.
- Depends on: Nothing inside `itrader`.
- Used by: All handlers.
- Purpose: Pydantic-modelled system configuration.
- Location: `itrader/config/`
- Contains: `ITraderConfig` (frozen root — `rng_seed`/`timezone`/identity base params + `system`/`universe`/`stream`/`feed_provider`/`safety`/`order`/`logging` sub-models + lazy `sql`), `PortfolioConfig`, `ExchangeConfig`, `SystemSettings`/`UniverseConfig`/`LogConfig`, domain models. `ITraderConfig()` is constructed directly — there is no registry or provider getter layer.
- Depends on: `pydantic`, `pydantic-settings`.
- Used by: `itrader/__init__.py`, `ExecutionHandler`, `PortfolioHandler`.
- Location: `itrader/__init__.py`
- Initialised on import: `config = ITraderConfig()`, `logger = init_logger(config)`, `idgen = IDGenerator()`.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Data Flow

### Primary Backtest Request Path

### Live Trading Path

### Bracket / Resting-Order Flow

- Portfolio positions: owned by each `Portfolio`; sub-managers in `position/`, `transaction/`, `metrics/`. Cash lives on the `Account` leaf in `account/`.
- Order mirror: `OrderManager` over a pluggable `OrderStorage` (`in_memory` / `sql` / `cached_sql`).
- Resting-order book: `MatchingEngine._resting`, one per `SimulatedExchange`.
- Live run status: `SafetyController._status` guarded by `SafetyController._status_lock` (`threading.Lock`); `LiveTradingSystem` only delegates.

## Key Abstractions

- Purpose: All inter-component messages; immutable.
- Examples: `itrader/events_handler/events/` — `TimeEvent`, `BarEvent`, `SignalEvent`, `OrderEvent`, `FillEvent`, `ScreenerEvent`, `PortfolioUpdateEvent`, `ErrorEvent`/`PortfolioErrorEvent`.
- Pattern: `msgspec.Struct` subclass of `Event` (`frozen=True, kw_only=True, gc=False`); `type` pinned via `type: ClassVar[EventType] = EventType.X`; factory class methods for safe construction.
- Purpose: Base for all trading strategies.
- Examples: `itrader/strategy_handler/base.py`; concrete `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`, `itrader/strategy_handler/my_strategies/`.
- Pattern: Subclass implements the `generate_signal(ticker)` abstractmethod returning a `SignalIntent`; the handler pushes bars via `update(ticker, bar)`, gates on `is_ready(ticker)`, and emits the resulting `SignalEvent` onto `global_queue`.
- Purpose: Pluggable exchange interface.
- Examples: `itrader/execution_handler/exchanges/base.py`; concrete `SimulatedExchange`.
- Pattern: Implements `on_order`, `on_market_data`, `connect/disconnect/health_check/validate_order`, and `snapshot() -> AccountSnapshot` (the venue-truth read; `AccountSnapshot.empty()` when no venue is behind it).
- Purpose: Narrow read boundary so `OrderManager`/`OrderHandler` query portfolios without importing the handler.
- Examples: `itrader/core/portfolio_read_model.py` — twelve methods: `available_cash`, `get_position`, `reserve`, `release`, `drop_pending`, `exchange_for`, `account_for`, `open_position_count`, `active_portfolio_ids`, `total_equity`, `maintenance_margin`, `margin_ratio`.
- Pattern: `PortfolioHandler` satisfies the Protocol structurally.
- Purpose: Look-ahead-safe data access.
- Examples: `itrader/price_handler/store/base.py`, `itrader/price_handler/feed/base.py`; concrete `CsvPriceStore`, `BacktestBarFeed`.
- Pattern: Store loads frames; feed slices per-tick windows (precompute once, `searchsorted` per tick — zero per-tick resample).
- Purpose: Pluggable order-mirror persistence.
- Examples: `itrader/order_handler/storage/in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`; built via `build_order_storage(environment, sql_engine=None)`.
- Purpose: Pluggable execution cost.
- Examples: `itrader/execution_handler/fee_model/` (`zero`, `percent`, `maker_taker`), `slippage_model/` (`zero`, `fixed`, `linear`).

## Entry Points

- Location: `itrader/trading_system/backtest/backtest_trading_system.py` — `BacktestTradingSystem.run()` (built by `build_backtest_system(spec)` from the same module)
- Triggers: `scripts/run_backtest.py` (`make backtest`), notebooks.
- Responsibilities: Wire components, derive membership + ping grid, precompute resampled frames, drive the for-loop, print/record metrics.
- Location: `itrader/trading_system/live/build.py` — `build_live_system(config, execution_venue=..., data_venue=...)` → `itrader/trading_system/live/system.py` — `LiveTradingSystem.start()`
- Triggers: External caller / web API.
- Responsibilities: Build the graph + venue accounts, bootstrap from the durable store, launch the processing thread, manage lifecycle.
- Location: `itrader/trading_system/live/system.py` — `LiveTradingSystem.add_event()`
- Triggers: Web API / external caller.
- Responsibilities: Fail-closed default-deny admission — accepts only externally-originated `SIGNAL`, `STRATEGY_COMMAND`, and `CONFIG_UPDATE` events onto the queue; a `SIGNAL` routes through `OrderHandler.on_signal` → `AdmissionManager` so validation/sizing/cash-reservation run before any `OrderEvent` is emitted.
- Location: `itrader/strategy_handler/base.py` — strategy `generate_signal(ticker)` → `SignalIntent`, which the handler turns into a `SignalEvent`.
- Triggers: `StrategiesHandler.on_bar` per BAR.

## Architectural Constraints

- **Threading (backtest):** Single-threaded synchronous for-loop; no locking needed for correctness. `PortfolioHandler` has no collection lock (single-writer contract — see the portfolio_handler section above).
- **Threading (live):** Event processing runs on one daemon thread. `Portfolio` and `SimulatedExchange` hold NO lock; the only `threading.RLock`s live on the three cached-SQL storages (`order_handler/`, `portfolio_handler/`, `strategy_handler/` `storage/cached_sql_storage.py`). Run status is guarded by `SafetyController._status_lock` (a plain `threading.Lock`).
- **Global state:** `config`, `logger`, `idgen` are module-level singletons in `itrader/__init__.py`, initialised at import time. `MatchingEngine._resting` is instance-level.
- **Import side effects:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.
- **Circular imports:** `OrderHandler` ↔ `OrderManager` resolved by constructor injection, not module imports. Avoid new module-level cross-imports between handlers.
- **Bar-timing contract:** the seven rules in `itrader/price_handler/feed/bar_feed.py` are the single written home of look-ahead safety; enforced in the window slice, never in strategies.
- **Money:** Decimal end-to-end; `float()` only at serialization/logging edges.
- **Determinism:** one shared seeded `random.Random` injected at wiring; injected `BacktestClock`.
- **Indentation:** handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, and the events package use 4 spaces — match the file.

## Anti-Patterns

### Calling handlers directly across domains

### Adding a new event type without registering it

### Matching orders inside OrderHandler / OrderManager

### Float arithmetic on money

## Error Handling

- `ErrorHandler.on_error` (`itrader/events_handler/error_handler.py`) is the real `ERROR`-route consumer (structured log sink, severity-mapped, CRITICAL alert escalation, `last_error` persist). Its whole body is wrapped in a swallowing `try/except` so a raising alert-sink/logger can never re-enter `_dispatch` and republish a fresh `ErrorEvent` (the error→error livelock). The source-side guard is in `error_policy.py::ErrorPolicy.on_handler_error`.
- `PortfolioHandler._operation_context()` tracks active operations and publishes `PortfolioErrorEvent` on failure.
- `SimulatedExchange` emits `FillEvent(REFUSED)` on rejection so the order mirror reconciles.
- `ExecutionHandler.on_order` / `on_market_data` catch per-exchange exceptions and log without re-raising (prevents queue stalls).
- Domain exceptions live in `itrader/core/exceptions/` (`base.py`, `order.py`, `portfolio.py`, `data.py`, `strategy.py`, `results.py`, `credential.py`). `strategy.py` holds `StrategyAdmissionError` — introduced by quick task `260720-ljn` as the shared ancestor of every strategy-payload refusal (unknown type, undeserializable config blob, param drift), and the one ancestor a caller names to catch "a bad strategy payload". `results.py` holds `ResultsNotFound`.

## Cross-Cutting Concerns

<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
