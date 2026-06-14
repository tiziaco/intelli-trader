# Technology Stack

**Analysis Date:** 2026-06-14

## Languages

**Primary:**
- Python 3.13 (CPython) - All application and test code under `itrader/` and `tests/`. Pinned `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Domain configuration under `settings/` (`settings/domains/system.default.yaml`, `settings/domains/trading.default.yaml`, `settings/domains/portfolio.default.yaml`, plus `settings/portfolio_handler*.yaml`)
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
- pytest 9.0.3 (`^9.0.3`) - Test runner; `testpaths = ["tests"]`, `minversion = "8.0"`
- pytest-cov 7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html 4.2.0 - HTML test reports
- backtesting 0.6.5 (`backtesting.py`) - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`, `scripts/cross_validate.py`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Build/Dev:**
- mypy 2.1.0 - Only static-analysis gate; `[tool.mypy]` runs `strict = true` over `files = ["itrader"]`. Per-module `ignore_errors` overrides for deferred subsystems (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`, `postgresql_storage`) and `ignore_missing_imports` for stubless third-party libs (`ta`, `pandas_ta`, `ccxt`, `pandas`, `scipy`, `plotly`, `sklearn`, `statsmodels`, etc.)
- poetry-core - Build backend (`[build-system]`)
- pyenv - Python version management
- Make - All developer commands (`Makefile`); loads `.env` at top level

## Key Dependencies

**Critical:**
- pandas 2.3.3 - Primary OHLCV data structure across all handlers
- numpy 2.2.6 (`>=2.2.3,<2.3`) - Numerical/array computing
- pydantic 2.13.4 - Domain config models (`itrader/config/*.py`)
- pydantic-settings 2.14.1 - `Settings(BaseSettings)` env-var layer, `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- uuid-utils 0.16.0 - Rust-backed UUIDv7 generation; single locked ID scheme (`itrader/outils/id_generator.py`)
- Decimal (stdlib) - Money is Decimal end-to-end (locked decision); enter via `to_money()` in `itrader/core/money.py`. Float-for-money is a correctness defect.
- structlog 24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer via `ITRADER_JSON_LOGS`

**Numerical / Strategy:**
- scipy 1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn 1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels 0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading
- ta 0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library used in strategy filters and SLTP models

**Infrastructure:**
- sqlalchemy 2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils 0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary 2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt 4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- pyyaml 6.0.3 - YAML parsing for domain config (`itrader/config/`)
- tqdm 4.67.3 - Progress bars during data download loops
- plotly 6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)

**Dev REPL:**
- ipython 9.14.0, ipykernel 6.31.0 - REPL / Jupyter kernel

**Undeclared imports (deferred/quarantined modules — NOT in `pyproject.toml`/`poetry.lock`):**
- `websocket` (websocket-client) - Imported by `itrader/price_handler/providers/binance_stream.py` (D-live quarantined; not on any run path)
- `tpqoa` - Imported by `itrader/price_handler/providers/oanda_provider.py` (OANDA wrapper; needs `oanda.cfg`)
- `readerwriterlock` - Referenced in CLAUDE.md for thread-safe portfolio access but no active import found in `itrader/` (portfolios use `threading.RLock`)

## Configuration

**Environment:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env`). Contains DB URLs and Binance/OANDA exchange credentials — see INTEGRATIONS.md for key names. Never read its values.
- `pydantic-settings` `Settings` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`). Backtest path has safe defaults (`timezone`, `log_level`, `environment`); `database_url` is a required-no-default `SecretStr` that fails loud on live instantiation.
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import. `config = SystemConfig.default()`.
- Domain YAML configs loaded from `settings/`; defaults shipped as `settings/domains/{domain}.default.yaml`

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands (`make init-env`, `make test*`, `make backtest`, `make typecheck`, `make normalize-data`)
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow`, `e2e` markers declared; the type marker is folder-derived in `tests/conftest.py`.

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage (`itrader/price_handler/store/sql_store.py`)
- OANDA API credentials in an `oanda.cfg` file for the OANDA provider (`itrader/price_handler/providers/oanda_provider.py`)

**Production:**
- No Dockerfile, docker-compose, or CI workflow detected (no `.github/`)
- Live order persistence (`PostgreSQLOrderStorage`) is a `NotImplementedError` placeholder (`itrader/order_handler/storage/postgresql_storage.py`)
- The deliverable is a deterministic backtest engine, not a deployed service; `make backtest` runs `scripts/run_backtest.py`

---

*Stack analysis: 2026-06-14*
