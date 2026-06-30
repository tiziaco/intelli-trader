---
last_mapped_commit: 6b15b25
---
# Codebase Structure

**Analysis Date:** 2026-06-30

## Directory Layout

```
intelli-trader/
├── itrader/                         # Application package (single source of truth)
│   ├── __init__.py                  # Singletons on import: config, logger, idgen
│   ├── config/                      # Pydantic config — SystemConfig + SqlSettings (sql.py)
│   ├── core/                        # Shared primitives; depends on NOTHING in itrader
│   │   ├── enums/                   # OrderType, OrderStatus, EventType, Side, ...
│   │   ├── exceptions/              # base/order/portfolio/data exception trees
│   │   ├── ids.py money.py clock.py bar.py sizing.py portfolio_read_model.py
│   ├── events_handler/              # The dispatcher + frozen event dataclasses
│   │   ├── full_event_handler.py    # EventHandler.routes — the dispatch registry
│   │   └── events/                  # base/market/signal/order/fill/error (by domain)
│   ├── storage/                     # ★ v1.6 SHARED SQL SPINE (domain-neutral)
│   │   ├── backend.py               # SqlBackend (Engine+MetaData) + NAMING_CONVENTION
│   │   ├── types.py                 # Uuid, UtcIsoText, json_variant (cross-dialect)
│   │   └── migrations/              # Alembic chain — DURABLE Postgres store ONLY
│   │       ├── env.py  script.py.mako
│   │       └── versions/            # 2cbf0bf6b0b6_operational_baseline, 47f2b41f3ffe_...
│   ├── results/                     # ★ v1.6 results store (4th spine concern)
│   │   ├── base.py                  # ResultsStore ABC (SQL-free re-export)
│   │   ├── records.py models.py serializers.py sql_storage.py (SqlResultsStore)
│   ├── order_handler/               # Thin OrderHandler + fat OrderManager
│   │   ├── admission/ brackets/ lifecycle/ reconcile/   # split managers
│   │   ├── base.py                  # OrderStorage ABC + IdLike
│   │   └── storage/                 # in_memory / sql / cached_sql / models / factory
│   ├── portfolio_handler/           # PortfolioHandler + Portfolio (+ sub-managers)
│   │   ├── cash/ position/ transaction/ metrics/
│   │   ├── base.py                  # PortfolioStateStorage ABC
│   │   └── storage/                 # in_memory / sql / cached_sql / models / factory
│   ├── execution_handler/           # ExecutionHandler + SimulatedExchange + MatchingEngine
│   │   ├── exchanges/ fee_model/ slippage_model/ matching_engine.py
│   ├── strategy_handler/            # StrategiesHandler + strategies
│   │   ├── strategies/ my_strategies/ indicators/
│   │   ├── storage/                 # base (SignalStore) / in_memory / sql / cached_sql / models / factory
│   ├── price_handler/               # Data engine
│   │   ├── store/ (csv_store, sql_store) feed/ (bar_feed) providers/ exchange/
│   ├── screeners_handler/  universe/  reporting/  trading_system/  outils/
│   └── trading_system/              # Composition roots + run loop
│       ├── compose.py               # Engine dataclass + compose_engine() seam
│       ├── backtest_runner.py       # BacktestRunner (for-loop)
│       ├── backtest_trading_system.py  # BacktestTradingSystem façade + _persist_results
│       ├── system_spec.py           # ScenarioSpec
│       ├── live_trading_system.py  trading_interface.py
│       └── simulation/              # TimeGenerator
├── tests/                           # unit/ integration/ e2e/ golden/ (test root — NOT test/)
├── scripts/                         # run_backtest.py, cross_validate*.py, crossval/
├── settings/                        # YAML config (gitignored prod); domains/*.default.yaml
├── data/                            # Golden OHLCV CSVs (data/raw/)
├── output/                          # results.db (on-disk SQLite results store) + run artifacts
├── docs/                            # CACHE-CLASSIFICATION.md, per-handler docs, superpowers/
├── perf/                            # Benchmark runners, workloads, tools
├── alembic.ini                      # Alembic config (script_location → itrader/storage/migrations)
├── pyproject.toml                   # Deps + pytest + mypy config (single source of truth)
├── Makefile                         # All developer commands
└── poetry.lock
```

## Directory Purposes

**`itrader/storage/` (v1.6 shared SQL spine):**
- Purpose: Domain-neutral SQL spine every storage concern *composes* (never inherits).
- Contains: `SqlBackend` (Engine + MetaData, no business logic), cross-dialect `types`, and the Alembic `migrations/` chain for the durable Postgres operational store.
- Key files: `backend.py` (`SqlBackend`, `NAMING_CONVENTION`), `types.py` (`Uuid`, `UtcIsoText`, `json_variant`), `migrations/env.py` (autogen target = `build_*_tables` registrars).

**`itrader/results/` (v1.6 results store):**
- Purpose: The 4th spine concern — a post-run sink + cross-run read-model for backtest/optimization runs.
- Contains: `ResultsStore` ABC, frozen DTOs (`RunRecord`/`PortfolioRecord`/`RunMetrics`), serializers, and `SqlResultsStore`.
- Key files: `base.py` (ABC, `MetricName` allow-list), `records.py`, `sql_storage.py` (NOT re-exported — GATE-01).

**`itrader/<domain>_handler/storage/` (per-concern persistence):**
- Purpose: Pluggable persistence per domain. Each holds: `in_memory_storage.py` (backtest), `sql_storage.py` (system of record), `cached_sql_storage.py` (live store-first wrapper), `models.py` (`build_*_tables` registrar), `storage_factory.py` (env router).
- Present for: `order_handler/`, `portfolio_handler/`, `strategy_handler/`. The matching ABCs live one level up in each domain's `base.py` (order/portfolio) or in `storage/base.py` (strategy `SignalStore`).

**`itrader/trading_system/`:**
- Purpose: Wire all components around one `global_queue`; drive the run; trigger the post-loop persistence dump.
- Key files: `compose.py` (`Engine` + `compose_engine` seam — both run modes call it), `backtest_runner.py`, `backtest_trading_system.py` (façade + `_persist_results`), `system_spec.py` (`ScenarioSpec`), `live_trading_system.py`, `trading_interface.py`.

**`itrader/order_handler/` (split managers):**
- Purpose: Thin `OrderHandler` facade + business logic split into sub-packages: `admission/` (sizing/validation gate), `brackets/` (`bracket_book.py`, `bracket_manager.py`, `levels.py`), `lifecycle/` (`lifecycle_manager.py`), `reconcile/` (`reconcile_manager.py`).

**`itrader/core/`:**
- Purpose: Cross-cutting primitives; depends on nothing inside `itrader`. `enums/`, `exceptions/`, `ids.py`, `money.py`, `clock.py`, `bar.py`, `sizing.py`, `portfolio_read_model.py`.

## Key File Locations

**Entry Points:**
- `scripts/run_backtest.py`: committed backtest driver (`make backtest`).
- `itrader/trading_system/backtest_trading_system.py`: `BacktestTradingSystem.run(persist=...)`.
- `itrader/trading_system/live_trading_system.py`: `LiveTradingSystem.start()`.

**Configuration:**
- `pyproject.toml`: deps, pytest (`filterwarnings=["error"]`, strict markers/config), mypy (`strict`, `files=["itrader"]`).
- `itrader/config/sql.py`: `SqlSettings` (driver-by-config; `env_prefix="ITRADER_DATABASE_"`; `default()`/`results_default()`).
- `alembic.ini`: Alembic config; `script_location` → `itrader/storage/migrations`.
- `.env` (present): DB URLs + exchange creds (never read contents).
- `settings/domains/*.default.yaml`: tracked YAML defaults.

**Core Logic:**
- `itrader/events_handler/full_event_handler.py`: the dispatch registry (`EventHandler.routes`).
- `itrader/execution_handler/matching_engine.py`: resting-order book + intrabar trigger/OCO.
- `itrader/storage/backend.py`: the shared `SqlBackend` spine.
- `itrader/trading_system/compose.py`: the `compose_engine` wiring seam.

**Persistence:**
- ABCs: `order_handler/base.py`, `portfolio_handler/base.py`, `strategy_handler/storage/base.py`, `results/base.py`.
- SQL stores: `*/storage/sql_storage.py`, `results/sql_storage.py`, `price_handler/store/sql_store.py`.
- Cache wrappers: `*/storage/cached_sql_storage.py`.
- Table registrars: `*/storage/models.py`, `results/models.py` (`build_*_tables`).
- Migrations: `itrader/storage/migrations/versions/*.py`.

**Testing:**
- `tests/unit/<domain>/`, `tests/integration/`, `tests/e2e/`, `tests/golden/` (artifacts).
- Oracle: `tests/integration/test_backtest_oracle.py`.
- Cache drift guard: `tests/integration/test_cache_classification.py`.

## Naming Conventions

**Files:**
- `snake_case.py` throughout.
- Handlers: `<domain>_handler.py`; managers: `<domain>_manager.py`; ABCs: `base.py` per package.
- Storage backends: `<backend>_storage.py` (`in_memory_storage.py`, `sql_storage.py`, `cached_sql_storage.py`); table registrars: `models.py`; factories: `storage_factory.py`.
- Migrations: `<revision>_<slug>.py` (Alembic-generated, e.g. `2cbf0bf6b0b6_operational_baseline.py`).
- Tests mirror source: `test_<module>.py`.

**Classes:**
- `PascalCase`; `<Domain>Handler` (thin) + `<Domain>Manager` (logic).
- Storage: `<Concern>Storage` ABC → `Sql<Concern>Storage` → `CachedSql<Concern>Storage`.
- Table registrars: `build_<concern>_tables(metadata)`.
- Config: `<Domain>Config` / `<Domain>Settings` (`SqlSettings`).

**Directories:**
- Domain packages: `<domain>_handler/`; sub-managers and storage in lowercase subdirs (`storage/`, `cash/`, `brackets/`).
- The shared spine is domain-neutral top-level: `itrader/storage/`, `itrader/results/`.

## Where to Add New Code

**New storage concern (5th spine concern):**
- ABC: a new `base.py` with one narrow `ABC` (mirror `results/base.py`).
- SQL store: `<domain>/storage/sql_storage.py` composing a `SqlBackend` by reference (has-a, never inherit).
- Table registrar: `<domain>/storage/models.py` with `build_<concern>_tables(metadata)` (idempotent, uses `itrader.storage` column types).
- Factory: `<domain>/storage/storage_factory.py` routing `backtest`/`test` → in-memory, `live` → cached SQL wrapper; SQL imports LAZY inside the `'live'` arm.
- Do NOT re-export the concrete `Sql*Storage` from any package `__init__` (GATE-01).
- If durable (Postgres): register `build_<concern>_tables` in `itrader/storage/migrations/env.py` and `alembic revision --autogenerate`.

**New cache wrapper:**
- `<domain>/storage/cached_sql_storage.py` implementing the same ABC; persist store-first, mirror under one `threading.RLock`; classify the cache in `docs/CACHE-CLASSIFICATION.md` + add a `# CACHE-CLASS:` anchor on the definition line.

**New event type:**
- Dataclass: `events_handler/events/<domain>.py` (frozen).
- Enum member: `core/enums/event.py::EventType`.
- Route: `events_handler/full_event_handler.py::EventHandler.routes`.

**New strategy:**
- User strategies: `itrader/strategy_handler/my_strategies/`; reference patterns: `strategy_handler/strategies/`.

**New handler/domain logic:**
- Thin facade `<domain>_handler.py` (queue access) + fat `<domain>_manager.py` (no queue, no handler back-ref).
- Tests: `tests/unit/<domain>/test_<module>.py`.

**Shared primitives:** `itrader/core/` (must depend on nothing inside `itrader`).

## Special Directories

**`output/`:**
- Purpose: Run artifacts + the on-disk SQLite results store (`results.db`, from `SqlSettings.results_default()`).
- Generated: Yes. Committed: No (run output).

**`itrader/storage/migrations/versions/`:**
- Purpose: Alembic revision scripts for the durable Postgres operational store.
- Generated: Yes (autogenerate + hand-review for custom-type imports). Committed: Yes.

**`settings/`:**
- Purpose: YAML config overrides. Gitignored in prod; `domains/*.default.yaml` defaults tracked.

**`tests/golden/`:**
- Purpose: Frozen oracle artifacts + cross-validation docs (0 tests collected; the byte-exact oracle test is in `tests/integration/`).

**`.planning/`:**
- Purpose: GSD planning artifacts (phases, milestones, codebase maps). Committed.

---

*Structure analysis: 2026-06-30*
