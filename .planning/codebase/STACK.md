# Technology Stack

**Analysis Date:** 2026-07-21

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - all application and test code under `itrader/` and `tests/`. Pinned `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - domain configuration under `settings/domains/` (e.g. `settings/domains/portfolio.default.yaml`)
- Make - developer task runner (`Makefile`, loads `.env` via `include .env`)
- INI - Alembic config (`alembic.ini`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`.venv/`)
- Lockfile: present and committed (`poetry.lock`)

## Frameworks

**Core:**
- No web framework — pure Python library/application.
- Custom in-house event queue on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^9.0.3 - test runner (`testpaths = ["tests"]`, `minversion = "8.0"`), config in `pyproject.toml::[tool.pytest.ini_options]`
- pytest-cov ^7.1.0 - coverage (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- pytest-asyncio ^1.4.0 - async tests (`asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`); required for live-connector async paths
- testcontainers ^4.14.2 (extras `[postgresql]`) - ephemeral Postgres containers for SQL-store integration tests
- backtesting 0.6.5 - gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - gating cross-validation oracle
- nautilus-trader 1.227.0 - non-gating reconciliation oracle
- scalene ^2.3.0 - CPU/memory profiler

**Build/Dev:**
- mypy ^2.1.0 - `[tool.mypy]` `strict = true`, `files = ["itrader"]`; per-module `ignore_errors` (live trading, ccxt/oanda providers, screeners, `my_strategies`) and `ignore_missing_imports` (stubless third-party libs)
- alembic ^1.18.5 - schema migrations. `alembic.ini::script_location = migrations` — the migration chain lives at repo-root `migrations/` (`migrations/env.py`), NOT under `itrader/storage/migrations/`; this is a relocation since the 2026-07-07 doc, verify path before touching migration scripts
- Make - all developer commands (`Makefile`)
- pyenv - Python version management
- poetry-core - build backend (`[build-system]`)

## Key Dependencies

**Critical:**
- pandas ^2.3.3 - primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - numerical/array computing
- Decimal (stdlib) - money is Decimal end-to-end (locked decision); float-for-money is a correctness defect
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` → native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 - domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `BaseSettings` env-var layers: `LogConfig` reads `ITRADER_*` (`itrader/config/log.py`), `SqlSettings` reads `ITRADER_DATABASE_*` (`itrader/config/sql.py`), `OkxSettings` reads plain `OKX_API_*`/`OKX_SANDBOX`/`OKX_REGION` (`itrader/config/okx_settings.py`, `env_prefix=""`, `SecretStr` end-to-end)
- msgspec ^0.21.1 - the `Event` base class IS `msgspec.Struct(frozen=True, kw_only=True, gc=False)`, not a frozen dataclass (`itrader/events_handler/events/base.py`) — the top-level CLAUDE.md description of events as `@dataclass(frozen=True, slots=True, kw_only=True)` is stale/incorrect for the event hierarchy; msgspec is also used across other hot-path value objects and SQL codecs (`core/bar.py`, `execution_handler/matching_engine.py`, `strategy_handler/signal_record.py`)

**Analytics / Strategy:**
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 - technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned beta) - extended TA library

**Infrastructure / Live:**
- sqlalchemy ^2.0.50 - ORM/engine for the shared SQL spine (`itrader/storage/engine.py::SqlEngine` — Engine + fresh MetaData, no query logic) and the price SQL store (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 - unified crypto-exchange interface; `ccxt.pro` provides the live WebSocket client for the OKX connector (`itrader/connectors/okx.py`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- structlog ^24.4.0 - structured logging with context binding (`itrader/logger.py`)
- plotly ^6.8.0 - interactive charts for performance reporting (`itrader/reporting/plots.py`)
- tqdm ^4.67.3 - progress bars during data-download loops
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`, `settings/domains/`)

**Dev REPL:**
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel

## Configuration

**Environment:**
- `.env` at repo root (present). Contains DB connection params and OKX exchange API credentials — key names only, see INTEGRATIONS.md.
- `pydantic-settings` layers:
  - `LogConfig` reads `ITRADER_*` — `log_level`, `disable_logs` only (`itrader/config/log.py`). This REPLACES the former `config/settings.py::Settings` class referenced in the 2026-07-07 doc — that module no longer exists; `LogConfig` is a slim successor carrying only the two documented logging knobs (`environment`/`timezone` moved onto the `ITraderConfig` root itself).
  - `SqlSettings` reads `ITRADER_DATABASE_*` (unified DB config, `itrader/config/sql.py`) — mounted on `ITraderConfig` as a lazy `sql` `@cached_property`, not a field
  - `OkxSettings` reads plain `OKX_API_*` / `OKX_SANDBOX` / `OKX_REGION` (credentials, `itrader/config/okx_settings.py`, `SecretStr` end-to-end, no `ITRADER_` prefix)
- `ITraderConfig` (`itrader/config/itrader_config.py`) is the single frozen root, constructed once as the `config` singleton and mutated in place (never reassigned):
  - Frozen base params (direct fields, immutable at runtime — a `setattr` raises `pydantic.ValidationError`): `rng_seed` (default 42), `environment` (`Environment` enum, `itrader/config/system.py`), `name`, `version`, `debug_mode`, `timezone` (default `"Europe/Paris"`, oracle-critical), `data_dir`, `log_dir`, `config_dir`, `cache_dir`.
  - Mutable overlay sub-models (`validate_assignment=True` each): `system: SystemSettings`, `universe: UniverseConfig`, `stream: StreamSettings`, `feed_provider: FeedProviderSettings`, `safety: SafetySettings`, `order: OrderConfig`, `logging: LogConfig`.
  - `model_config = ConfigDict(frozen=True, extra="forbid")`.
  - **Confirmed removed / do not carry forward:** the legacy `SystemConfig` root, the old `Settings` env class, `PerformanceSettings`, and `MonitoringSettings` are all absent from `itrader/config/` as of this refresh (v1.8 Phase 9 + follow-ups) — `ITraderConfig()` is constructed directly, no registry/provider getter layer exists.
- `PortfolioConfig` (`itrader/config/portfolio.py`) and `ExchangeConfig` (`itrader/config/exchange.py`) are standalone domain models outside the `ITraderConfig` tree; `ExchangeConfig` ships classmethod presets (`.default()`, `.high_fee()`).
- Domain YAML loaded from `settings/`; defaults shipped as `settings/domains/{domain}.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import

**Build:**
- `pyproject.toml` - single source of truth for dependencies, pytest config, mypy config
- `alembic.ini` - `script_location = migrations` (repo-root `migrations/`, `migrations/env.py`); `sqlalchemy.url` injected programmatically
- `Makefile` - all developer commands

**Test strictness:**
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, `--strict-markers`, `--strict-config`, `--disable-warnings`
- Markers: `unit`, `integration`, `slow`, `e2e` (folder-derived TYPE axis in `tests/conftest.py`) + `smoke`, `live` (hand-applied PURPOSE axis; `live` = real network round-trip to a venue). pytest-asyncio registers its own exempt `asyncio` marker.

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13
- Poetry for dependency management and in-project `.venv/`
- Docker (for `testcontainers`-backed Postgres integration tests)

**Production / Live:**
- PostgreSQL on port 5544 (NOT 5432 — occupied by another DB on the target machine) as the operational SQL backend (`SqlSettings` driver `postgresql+psycopg2`); SQLite is the default backtest/results arm (`SqlSettings.default()` → in-memory, `SqlSettings.results_default()` → on-disk `output/results.db`)
- Alembic migration chain applied to the operational Postgres store (repo-root `migrations/versions/`)
- OKX demo/live account with API key + secret + passphrase for the live path (paper-first, sandbox default `True`), region-aware host routing (`OkxSettings.region`: `global`/`eea`)
- OANDA API credentials in an `oanda.cfg` file (`itrader/price_handler/providers/oanda_provider.py` via `tpqoa`) — deferred subsystem (mypy `ignore_errors`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`) — deferred subsystem
- No Dockerfile, docker-compose, or CI workflow file detected in the repo root

---

*Stack analysis: 2026-07-21*
