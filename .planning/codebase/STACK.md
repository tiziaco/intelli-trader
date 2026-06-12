# Technology Stack

**Analysis Date:** 2026-06-12

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Configuration overrides under `settings/` (e.g. `settings/domains/portfolio.default.yaml`, `settings/portfolio_handler.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry; virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`)

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom event queue built on `queue.Queue` (stdlib). Dispatch entry: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-cov ^7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- backtesting 0.6.5 - Gating cross-validation oracle (dev dependency)
- backtrader 1.9.78.123 - Gating cross-validation oracle (dev dependency)
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle (dev dependency)

**Build/Dev:**
- Make - All developer commands (`Makefile`; loads `.env` at top via `include .env`)
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)
- mypy ^2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`)

## Key Dependencies

**Data & Numerics:**
- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/metrics.py`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` in custom indicators (`itrader/strategy_handler/my_strategies/custom_indicators/`)
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) in `itrader/screeners_handler/`

**Technical Analysis:**
- ta ^0.11.0 - Technical indicator library used in `itrader/strategy_handler/`
- pandas-ta 0.4.71b0 (pinned beta) - Extended TA library used in strategy filters and SLTP models

**Infrastructure:**
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` env-var layer with `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)
- tqdm ^4.67.3 - Progress bars during data download loops

**Database / Persistence:**
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)

**Exchange / Market Data:**
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- tpqoa (transitive, not in pyproject.toml) - OANDA v20 REST wrapper (`itrader/price_handler/providers/oanda_provider.py`)

**Visualization:**
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)

**Dev / REPL:**
- ipython ^9.14.0 - REPL
- ipykernel ^6.31.0 - Jupyter kernel

## Configuration

**Environment:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). Contains DB URLs and exchange API credentials.
- `pydantic-settings` `Settings` reads env vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`).
- Required env vars (backtest path only needs none; live path requires all):
  - `ITRADER_DATABASE_URL` — PostgreSQL connection string (required `SecretStr`, no default; live path fails loud without it)
  - `ITRADER_LOG_LEVEL` — Logging level (optional, default `INFO`)
  - `ITRADER_JSON_LOGS` — JSON log rendering toggle (optional, default `false`)
- OANDA: `oanda.cfg` file expected at the working directory root (read by `tpqoa.tpqoa('oanda.cfg')` in `itrader/price_handler/providers/oanda_provider.py`)

**Domain YAML:**
- Domain YAML configs loaded from `settings/` (gitignored in production; `.default.yaml` defaults tracked under `settings/domains/`):
  - `settings/domains/system.default.yaml`
  - `settings/domains/portfolio.default.yaml`
  - `settings/domains/trading.default.yaml`
  - `settings/portfolio_handler.yaml` (active; loaded by portfolio config)

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, mypy config, and package metadata
- `[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow`, `e2e` markers are declared (type marker folder-derived in `tests/conftest.py`).
- `[tool.mypy]` - `strict = true`, `files = ["itrader"]`; deferred modules excluded via `[[tool.mypy.overrides]]` with `ignore_errors = true` (tagged by deferral category: D-live, D-sql, D-oanda, D-screener)

**Process-wide singletons (initialized on import):**
- `itrader/__init__.py` initializes `config = SystemConfig.default()`, `logger = init_logger(config)`, `idgen = IDGenerator()` on import.
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`.

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`

**Production (live trading only):**
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` stub in `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file at working directory root
- Binance WebSocket access (`wss://stream.binance.com:9443/stream`) for live streaming
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-06-12*
