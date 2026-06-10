# External Integrations

**Analysis Date:** 2026-06-10

All external integrations except the local CSV golden-dataset path are **deferred** (D-live / D-oanda / D-sql in `pyproject.toml` mypy overrides). The committed backtest run path touches **no external services** — it reads CSV files from `data/` only. The integrations below exist as provider/store modules for live and data-download paths but are not on the backtest run path.

## APIs & External Services

**Crypto market data:**
- CCXT (multi-exchange) - Fetch OHLCV from any CCXT-supported exchange
  - SDK/Client: `ccxt` (`itrader/price_handler/providers/ccxt_provider.py::CCXT_exchange`)
  - Auth: public market data (no key in module); exchange selected by name via `getattr(ccxt, name)()`
  - Status: deferred (D-oanda override)

**Binance:**
- Binance kline streaming - Live OHLCV via WebSocket
  - SDK/Client: `websocket` WebSocketApp (`itrader/price_handler/providers/binance_stream.py::BINANCELiveStreamer`)
  - Auth env vars: `BINANCE_MAIN_API_KEY`, `BINANCE_MAIN_API_SECRET`, `BINANCE_SPOT_TESTNET_API_KEY`, `BINANCE_SPOT_TESTNET_API_SECRET`, `BINANCE_FUTURE_TESTNET_API_KEY`, `BINANCE_FUTURE_TESTNET_API_SECRET` (in `.env`)
  - Status: quarantined / not imported on any run path (D-live owns rebuild)

**OANDA (FX/CFD):**
- OANDA data download - OHLCV for FX/CFD pairs
  - SDK/Client: `tpqoa` (`itrader/price_handler/providers/oanda_provider.py::OANDA_exchange`)
  - Auth: `oanda.cfg` file (referenced in constructor); env vars `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET` (in `.env`)
  - Status: deferred (D-oanda override)

## Data Storage

**Databases:**
- PostgreSQL (price database `trading_system_prices`)
  - Connection: `postgresql+psycopg2://...@localhost:5432/trading_system_prices` (hard-coded in `itrader/price_handler/store/sql_store.py::SqlHandler.init_engine` — a concern, see `CONCERNS.md`); intended env var `DATA_DB_URL` (in `.env`)
  - Client: SQLAlchemy 2.0 engine + `sqlalchemy_utils.database_exists`/`create_database`
  - Status: deferred (D-sql override); read-only on the run path
- PostgreSQL (live order persistence)
  - Connection: env var `SYSTEM_DB_URL` (in `.env`); passed as `db_url` to `OrderStorageFactory.create("live", db_url)`
  - Client: `PostgreSQLOrderStorage` — `NotImplementedError` placeholder (`itrader/order_handler/storage/postgresql_storage.py`)

**File Storage:**
- Local filesystem CSV — the canonical golden-dataset read path (`data/BTCUSD_1d_ohlcv_2018_2026.csv`, plus `ETHUSD`, `SOLUSD`, `AAVEUSD` daily OHLCV; raw provider CSVs under `data/raw/`)
  - Client: `CsvPriceStore` (`itrader/price_handler/store/csv_store.py`) — read-only, eager-load at construction
  - Output artifacts written to `output/` (gitignored): trades / equity CSVs + `summary.json` via `scripts/run_backtest.py`

**Caching:**
- None on the run path (config exposes `cache_dir` and `enable_caching` knobs in `SystemConfig`, unused by backtest)

## Authentication & Identity

**Auth Provider:**
- None — no user auth / identity system. Exchange API credentials only (Binance / OANDA), all on deferred live paths.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Rollbar). Errors flow as `ErrorEvent`/`PortfolioErrorEvent` through the queue, logged by `EventHandler._log_error_event`.

**Logs:**
- structlog (`itrader/logger.py`) — console color renderer by default, JSON renderer when `ITRADER_JSON_LOGS=true`. Bound loggers via `get_itrader_logger().bind(component="...")`.

**Metrics:**
- `MonitoringSettings` declares `metrics_port` (9090), `health_check_port` (8080), `profiling_port` (8081) in `itrader/config/system.py` — config-only, no exporter wired.

## CI/CD & Deployment

**Hosting:**
- Not detected — no deployment target configured

**CI Pipeline:**
- None detected (no `.github/workflows`, no CI config). `make precommit` references `pre-commit` but no `.pre-commit-config.yaml` is present.

## Environment Configuration

**Required env vars (names only — values are secrets, never read):**
- `DATA_DB_URL` - PostgreSQL price database URL
- `SYSTEM_DB_URL` - PostgreSQL live order/system database URL
- `BINANCE_MAIN_API_KEY`, `BINANCE_MAIN_API_SECRET`
- `BINANCE_SPOT_TESTNET_API_KEY`, `BINANCE_SPOT_TESTNET_API_SECRET`
- `BINANCE_FUTURE_TESTNET_API_KEY`, `BINANCE_FUTURE_TESTNET_API_SECRET`
- `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET`
- `ITRADER_*` prefixed vars consumed by pydantic-settings (`itrader/config/settings.py`): `ITRADER_DATABASE_URL` (required `SecretStr`), `ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_TIMEZONE`, `ITRADER_ENVIRONMENT`

**Secrets location:**
- `.env` at repo root (gitignored). OANDA also expects an `oanda.cfg` file. No secrets manager / vault integration.

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP server. `TradingInterface` (`itrader/trading_system/trading_interface.py`) is an in-process bridge for an external/web API to enqueue `OrderEvent`s, not an HTTP endpoint.

**Outgoing:**
- None

---

*Integration audit: 2026-06-10*
