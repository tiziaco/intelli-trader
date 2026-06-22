# External Integrations

**Analysis Date:** 2026-06-22

## APIs & External Services

**Crypto Data (deferred — D-oanda / D-live subsystems):**
- CCXT — Unified crypto-exchange HTTP API (100+ exchanges: Binance, Coinbase, Kraken, etc.)
  - SDK/Client: `ccxt` 4.5.56 (declared in `pyproject.toml`)
  - Auth: exchange API key/secret passed at runtime (not in `pyproject.toml`; likely in `.env` or runtime config)
  - Entry point: `itrader/price_handler/providers/ccxt_provider.py::CCXT_exchange`
  - Status: **deferred** (module in `[[tool.mypy.overrides]] ignore_errors = true`; not on the backtest run path)

- Binance WebSocket — Live kline (candlestick) streaming
  - SDK/Client: `websocket-client` (imported as `websocket`); **NOT declared in `pyproject.toml`** — install separately for live use
  - Auth: None required for public kline streams
  - Entry point: `itrader/price_handler/providers/binance_stream.py::BINANCELiveStreamer`
  - Status: **quarantined** (D-live; class is `import`-blocked from the run path per `itrader/price_handler/providers/__init__.py` comment)

- OANDA — Forex data provider
  - SDK/Client: `tpqoa` (third-party wrapper over OANDA REST/streaming API); **NOT declared in `pyproject.toml`** — install separately for live use
  - Auth: `oanda.cfg` file at the working directory root (passed to `tpqoa.tpqoa('oanda.cfg')`)
  - Entry point: `itrader/price_handler/providers/oanda_provider.py::OANDA_exchange`
  - Status: **deferred** (module in `[[tool.mypy.overrides]] ignore_errors = true`; not on the backtest run path)

## Data Storage

**Databases:**
- PostgreSQL (price store)
  - Connection URL: hardcoded in `SqlHandler.init_engine` as `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices` (`itrader/price_handler/store/sql_store.py`)
  - Client: SQLAlchemy 2.0.50 engine + psycopg2-binary 2.9.12 adapter; `sqlalchemy-utils` for `database_exists`/`create_database`
  - Usage: read-only on the backtest run path; write path (`to_database`) used by data ingestion scripts
  - Status: **deferred** (module in `[[tool.mypy.overrides]] ignore_errors = true`)

- PostgreSQL (live order storage)
  - Client: `PostgreSQLOrderStorage` in `itrader/order_handler/storage/postgresql_storage.py`
  - Status: **stub only** — every method raises `NotImplementedError("To be implemented in Phase 2")`; URL provided via constructor `db_url: str` (unresolved source)

**File Storage (backtest path — active):**
- Local CSV files in `data/` directory
  - Golden dataset: `data/BTCUSD_1d_ohlcv_2018_2026.csv` (pinned oracle input)
  - Additional datasets: `data/ETHUSD_1d_ohlcv.csv`, `data/SOLUSD_1d_ohlcv.csv`, `data/AAVEUSD_1d_ohlcv.csv`
  - Raw provider downloads: `data/raw/`
  - Client: `CsvPriceStore` in `itrader/price_handler/store/csv_store.py` (pandas read, eager-load)

- Local output files in `output/`
  - Backtest artifacts: `output/trades.csv`, `output/equity.csv`, `output/summary.json`
  - Produced by: `scripts/run_backtest.py` via `itrader/reporting/frames.py`, `itrader/reporting/summary.py`

**Caching:**
- None for price data (CsvPriceStore loads eagerly into memory; BarFeed precomputes windows)
- `SystemConfig.performance.enable_caching = True` and `cache_size_mb = 512` are declared fields but no caching layer is implemented on the active run path

## Authentication & Identity

**Auth Provider:**
- None — no web authentication layer; the system is a library/CLI tool with no user-facing HTTP server
- Live path bridge (`TradingInterface` in `itrader/trading_system/trading_interface.py`) exposes methods for an external/web API to enqueue orders, but auth is deferred (D-live)

**Identity / ID Generation:**
- Single UUIDv7 scheme via `IDGenerator` singleton (`itrader/outils/id_generator.py`)
- Backed by: `uuid-utils` 0.16.0 (Rust-backed); `uuid_utils.compat.uuid7()` returns native `uuid.UUID`
- All entity IDs (portfolio, order, position, transaction, strategy, signal, screener, event `event_id`) are UUIDv7 from this singleton

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, Rollbar, or similar service)

**Structured Logs:**
- structlog 24.4.0 (`itrader/logger.py`); console (colored) or JSON renderer
- Log level: `ITRADER_LOG_LEVEL` env var (default `INFO`)
- JSON mode: `ITRADER_JSON_LOGS` env var (default `false`)
- Root logger configured via `setup_logging()` called from `init_logger()` in `itrader/__init__.py`
- Error events also flow as `ErrorEvent` / `PortfolioErrorEvent` dataclasses onto the `global_queue`

**Metrics / Health Check:**
- `MonitoringSettings` fields (`metrics_port=9090`, `health_check_port=8080`, `enable_profiling=False`, `enable_tracing=False`) are declared in `itrader/config/system.py` but no implementation is active on any run path

**Performance Reporting (built-in):**
- plotly 6.8.0 — interactive equity curve and trade charts (`itrader/reporting/plots.py`)
- scipy `linregress` — regression-based performance metrics (`itrader/reporting/metrics.py`)
- Output: HTML figures (via plotly), JSON summary (`output/summary.json`), CSV frames (`output/trades.csv`, `output/equity.csv`)

## CI/CD & Deployment

**Hosting:**
- No production hosting or deployment configuration detected

**CI Pipeline:**
- None detected (no `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, etc.)

**Pre-commit:**
- `pre-commit` referenced in `Makefile::precommit` target (`pre-commit run --all-files --hook-stage manual`)
- No `.pre-commit-config.yaml` present in the repo — gate is effectively inactive

## Environment Configuration

**Required env vars (live path only):**
- `ITRADER_DATABASE_URL` — PostgreSQL connection URL (declared as `SecretStr` with no default in `itrader/config/settings.py`); raises `pydantic.ValidationError` if unset when `Settings` is instantiated. NOT required for backtest path (backtest never calls `Settings()`).

**Optional env vars (all paths):**
- `ITRADER_LOG_LEVEL` — log level override (default `INFO`), read via `os.environ` directly in `itrader/logger.py`
- `ITRADER_JSON_LOGS` — enable JSON log output (default `false`), read via `os.environ` directly in `itrader/logger.py`

**Secrets location:**
- `.env` file at repo root (present; loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`)
- `oanda.cfg` at working directory root — OANDA API credentials for live forex data (deferred)
- PostgreSQL credentials are hardcoded in `SqlHandler.init_engine` (`itrader/price_handler/store/sql_store.py`) — a known concern; see CONCERNS.md

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP server or webhook receiver detected

**Outgoing:**
- None — all external data communication is outbound polling (CCXT HTTP, OANDA REST via tpqoa) or streaming subscription (Binance WebSocket), not webhook-based

## Third-Party Library Notes

**Declared in `pyproject.toml` but deferred from strict typing:**
- `ccxt`, `ta`, `pandas_ta`, `pandas`, `scipy`, `plotly`, `sklearn`, `statsmodels`, `yaml`, `pytz`, `tqdm` — all have `ignore_missing_imports = true` in `[tool.mypy.overrides]` because they ship no type stubs

**Imported by quarantined/deferred modules but NOT declared in `pyproject.toml`:**
- `tpqoa` — OANDA provider (`itrader/price_handler/providers/oanda_provider.py`)
- `websocket` (websocket-client) — Binance streamer (`itrader/price_handler/providers/binance_stream.py`)
- Must be installed manually for live data ingestion; not part of standard `poetry install`

---

*Integration audit: 2026-06-22*
