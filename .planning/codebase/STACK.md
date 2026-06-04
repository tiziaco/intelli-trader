# Technology Stack

**Analysis Date:** 2026-06-03

## Languages

**Primary:**
- Python 3.13.1 (CPython) - All application and test code

**Secondary:**
- YAML - Configuration files under `settings/`

## Runtime

**Environment:**
- CPython 3.13.1 (managed via pyenv, `.python-version` pins to `3.13`)

**Package Manager:**
- Poetry (virtualenvs installed in-project as `.venv/`)
- Lockfile: `poetry.lock` present and committed

## Frameworks

**Core:**
- No web framework — pure Python library/application

**Event System:**
- Custom in-house event queue built on `queue.Queue` (stdlib)
- Entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest 8.4.2 — test runner
- pytest-cov 5.0.0 — coverage reports (HTML at `htmlcov/`)
- pytest-watch 4.2.0 — file-watch mode
- pytest-html 4.2.0 — HTML test reports

**Build/Dev:**
- `make` — task runner (`Makefile` at repo root)
- pyenv — Python version management

## Key Dependencies

**Data Processing:**
- pandas 2.3.3 — primary data structure for OHLCV price series; used throughout all handlers
- numpy 2.2.6 — numerical operations, array computing

**Technical Analysis:**
- ta 0.11.0 — technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 — extended TA library with 130+ indicators; used in strategy filters and SLTP models (`itrader/strategy_handler/sltp_models/`, `itrader/strategy_handler/my_strategies/filters/`)

**Statistics & ML:**
- scipy 1.17.1 — `linregress` for performance metrics (`itrader/reporting/performance.py`)
- scikit-learn 1.9.0 — `LinearRegression`, `PolynomialFeatures` for custom indicators (`itrader/strategy_handler/my_strategies/custom_indicators/`)
- statsmodels 0.14.6 — cointegration tests (`coint`, `OLS`) for pairs trading (`itrader/screeners_handler/screeners/cointegrated_pairs.py`, `itrader/strategy_handler/my_strategies/mean_reversion/`)

**Database:**
- sqlalchemy 2.0.50 — ORM and engine for PostgreSQL price database (`itrader/price_handler/sql_handler.py`)
- sqlalchemy-utils 0.41.2 — `database_exists`, `create_database` helpers (`itrader/price_handler/sql_handler.py`)
- psycopg2-binary 2.9.12 — PostgreSQL adapter; required by SQLAlchemy engine URL `postgresql+psycopg2://`

**Crypto Exchange Data:**
- ccxt 4.5.56 — unified interface to 100+ crypto exchanges; used in `itrader/price_handler/exchange/CCXT.py`

**Networking:**
- websocket (from `websocket-client`) — Binance live data streaming via `wss://stream.binance.com:9443`; used in `itrader/price_handler/live_streaming/BINANCE_Live.py`

**Configuration:**
- pyyaml 6.0.3 — YAML parsing for domain config files (`itrader/config/core/provider.py`)

**Logging:**
- structlog 24.4.0 — structured logging with context binding; configured in `itrader/logger.py`; outputs to console with color support and optionally JSON

**Concurrency:**
- readerwriterlock 1.0.9 — reader-writer lock for thread-safe portfolio access (`itrader/portfolio_handler/portfolio_handler.py`)

**Utilities:**
- tqdm 4.67.3 — progress bars during data download loops (`itrader/price_handler/data_provider.py`)
- plotly 6.8.0 — interactive charts for performance reporting (`itrader/reporting/plots.py`)

**Development Only:**
- ipython 9.14.0 — interactive REPL
- ipykernel 6.31.0 — Jupyter kernel support

## Configuration

**Environment:**
- `.env` file at repo root (loaded by `Makefile` via `include .env` / `.EXPORT_ALL_VARIABLES`)
- Domain-based YAML configs loaded from `settings/` directory (gitignored)
- Config system initialized as a process-wide singleton in `itrader/__init__.py` on package import
- YAML files follow per-domain naming: `settings/{domain}.yaml` (e.g., `settings/portfolio.yaml`)
- Defaults shipped as `settings/domains/{domain}.default.yaml`
- `FileConfigProvider` auto-detects file changes and refreshes from disk; thread-safe via `threading.RLock`

**Build:**
- `pyproject.toml` — single source of truth for dependencies, test config, and package metadata
- `Makefile` — all developer commands; loads `.env` at top level

## Platform Requirements

**Development:**
- macOS or Linux (pyenv for Python version management)
- pyenv with Python 3.13 installed
- Poetry (for dependency management and virtual environment)
- PostgreSQL running locally on port 5432 (for price storage via `SqlHandler`)

**Production:**
- PostgreSQL database for price history (`trading_system_prices` database)
- PostgreSQL for order storage (live mode — `PostgreSQLOrderStorage` not yet implemented)
- OANDA API credentials in `oanda.cfg` file if using OANDA exchange
- Binance WebSocket access if using live streaming (`BINANCELiveStreamer`)

---

*Stack analysis: 2026-06-03*
