---
last_mapped_commit: 6b15b25
---
# Technology Stack

**Analysis Date:** 2026-06-30

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Domain configuration files under `settings/` (e.g. `settings/domains/portfolio.default.yaml`)
- Make - Developer task runner (`Makefile`)
- SQL (via SQLAlchemy Core/ORM) - Persistence layer; no raw `.sql` files, schema is Python-defined (`itrader/*/storage/models.py`, `itrader/results/models.py`)
- Mako - Alembic migration template (`itrader/storage/migrations/script.py.mako`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~514 KB)

## Frameworks

**Core:**
- No web framework — pure Python library/application. A FastAPI application layer is planned (drives the v1.6 SQL schema toward web-app queryability) but not yet present.
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Persistence / ORM (v1.6 — Persistence Foundation milestone):**
- SQLAlchemy ^2.0.50 - Core + ORM engine for all durable storage. Shared spine in `itrader/storage/backend.py` (`SqlBackend` = Engine + MetaData, no business logic). Cross-dialect type helpers in `itrader/storage/types.py`.
- Alembic ^1.18.5 - Migration chain for the durable Postgres operational store ONLY (`itrader/storage/migrations/`, config `alembic.ini`). The ephemeral SQLite results/research store uses `MetaData.create_all()` and runs NO Alembic.
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- msgspec ^0.21.1 - Fast frozen-struct value objects + serialization at the once-per-run boundary (`itrader/core/bar.py`, `itrader/events_handler/events/base.py`, `itrader/portfolio_handler/transaction/transaction.py`, `itrader/strategy_handler/signal_record.py`, `itrader/execution_handler/matching_engine.py`)

**Testing:**
- pytest ^9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-cov ^7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- testcontainers ^4.14.2 (extras: `postgresql`) - Spin up ephemeral PostgreSQL containers for SQL storage integration tests (v1.6 addition)
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Build/Dev:**
- mypy ^2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems (live trading, ccxt/oanda providers, screeners, `my_strategies`) and stubless third-party libs
- scalene ^2.3.0 - CPU profiler for the perf harness (`make perf-profile`; CPU-only, never wraps the gated run)
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)

## Key Dependencies

**Critical:**
- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID`. Single ID scheme (locked decision).
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` non-DB env layer (`env_prefix="ITRADER_"`, `itrader/config/settings.py`) and the unified `SqlSettings` DB layer (`env_prefix="ITRADER_DATABASE_"`, `itrader/config/sql.py`)
- msgspec ^0.21.1 - Frozen struct value objects (`Bar`, events) on the hot path; pyarrow/Arrow is explicitly REJECTED on the per-tick path (`docs/CACHE-CLASSIFICATION.md` Q7)
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect

**Infrastructure:**
- sqlalchemy ^2.0.50 - ORM/engine for the price DB, the durable operational store, and the results store
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned beta) - Extended TA library in strategy filters and SLTP models
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`, quarantined D-live)
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)
- tqdm ^4.67.3 - Progress bars during data download loops
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel (dev)

## Configuration

**Environment:**
- `.env` file at repo root (present, gitignored; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). `.env.example` is committed as the documented surface.
- Two pydantic-settings layers:
  - `Settings` (`itrader/config/settings.py`) reads NON-DB process vars with prefix `ITRADER_` (`timezone`, `log_level`, `environment`, `disable_logs`); `extra="ignore"`. Backtest path needs no `.env`.
  - `SqlSettings` (`itrader/config/sql.py`) — unified, self-contained DB config with prefix `ITRADER_DATABASE_`; `extra="forbid"`. Owns driver switch, connection params, conditional Postgres validation, and the engine-URL builder. Never constructed at import time (import-inert).
- Domain YAML configs loaded from `settings/` (gitignored in production); defaults shipped as `settings/domains/{domain}.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import
- `SqlDriver` enum (`itrader/config/sql.py`) is the config-not-code backend switch: `sqlite+pysqlite` (research/backtest default, `:memory:`), `postgresql+psycopg2` (operational store), `sqlite+libsql` (Turso-ready SLOT only, not wired)

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `alembic.ini` - Alembic config; `sqlalchemy.url` left INTENTIONALLY BLANK (SEC-01) — resolved at runtime from `SqlSettings` inside `itrader/storage/migrations/env.py`
- `Makefile` - All developer commands
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow`, `e2e` markers are declared (type marker folder-derived in `tests/conftest.py`).

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- Docker (for `testcontainers` PostgreSQL integration tests)

**Production:**
- PostgreSQL on `localhost:5544` (NOT 5432 — 5432 is taken on the target machine) for the durable operational store and the price database, configured via `ITRADER_DATABASE_*` env vars
- SQLite (in-process `:memory:` for backtest, on-disk file for the results store) — no server required
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`, quarantined)
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-06-30*
