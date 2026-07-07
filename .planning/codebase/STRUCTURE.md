# Codebase Structure

**Analysis Date:** 2026-07-07

## Directory Layout

```
intelli-trader/
├── itrader/                     # The framework package (all application code)
│   ├── __init__.py              # Singleton bootstrap: config, logger, idgen (import side effects)
│   ├── config/                  # Pydantic config models (SystemConfig, SqlSettings, OkxSettings, …)
│   ├── connectors/              # Live venue session/transport (LiveConnector Protocol, OkxConnector)
│   ├── core/                    # Cross-cutting primitives (depends on nothing in itrader)
│   │   ├── enums/               # EventType, OrderStatus, Side, SystemStatus, …
│   │   └── exceptions/          # ITraderError hierarchy by domain
│   ├── events_handler/          # Dispatch (full_event_handler.py) + events/ frozen dataclasses
│   │   └── events/              # base/market/signal/order/ack/fill/error/universe events
│   ├── execution_handler/       # ExecutionHandler + exchanges/, fee_model/, slippage_model/
│   │   └── exchanges/           # base, simulated, okx, matching_engine, venue_correlation
│   ├── order_handler/           # OrderHandler + OrderManager coordinator + 4 collaborators
│   │   ├── admission/           # AdmissionManager (signal→order pipeline)
│   │   ├── brackets/            # BracketManager, BracketBook, levels
│   │   ├── lifecycle/           # LifecycleManager (modify/cancel)
│   │   ├── reconcile/           # ReconcileManager (on_fill mirror reconcile)
│   │   └── storage/             # in_memory / cached_sql / sql order-mirror backends + factory
│   ├── portfolio_handler/       # PortfolioHandler + Portfolio + managers
│   │   ├── account/             # Account ABC; Simulated* (compute) + VenueAccount (cache) leaves
│   │   ├── cash/ position/ transaction/ metrics/   # per-portfolio sub-managers
│   │   ├── reconcile/           # VenueReconciler + drift epsilon (two-sided restart)
│   │   └── storage/             # in_memory / cached_sql / sql portfolio-state backends + factory
│   ├── price_handler/           # Data engine
│   │   ├── store/               # CsvPriceStore, SqlHandler (read-only on run path)
│   │   ├── feed/                # BacktestBarFeed, LiveBarFeed, cache_registration
│   │   ├── providers/           # OKX / CCXT / OANDA / Binance stream / Replay providers
│   │   ├── exchange/            # exchange-facing price helpers
│   │   └── ingestion.py         # bulk price ingestion
│   ├── reporting/               # Pure run-artifact builders (frames, metrics, plots, summary)
│   ├── results/                 # Run-record models + ResultsStore ABC + SqlResultsStore
│   ├── screeners_handler/       # Dynamic market screening (deferred subsystem)
│   ├── storage/                 # Shared SQL spine (SqlBackend) + types + Alembic migrations/
│   │   └── migrations/versions/ # Alembic revision files
│   ├── strategy_handler/        # StrategiesHandler + strategies/, my_strategies/, indicators/, storage/
│   ├── trading_system/          # Composition roots + run drivers
│   │   └── simulation/          # TimeGenerator (backtest driver)
│   ├── universe/                # Membership derivation + live UniverseHandler
│   └── outils/                  # id_generator, time_parser and small utilities
├── tests/                       # Test root (unit/ integration/ e2e/ golden/ support/)
├── scripts/                     # Runnable entrypoints (run_backtest, run_live_paper, cross_validate*)
├── settings/                    # YAML config (domains/*.default.yaml tracked; prod gitignored)
├── data/                        # Golden OHLCV CSV datasets
├── docs/                        # Design docs (order_handler/, portfolio_handler/, superpowers/, tests/)
├── notebooks/ · output/ · perf/ # Notebooks, run outputs, perf profiling artifacts
├── pyproject.toml               # Deps + pytest + mypy config (single source of truth)
├── alembic.ini                  # Alembic config (points at itrader/storage/migrations)
├── Makefile                     # All developer commands
└── CLAUDE.md                    # Project guidance
```

## Directory Purposes

**`itrader/trading_system/`:**
- Purpose: Composition roots and run drivers — where the component graph is wired around one queue.
- Key files: `compose.py` (shared `compose_engine`), `backtest_trading_system.py` (holder + `build_backtest_system` factory), `backtest_runner.py` (fail-fast for-loop), `live_trading_system.py` (live/paper daemon), `system_spec.py`, `simulation/time_generator.py`, `alert_sink.py`.

**`itrader/order_handler/`:**
- Purpose: Order domain — thin `OrderHandler` interface + `OrderManager` coordinator over four injected collaborators.
- Key files: `order_handler.py`, `order_manager.py`, `order.py`, `order_validator.py`, `sizing_resolver.py`, and the `admission/` `brackets/` `lifecycle/` `reconcile/` collaborator packages plus `storage/`.

**`itrader/portfolio_handler/`:**
- Purpose: Portfolio lifecycle + per-portfolio state via a pluggable `Account`.
- Key files: `portfolio_handler.py`, `portfolio.py`, `account/` (ABC + `simulated.py` + `venue.py` + `conformance.py`), `reconcile/venue_reconciler.py`, `reconcile/drift.py`, the `cash/`/`position/`/`transaction/`/`metrics/` managers, and `storage/`.

**`itrader/connectors/`:**
- Purpose: Live venue session/transport (async bottled here).
- Key files: `base.py` (`LiveConnector` Protocol), `okx.py` (`OkxConnector`).

**`itrader/storage/`:**
- Purpose: Shared SQL spine composed by every SQL storage concern + schema migrations.
- Key files: `backend.py` (`SqlBackend`, `NAMING_CONVENTION`), `types.py`, `halt_record_store.py`, `migrations/env.py`, `migrations/versions/*.py`.

**`itrader/price_handler/`:**
- Purpose: Look-ahead-safe data engine (store → feed → BarEvent) plus live providers.
- Key files: `store/csv_store.py`, `store/sql_store.py`, `feed/bar_feed.py` (bar-timing contract), `feed/live_bar_feed.py`, `providers/okx_provider.py`, `providers/replay_provider.py`.

**`itrader/core/`:**
- Purpose: Cross-cutting primitives; depends on nothing else in `itrader`.
- Key files: `money.py`, `ids.py`, `clock.py`, `bar.py`, `instrument.py`, `sizing.py`, `commission_estimator.py`, `portfolio_read_model.py`, `enums/`, `exceptions/`.

## Key File Locations

**Entry Points:**
- `scripts/run_backtest.py`: reproducible SMA_MACD oracle generator (`make backtest`).
- `scripts/run_live_paper.py`: paper replay (offline CI-safe) / OKX manual smoke.
- `itrader/trading_system/backtest_trading_system.py`: `build_backtest_system` factory.
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()` + `run_paper_replay()`.

**Configuration:**
- `itrader/config/system.py`: `SystemConfig.default()`.
- `pyproject.toml`: deps, pytest (`filterwarnings=["error"]`, strict markers/config), mypy `--strict`.
- `settings/domains/*.default.yaml`: tracked config defaults.
- `alembic.ini` + `itrader/storage/migrations/`: schema migration chain.

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: the single routing literal (`EventHandler.routes`).
- `itrader/trading_system/compose.py`: shared graph wiring.
- `itrader/execution_handler/matching_engine.py`: resting-order book / OCO.

**Testing:**
- `tests/unit/<domain>/`, `tests/integration/`, `tests/e2e/`, `tests/golden/` (artifacts, 0 collected), `tests/support/`, `tests/conftest.py` (auto-applies type marker).
- Oracle: `tests/integration/test_backtest_oracle.py`; inertness gate: `tests/integration/test_okx_inertness.py`; parity: `tests/integration/test_paper_parity.py`.

## Naming Conventions

**Files:**
- `snake_case.py` throughout, no exceptions.
- Handlers: `<domain>_handler.py`. Managers: `<domain>_manager.py`. Abstract bases: `base.py` per package.
- Storage backends: `<backend>_storage.py` (`in_memory_storage.py`, `cached_sql_storage.py`, `sql_storage.py`).
- Tests mirror source: `test_<module>.py`.
- Alembic revisions: `<revid>_<slug>.py` under `storage/migrations/versions/`.

**Directories:**
- `<domain>_handler/` for each domain; collaborator sub-packages are bare domain nouns (`admission/`, `brackets/`, `lifecycle/`, `reconcile/`, `account/`, `cash/`, `position/`).
- `snake_case` always.

**Classes:** `PascalCase`; `<Domain>Handler` (thin) + `<Domain>Manager` (logic); `Abstract<Name>` / ABC bases; `<Domain>Config`; `<Specific><Category>Error`.

## Where to Add New Code

**New event type:**
- Enum member: `itrader/core/enums/event.py::EventType`.
- Dataclass: `itrader/events_handler/events/<domain>.py` (frozen, `slots`, `kw_only`).
- Route: `itrader/events_handler/full_event_handler.py::EventHandler.routes` (even an explicit empty list).

**New strategy:**
- Reference/library strategies: `itrader/strategy_handler/strategies/`.
- User strategies: `itrader/strategy_handler/my_strategies/` (subdivided by style: `momentum/`, `mean_reversion/`, `trend_following/`, `scalping/`, plus `filters/`, `custom_indicators/`).

**New exchange / venue:**
- Exchange arm: `itrader/execution_handler/exchanges/` (subclass `AbstractExchange`).
- Connector: `itrader/connectors/` (satisfy the `LiveConnector` Protocol); wire lazily in `LiveTradingSystem.__init__`.

**New data provider:** `itrader/price_handler/providers/` (subclass the provider base).

**New order-domain behavior:**
- Signal→order gates/sizing: `order_handler/admission/`.
- Bracket assembly: `order_handler/brackets/`.
- modify/cancel verbs: `order_handler/lifecycle/`.
- fill reconciliation: `order_handler/reconcile/`.

**New SQL storage concern:** compose `itrader/storage/SqlBackend` (has-a, never inherit a shared base); add an Alembic revision under `storage/migrations/versions/`. Keep SQL-heavy imports out of package barrels (inertness gate).

**New account behavior:** extend the `Account` ABC in `portfolio_handler/account/`; `Simulated*` leaves compute, `VenueAccount` caches.

**Shared primitives / enums / exceptions:** `itrader/core/` (must not import anything else in `itrader`).

**Utilities:** `itrader/outils/` for cross-cutting helpers; `itrader/reporting/` for pure post-run artifact builders.

**Tests:** mirror the source path under `tests/unit/<domain>/`; keep `tests/unit/` dirs package-less (no `__init__.py`) to avoid top-level package collisions during full-suite collection.

## Special Directories

**`tests/golden/`:**
- Purpose: frozen oracle artifacts (trade log / equity / summary references), NOT test cases.
- Generated: Yes (re-frozen only at named D-11 re-freeze points). Committed: Yes.

**`itrader/storage/migrations/`:**
- Purpose: Alembic schema migration chain (framework-owned).
- Generated: partly (autogenerate). Committed: Yes.

**`settings/`:**
- Purpose: YAML config. `*.default.yaml` under `domains/` tracked; production overrides gitignored.

**`output/`, `perf/`, `htmlcov/`, `.venv/`, `notebooks/`:**
- Purpose: run outputs, perf profiling, coverage HTML, in-project virtualenv, exploratory notebooks. Generated; not the source of truth.

---

*Structure analysis: 2026-07-07*
