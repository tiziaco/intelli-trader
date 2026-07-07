# Technology Stack

**Analysis Date:** 2026-07-07

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) — all application and test code under `itrader/` and `tests/`. Pinned `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML — domain configuration under `settings/` (e.g. `settings/domains/system.default.yaml`, `settings/domains/trading.default.yaml`, `settings/domains/portfolio.default.yaml`)
- Make — developer task runner (`Makefile`, loads `.env` via `include .env`)
- INI — Alembic config (`alembic.ini`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`.venv/`)
- Lockfile: present and committed (`poetry.lock`, ~515 KB)

## Frameworks

**Core:**
- No web framework — pure Python library/application. A FastAPI application layer is planned (Phase 5, deferred) but not yet wired.
- Custom in-house event queue on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^9.0.3 — test runner (`testpaths = ["tests"]`, `minversion = "8.0"`), config in `pyproject.toml::[tool.pytest.ini_options]`
- pytest-cov ^7.1.0 — coverage (HTML at `htmlcov/`)
- pytest-html ^4.2.0 — HTML test reports
- pytest-asyncio ^1.4.0 — async tests (`asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"`); required for the live-connector async paths (Phase 2, D-08)
- testcontainers ^4.14.2 (extras `[postgresql]`) — ephemeral Postgres containers for SQL-store integration tests
- backtesting 0.6.5 — gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 — gating cross-validation oracle
- nautilus-trader 1.227.0 — non-gating reconciliation oracle
- scalene ^2.3.0 — CPU/memory profiler (`perf/`, `scalene-profile.html`)

**Build/Dev:**
- mypy ^2.1.0 — `[tool.mypy]` `strict = true`, `files = ["itrader"]`; per-module `ignore_errors` (live trading, sql/ccxt/oanda providers, screeners, `my_strategies`) and `ignore_missing_imports` (stubless third-party libs)
- alembic ^1.18.5 — schema migrations for the operational SQL store (`itrader/storage/migrations/`, `alembic.ini`)
- Make — all developer commands (`Makefile`)
- pyenv — Python version management
- poetry-core — build backend (`[build-system]`)

## Key Dependencies

**Critical:**
- pandas ^2.3.3 — primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 — numerical/array computing
- Decimal (stdlib) — money is Decimal end-to-end (locked decision); float-for-money is a correctness defect
- uuid-utils ^0.16.0 — Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` → native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 — domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 — `BaseSettings` env-var layers: `Settings` (`ITRADER_`), `SqlSettings` (`ITRADER_DATABASE_`), `OkxSettings` (plain `OKX_API_*`, `env_prefix=""`)
- msgspec ^0.21.1 — fast structured (de)serialization; used across hot-path value objects and SQL codecs (`core/bar.py`, `events_handler/events/base.py`, `events_handler/events/universe.py`, `portfolio_handler/transaction/transaction.py`, `execution_handler/matching_engine.py`, `portfolio_handler/storage/sql_storage.py`, `strategy_handler/signal_record.py`)

**Analytics / Strategy:**
- scipy ^1.17.1 — `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 — `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 — cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 — technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned beta) — extended TA library

**Infrastructure / Live:**
- sqlalchemy ^2.0.50 — ORM/engine for the operational + price SQL stores (`itrader/storage/backend.py`, `itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 — `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 — PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 — unified crypto-exchange interface; `ccxt.pro` provides the live WebSocket client for the OKX connector (`itrader/connectors/okx.py`)
- aiohttp (transitive via `ccxt.pro`) — used directly by the OKX native business-candle WebSocket in `itrader/price_handler/providers/okx_provider.py`
- websocket-client (`websocket`) — Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- structlog ^24.4.0 — structured logging with context binding (`itrader/logger.py`)
- plotly ^6.8.0 — interactive charts for performance reporting (`itrader/reporting/plots.py`)
- tqdm ^4.67.3 — progress bars during data-download loops
- pyyaml ^6.0.3 — YAML parsing for domain config (`itrader/config/`)

**Dev REPL:**
- ipython ^9.14.0, ipykernel ^6.31.0 — REPL / Jupyter kernel

## Configuration

**Environment:**
- `.env` at repo root (present, gitignored). `.env.example` committed as the documented surface.
- `pydantic-settings` layers:
  - `Settings` reads `ITRADER_*` (logging, `itrader/config/settings.py`)
  - `SqlSettings` reads `ITRADER_DATABASE_*` (unified DB config, `itrader/config/sql.py`)
  - `OkxSettings` reads plain `OKX_API_*` / `OKX_SANDBOX` / `OKX_REGION` (credentials, `itrader/config/okx_settings.py`, `SecretStr` end-to-end)
- Domain YAML loaded from `settings/`; defaults shipped as `settings/domains/{domain}.default.yaml` and `settings/portfolio_handler.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import

**Build:**
- `pyproject.toml` — single source of truth for dependencies, pytest config, mypy config
- `alembic.ini` — `script_location = itrader/storage/migrations`; `sqlalchemy.url` injected programmatically (`Config.set_main_option`)
- `Makefile` — all developer commands

**Test strictness:**
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, `--strict-markers`, `--strict-config`, `--disable-warnings`
- Markers: `unit`, `integration`, `slow`, `e2e` (folder-derived TYPE axis in `tests/conftest.py`) + `smoke`, `live` (hand-applied PURPOSE axis; `live` = real network round-trip to a venue)

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13
- Poetry for dependency management and in-project `.venv/`
- Docker (for `testcontainers`-backed Postgres integration tests)

**Production / Live:**
- PostgreSQL on `localhost:5544` (NOT 5432 — occupied by another DB on the target machine) for the operational store (`itrader`); SQLite for the research/results store
- Alembic migration chain applied to the operational Postgres store (`itrader/storage/migrations/versions/`)
- OKX demo/live account with API key + secret + passphrase for the live path (paper-first, sandbox default `True`)
- OANDA API credentials in an `oanda.cfg` file (`itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-07-07*
