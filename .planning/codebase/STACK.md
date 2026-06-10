# Technology Stack

**Analysis Date:** 2026-06-10

## Languages

**Primary:**
- Python 3.13 (CPython, pinned `>=3.13,<3.14` in `pyproject.toml`) - All application and test code under `itrader/` and `tests/`. `.python-version` pins `3.13`.

**Secondary:**
- YAML - Configuration files under `settings/` (e.g. `settings/domains/system.default.yaml`, `settings/domains/portfolio.default.yaml`, `settings/portfolio_handler.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

**Environment:**
- CPython 3.13, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~487 KB)

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`) (`pyproject.toml`)
- pytest-cov ^7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- backtesting (backtesting.py) 0.6.5 - Gating cross-validation oracle
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Build/Dev:**
- mypy ^2.1.0 - `[tool.mypy]` runs `strict = true` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`) and stubless third-party libs
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env` + `.EXPORT_ALL_VARIABLES`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel

## Key Dependencies

**Critical:**
- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- pydantic ^2.13 - Domain config models (`itrader/config/system.py`, `exchange.py`, `portfolio.py`, `models.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` env-var layer, `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; single ID scheme via `idgen` singleton (`itrader/outils/id_generator.py`)
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer selected via `ITRADER_JSON_LOGS`

**Analytics / Indicators:**
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests for pairs strategies
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)

**Infrastructure:**
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`, transitive) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)
- tqdm ^4.67.3 - Progress bars during data download loops

## Configuration

**Environment:**
- `.env` file at repo root (present, gitignored via `.gitignore`). Loaded by `Makefile` via `include .env`. Contains DB URLs and exchange API credentials — see `INTEGRATIONS.md` for key names (NEVER read values).
- `pydantic-settings` `Settings` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`). `database_url` is a required-no-default `SecretStr` — a live instantiation without it fails loud.
- Backtest path needs no `.env`: `timezone`/`log_level`/`environment` carry safe defaults.
- Log level read directly from `ITRADER_LOG_LEVEL` (default `INFO`) and `ITRADER_JSON_LOGS` (default off) in `itrader/logger.py` — never via a `Settings` instance at import time (avoids `ValidationError` on `import itrader`).
- Domain YAML configs loaded from `settings/` (gitignored in production); defaults shipped as `settings/domains/{domain}.default.yaml`.
- Process-wide singletons (`config = SystemConfig.default()`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import. Determinism seed: `SystemConfig.performance.rng_seed`, default 42.

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, `--strict-markers`, `--strict-config`. Declared markers: `unit`, `integration`, `slow`, `e2e` (folder-derived in `tests/conftest.py`).

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`

**Production:**
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage (`itrader/price_handler/store/sql_store.py`)
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` placeholder in `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-06-10*
