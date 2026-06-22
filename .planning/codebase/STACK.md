# Technology Stack

**Analysis Date:** 2026-06-22

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Configuration override files under `settings/` (e.g. `settings/domains/system.default.yaml`, `settings/domains/portfolio.default.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (build backend: `poetry-core`); virtualenvs installed in-project as `.venv/` (`poetry config virtualenvs.in-project true`)
- Lockfile: present and committed (`poetry.lock`, 111 resolved packages)

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Configuration:**
- pydantic 2.13.4 - Domain config models (`itrader/config/*.py`)
- pydantic-settings 2.14.1 - `Settings(BaseSettings)` env-var layer with `env_prefix="ITRADER_"` (`itrader/config/settings.py`)

**Testing:**
- pytest 9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`)
- pytest-cov 7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html 4.2.0 - HTML test reports

**Cross-Validation Oracles (dev-only):**
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Static Analysis:**
- mypy 2.1.0 - `[tool.mypy]` runs `--strict` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems and stubless third-party libs

**Build/Dev:**
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env`
- pyenv - Python version management

## Key Dependencies

**Data & Numerics:**
- pandas 2.3.3 - Primary OHLCV data structure across all handlers; `DataFrame` is the canonical price container
- numpy 2.2.6 - Numerical/array computing (pinned `>=2.2.3,<2.3` in `pyproject.toml`)
- scipy 1.17.1 - `linregress` for performance metrics (`itrader/reporting/metrics.py`)
- scikit-learn 1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators in `my_strategies/`
- statsmodels 0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading screeners

**Technical Indicators:**
- ta 0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned beta) - Extended TA library used in strategy filters and SLTP models in `my_strategies/`

**IDs:**
- uuid-utils 0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`). Single UUIDv7 scheme — do not introduce a second ID scheme.

**Money:**
- `decimal.Decimal` (stdlib) - Money is Decimal end-to-end (locked project decision). `float()` appears only at the serialization/logging edge. Entry point: `to_money(x)` in `itrader/core/money.py`.

**Database / Storage:**
- sqlalchemy 2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils 0.41.2 - `database_exists`, `create_database` helpers used in `SqlHandler.init_engine`
- psycopg2-binary 2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices`)

**External Data:**
- ccxt 4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`); 100+ exchange support

**Logging:**
- structlog 24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer. Bound via `get_itrader_logger().bind(component="ClassName")`.

**Visualization:**
- plotly 6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)

**Config / Serialization:**
- pyyaml 6.0.3 - YAML parsing for domain config (`itrader/config/`)

**Progress:**
- tqdm 4.67.3 - Progress bars during data download loops

**Dev REPL:**
- ipython 9.14.0, ipykernel 6.31.0 - REPL / Jupyter kernel for notebook exploration

## Configuration

**Environment:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`). Contains DB URL and potentially exchange credentials.
- `pydantic-settings` `Settings(BaseSettings)` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`).
- Required env vars (live path only):
  - `ITRADER_DATABASE_URL` — PostgreSQL connection URL; declared as `SecretStr` with NO default, raises `ValidationError` if unset on a live instantiation. Not needed for backtest path.
- Optional env vars (all paths):
  - `ITRADER_LOG_LEVEL` — log level, default `INFO`; read via `os.environ` directly in `itrader/logger.py` (not via `Settings`) to avoid import-time `ValidationError`
  - `ITRADER_JSON_LOGS` — enable JSON log renderer, default `false`

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands

**Domain YAML Overrides (optional):**
- Defaults shipped as `settings/domains/{domain}.default.yaml`; production overrides gitignored
- `settings/domains/system.default.yaml` — logging, performance, database, cache, security, environment settings
- `settings/domains/portfolio.default.yaml` — portfolio limits, threading, validation, events settings
- `settings/domains/trading.default.yaml` — trading-specific defaults

**Process-Wide Singletons (initialized at import):**
- `config = SystemConfig.default()` — Pydantic system config
- `logger = init_logger(config)` — structlog structured logger
- `idgen = IDGenerator()` — UUIDv7 ID generator
- Location: `itrader/__init__.py`
- Import idiom: `from itrader import config, idgen` / `from itrader import logger`
- **Warning:** importing anything from `itrader` triggers singleton init. Do not import `itrader` in fixtures without understanding this.

**Test Configuration:**
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`, `--strict-markers`, `--strict-config`
- Registered markers: `unit`, `integration`, `slow`, `e2e` — any other marker fails the suite
- Type marker is folder-derived in `tests/conftest.py`; no marker in tests/unit/* needed (auto-applied)

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13.1 installed
- Poetry for dependency management and in-project `.venv/`
- No Dockerfile, docker-compose, or CI workflow detected

**Production / Live:**
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` stub — `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file (`itrader/price_handler/providers/oanda_provider.py`)
- Binance WebSocket access for live kline streaming (`itrader/price_handler/providers/binance_stream.py`)
- `tpqoa` and `websocket-client` are imported by deferred/quarantined provider modules but are NOT declared in `pyproject.toml` — install separately for live use

---

*Stack analysis: 2026-06-22*
