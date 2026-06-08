# Technology Stack

**Analysis Date:** 2026-06-08

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Configuration files under `settings/` (e.g. `settings/domains/portfolio.default.yaml`, `settings/portfolio_handler.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs installed in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~492 KB)

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^8.4.2 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-cov ^5.0.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-watch ^4.2.0 - File-watch mode (`make test-watch`)
- pytest-html ^4.2.0 - HTML test reports

**Cross-Validation (dev-only):**
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Type Checking / Build:**
- mypy ^2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems and stubless third-party libs
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)

## Key Dependencies

**Data / Numerical:**
- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading

**Technical Analysis:**
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library used in strategy filters and SLTP models

**Identity / Money / Validation:**
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`)
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` env-var layer with `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect

**Persistence:**
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)

**External Data / Streaming:**
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- tqdm ^4.67.3 - Progress bars during data download loops

**Logging / Reporting:**
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)

**Concurrency:**
- readerwriterlock (transitive/used) - Reader-writer lock for thread-safe portfolio access (`itrader/portfolio_handler/portfolio_handler.py`)

**Interactive (dev):**
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel

## Configuration

**Environment:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). Contains DB URLs and exchange API credentials — see INTEGRATIONS.md for key names.
- `pydantic-settings` `Settings` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`)
- Domain YAML configs loaded from `settings/` (gitignored in production); defaults shipped as `settings/domains/{domain}.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import

**Build / Tooling:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands

**Test Strictness:**
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow` markers are declared (folder-derived in `tests/conftest.py`).

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage

**Production / Live (deferred subsystems):**
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` placeholder in `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-06-08*
