# Technology Stack

**Analysis Date:** 2026-06-27

## Languages

**Primary:**
- Python 3.13 (CPython 3.13.1) - All application and test code under `itrader/` and `tests/`. Pinned to `>=3.13,<3.14` in `pyproject.toml`; `.python-version` pins `3.13`.

**Secondary:**
- YAML - Configuration files under `settings/` (e.g. `settings/domains/portfolio.default.yaml`)
- Make - Developer task runner (`Makefile`)

## Runtime

**Environment:**
- CPython 3.13.1, managed via pyenv (`pyenv local 3.13` in `Makefile::init-env`)

**Package Manager:**
- Poetry (`[tool.poetry]` in `pyproject.toml`); virtualenvs in-project (`poetry config virtualenvs.in-project true`) as `.venv/`
- Lockfile: present and committed (`poetry.lock`, ~493 KB, last regenerated 2026-06-26)

## Frameworks

**Core:**
- No web framework — pure Python library/application
- Custom in-house event queue built on `queue.Queue` (stdlib). Dispatch entry point: `itrader/events_handler/full_event_handler.py`

**Testing:**
- pytest ^9.0.3 - Test runner (`testpaths = ["tests"]`, `minversion = "8.0"`) — **bumped from ^8.4.2 to ^9.0.3**
- pytest-cov ^7.1.0 - Coverage reports (HTML at `htmlcov/`)
- pytest-html ^4.2.0 - HTML test reports
- backtesting.py 0.6.5 - Gating cross-validation oracle (`tests/golden/CROSS-VALIDATION.md`)
- backtrader 1.9.78.123 - Gating cross-validation oracle
- nautilus-trader 1.227.0 - Non-gating reconciliation oracle

**Build/Dev:**
- mypy ^2.1.0 - `[tool.mypy]` runs `strict = true` over `itrader` (`files = ["itrader"]`); per-module `ignore_errors`/`ignore_missing_imports` overrides for deferred subsystems (live trading, sql stores, ccxt/oanda providers, screeners, `my_strategies`) and stubless third-party libs
- scalene ^2.3.0 - CPU/memory profiler used for the v1.5 backtest-performance work (`make perf-profile`, `make perf-view`)
- Make - All developer commands (`Makefile`); loads `.env` at top level via `include .env` + `.EXPORT_ALL_VARIABLES`
- pyenv - Python version management
- poetry-core - Build backend (`[build-system]`)

## Key Dependencies

**Critical (correctness / hot-path):**
- msgspec ^0.21.1 - **Added in v1.5 Phase 8 (hot-path).** Events and core value objects migrated from `@dataclass(frozen=True, slots=True)` to frozen `msgspec.Struct`. Base event is `class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False)` (`itrader/events_handler/events/base.py`). Also backs `itrader/core/bar.py`, `itrader/portfolio_handler/transaction/transaction.py`, `itrader/execution_handler/matching_engine.py`, `itrader/strategy_handler/signal_record.py`. `gc=False` opts the structs out of cyclic GC for per-tick allocation churn.
- Decimal (stdlib) - Money is Decimal end-to-end (locked project decision); float-for-money is a correctness defect. Boundary helpers in `itrader/core/money.py`.
- uuid-utils ^0.16.0 - Rust-backed UUIDv7 generation; `uuid_utils.compat.uuid7()` returns native `uuid.UUID` (`itrader/outils/id_generator.py`, event `event_id` default factory)
- pandas ^2.3.3 - Primary OHLCV data structure across all handlers
- numpy >=2.2.3,<2.3 - Numerical/array computing

**Domain / analytics:**
- scipy ^1.17.1 - `linregress` for performance metrics (`itrader/reporting/`)
- scikit-learn ^1.9.0 - `LinearRegression`, `PolynomialFeatures` for custom indicators
- statsmodels ^0.14.6 - Cointegration tests (`coint`, `OLS`) for pairs trading
- ta ^0.11.0 - Technical indicator library (`itrader/strategy_handler/`)
- pandas-ta 0.4.71b0 (pinned, beta) - Extended TA library used in strategy filters and SLTP models
- tqdm ^4.67.3 - Progress bars during data download loops

**Infrastructure:**
- pydantic ^2.13 - Domain config models (`itrader/config/*.py`)
- pydantic-settings ^2.14 - `Settings(BaseSettings)` env-var layer with `env_prefix="ITRADER_"` (`itrader/config/settings.py`)
- structlog ^24.4.0 - Structured logging with context binding (`itrader/logger.py`); console (color) or JSON renderer selected by `ITRADER_JSON_LOGS`
- sqlalchemy ^2.0.50 - ORM/engine for PostgreSQL price database (`itrader/price_handler/store/sql_store.py`)
- sqlalchemy-utils ^0.41.2 - `database_exists`, `create_database` helpers
- psycopg2-binary ^2.9.12 - PostgreSQL adapter (`postgresql+psycopg2://`)
- ccxt ^4.5.56 - Unified crypto-exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
- plotly ^6.8.0 - Interactive charts for performance reporting (`itrader/reporting/plots.py`)
- pyyaml ^6.0.3 - YAML parsing for domain config (`itrader/config/`)
- websocket-client (`websocket`) - Binance live kline streaming (`itrader/price_handler/providers/binance_stream.py`, transitive)
- tpqoa - OANDA API wrapper (`itrader/price_handler/providers/oanda_provider.py`, transitive)
- ipython ^9.14.0, ipykernel ^6.31.0 - REPL / Jupyter kernel (dev)

## Configuration

**Environment:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env`). Contains DB URLs and exchange API credentials — see INTEGRATIONS.md for key names. NEVER read on the backtest path.
- `pydantic-settings` `Settings` reads vars with prefix `ITRADER_` (`itrader/config/settings.py`, `extra="ignore"`). Secrets declared as required-no-default `SecretStr` (`database_url`) so a live instantiation fails loud; backtest path ships safe defaults (`timezone`, `log_level`, `environment`, `disable_logs`).
- Domain YAML configs loaded from `settings/` (gitignored in production); defaults shipped as `settings/domains/{domain}.default.yaml`
- Process-wide singletons (`config`, `logger`, `idgen`) initialized in `itrader/__init__.py` on import

**Build:**
- `pyproject.toml` - Single source of truth for dependencies, pytest config, and mypy config
- `Makefile` - All developer commands (test, backtest, typecheck, perf-w1/w2, perf-profile)
- `pyproject.toml::[tool.pytest.ini_options]` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`. Only `unit`, `integration`, `slow`, `e2e` markers are declared (type marker folder-derived in `tests/conftest.py`).

## Platform Requirements

**Development:**
- macOS or Linux with pyenv + Python 3.13 installed
- Poetry for dependency management and in-project `.venv/`
- No autoformatter/linter config present; mypy `--strict` is the only static-analysis gate

**Production:**
- PostgreSQL on `localhost:5432` for the price database (`trading_system_prices`) when using SQL price storage
- PostgreSQL for live order storage (`PostgreSQLOrderStorage` is a `NotImplementedError` placeholder in `itrader/order_handler/storage/postgresql_storage.py`)
- OANDA API credentials in an `oanda.cfg` file (referenced by `itrader/price_handler/providers/oanda_provider.py` via `tpqoa`)
- Binance WebSocket access for live streaming (`itrader/price_handler/providers/binance_stream.py`)
- No Dockerfile, docker-compose, or CI workflow detected

---

*Stack analysis: 2026-06-27*
