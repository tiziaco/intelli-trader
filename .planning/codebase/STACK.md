# Technology Stack

**Analysis Date:** 2026-06-07

## Languages

**Primary:**
- Python 3.13.1 (CPython) - All application code, tests, and scripts
- YAML - Domain config overrides under `settings/` (gitignored in production)

**Secondary:**
- Rust (via `uuid-utils` C extension) - UUIDv7 generation; consumed through `uuid_utils.compat` in `itrader/outils/id_generator.py`

## Runtime

**Environment:**
- CPython 3.13.1 (managed via pyenv; `.python-version` pins to `3.13` at repo root)

**Package Manager:**
- Poetry (virtualenvs installed in-project as `.venv/`)
- Lockfile: `poetry.lock` present and committed

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib)
- Entry point for event dispatch: `itrader/events_handler/full_event_handler.py`
- Entry point for backtest: `itrader/trading_system/backtest_trading_system.py`
- Entry point for live: `itrader/trading_system/live_trading_system.py`

**Configuration:**
- pydantic 2.13 — domain config models (`PortfolioConfig`, `ExchangeConfig`, `SystemConfig`, `DataConfig`, `TradingConfig`) under `itrader/config/`
- pydantic-settings 2.14 — `Settings(BaseSettings)` with `ITRADER_*` env-prefix in `itrader/config/settings.py`

**Logging:**
- structlog 24.4.0 — structured logging with context binding; configured in `itrader/logger.py`; outputs colored console or JSON depending on `ITRADER_JSON_LOGS`

**Testing:**
- pytest 8.4.2 — test runner; config in `pyproject.toml` `[tool.pytest.ini_options]`
- pytest-cov 5.0.0 — coverage reports (HTML at `htmlcov/`)
- pytest-watch 4.2.0 — file-watch mode
- pytest-html 4.2.0 — HTML test reports

**Type Checking:**
- mypy 2.1.0 — `--strict` clean enforced; config in `pyproject.toml` `[tool.mypy]`; several deferred subsystems excluded via `[[tool.mypy.overrides]]`

**Build/Dev:**
- `make` — task runner; `Makefile` at repo root loads `.env` via `include .env`
- pyenv — Python version management

## Key Dependencies

**Data / Numerics:**
- pandas 2.3.3 — primary data structure for OHLCV price series; used throughout all handlers
- numpy 2.2.6 — numerical operations and array computing
- scipy 1.17.1 — `linregress` for performance metrics in `itrader/reporting/performance.py`
- scikit-learn 1.9.0 — `LinearRegression`, `PolynomialFeatures` for custom indicators in `itrader/strategy_handler/my_strategies/custom_indicators/`
- statsmodels 0.14.6 — cointegration tests (`coint`, `OLS`) for pairs trading in `itrader/screeners_handler/screeners/cointegrated_pairs.py`

**Technical Analysis:**
- ta 0.11.0 — technical indicator library; used in `itrader/strategy_handler/`
- pandas-ta 0.4.71b0 — extended TA library (130+ indicators); used in `itrader/strategy_handler/sltp_models/` and strategy filters

**Database / Storage:**
- sqlalchemy 2.0.50 — ORM and engine for PostgreSQL price database in `itrader/price_handler/store/sql_store.py`
- sqlalchemy-utils 0.41.2 — `database_exists`, `create_database` helpers used by `SqlHandler`
- psycopg2-binary 2.9.12 — PostgreSQL adapter; used by SQLAlchemy engine URL `postgresql+psycopg2://`

**Exchange / Networking:**
- ccxt 4.5.56 — unified interface to 100+ crypto exchanges; used in `itrader/price_handler/providers/ccxt_provider.py`
- websocket-client — Binance live data streaming via `wss://stream.binance.com:9443`; used in `itrader/price_handler/providers/binance_stream.py` (D-live: quarantined, not on active run path)
- tpqoa — OANDA REST API wrapper; used in `itrader/price_handler/providers/oanda_provider.py` (D-oanda: deferred, not declared in `pyproject.toml`)

**ID Generation:**
- uuid-utils 0.16.0 — Rust-backed UUIDv7 implementation; accessed via `uuid_utils.compat` in `itrader/outils/id_generator.py`

**Visualization:**
- plotly 6.8.0 — interactive charts in `itrader/reporting/plots.py` (D-reporting: deferred, not on backtest path)
- tqdm 4.67.3 — progress bars during data download loops in `itrader/price_handler/ingestion.py`

**YAML:**
- pyyaml 6.0.3 — YAML parsing for domain config files

**Interactive:**
- ipython 9.14.0 — interactive REPL
- ipykernel 6.31.0 — Jupyter kernel support

## Configuration

**Environment Variables (ITRADER_ prefix):**
- `ITRADER_LOG_LEVEL` — log level (default `INFO`); read directly from `os.environ` in `itrader/logger.py`
- `ITRADER_JSON_LOGS` — enable JSON log rendering (default `false`); read from `os.environ` in `itrader/logger.py`
- `ITRADER_DATABASE_URL` — PostgreSQL DSN as `SecretStr`; required-no-default in `itrader/config/settings.py`; only needed for live path

**Settings files:**
- `settings/` directory at repo root (gitignored in production); holds per-domain YAML overrides
- Default YAML files under `settings/domains/` (e.g., `settings/portfolio_handler.default.yaml`)
- Pydantic models are the canonical source of defaults — YAML files are optional overrides

**Build config:**
- `pyproject.toml` — single source of truth for dependencies, test config (`[tool.pytest.ini_options]`), mypy config (`[tool.mypy]`), and package metadata
- `Makefile` — all developer commands; loads `.env` at top level via `include .env .EXPORT_ALL_VARIABLES`
- `.env` file present at repo root (gitignored; never read its contents)

**Process-wide singletons (initialized on `import itrader`):**
- `config` — `SystemConfig.default()` instance
- `logger` — `ITraderStructLogger` via `init_logger()`
- `idgen` — `IDGenerator()` instance
- Source: `itrader/__init__.py`

## Platform Requirements

**Development:**
- macOS or Linux (pyenv for Python version management)
- pyenv with Python 3.13 installed
- Poetry for dependency management and virtual environment
- PostgreSQL running locally on port 5432 (for price storage via `SqlHandler` — optional for pure backtest)
- OANDA `oanda.cfg` credentials file if using OANDA provider (D-oanda deferred)

**Production:**
- No deployment target currently configured (pure library/application, no web server)
- PostgreSQL database `trading_system_prices` for price history (live mode)
- Binance WebSocket access for live streaming (D-live deferred)

---

*Stack analysis: 2026-06-07*
