# External Integrations

**Analysis Date:** 2026-06-14

All external integrations live in the **deferred/quarantined** parts of the codebase (price-data providers, live trading, SQL stores). The in-scope backtest path is fully offline: it reads a committed golden CSV and emits artifacts to `output/`. No external service is contacted on the backtest run path.

## APIs & External Services

**Crypto exchanges (data download — deferred):**
- CCXT unified exchange interface - Fetch OHLCV crypto data from any CCXT-supported exchange
  - SDK/Client: `ccxt` 4.5.56 (`itrader/price_handler/providers/ccxt_provider.py`, `CCXT_exchange`)
  - Auth: public market data via `getattr(ccxt, name)()` — no key used in current code path; keys present in `.env` for future use (see Environment Configuration)

**FX broker (data + live — deferred):**
- OANDA - Forex/CFD data download
  - SDK/Client: `tpqoa` (undeclared dependency) wrapping OANDA v20 (`itrader/price_handler/providers/oanda_provider.py`, `OANDA_exchange`)
  - Auth: `tpqoa.tpqoa('oanda.cfg')` reads a local `oanda.cfg` file (NOT the `.env`); OANDA testnet keys also present in `.env`

**Binance live stream (deferred / quarantined):**
- Binance kline WebSocket - Real-time OHLCV streaming
  - SDK/Client: `websocket` (websocket-client, undeclared) (`itrader/price_handler/providers/binance_stream.py`, `BINANCELiveStreamer`)
  - Auth: public kline stream in current code; Binance main + spot/futures testnet keys present in `.env`
  - Status: explicitly quarantined ("NOT imported on any run path; D-live owns rebuilding it")

## Data Storage

**Databases:**
- PostgreSQL — price database `trading_system_prices`
  - Connection: **hardcoded** `postgresql+psycopg2://...@localhost:5432/trading_system_prices` in `itrader/price_handler/store/sql_store.py::SqlHandler.init_engine` (does NOT read the `.env` `DATA_DB_URL` — see Concerns)
  - Client: SQLAlchemy 2.0.50 + `sqlalchemy_utils` (`database_exists`/`create_database`) + `psycopg2-binary`
  - Status: read-only on the backtest run path; primarily a download/ingest store. D-sql deferred (mypy override).
- PostgreSQL — live order persistence
  - Connection: `db_url` constructor arg (`itrader/order_handler/storage/postgresql_storage.py`)
  - Client: `PostgreSQLOrderStorage` is a `NotImplementedError` placeholder — not functional

**File Storage:**
- Local filesystem only. Golden input CSV at `data/BTCUSD_1d_ohlcv_2018_2026.csv`; run artifacts written to `output/` (`trades.csv`, `equity.csv`, `summary.json`). Frozen goldens under `tests/golden/`.
- `CsvPriceStore` (`itrader/price_handler/store/csv_store.py`) eager-loads the committed CSV — the offline read-only store used by the backtest.

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- None. No user/identity auth. The only "auth" is outbound exchange/broker API credentials (deferred). Backtest path requires no credentials.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Rollbar/etc.). Errors flow as `ErrorEvent`/`PortfolioErrorEvent` through the queue and are consumed by `EventHandler._log_error_event` (`itrader/events_handler/full_event_handler.py`).

**Logs:**
- structlog 24.4.0 (`itrader/logger.py`). Console (color) renderer by default, JSON renderer when `ITRADER_JSON_LOGS` is set. Log level from `ITRADER_LOG_LEVEL` (default `INFO`). Bound per-component via `get_itrader_logger().bind(component="...")`.

## CI/CD & Deployment

**Hosting:**
- None detected. No deployment target; the deliverable is a local deterministic backtest engine.

**CI Pipeline:**
- None. No `.github/workflows/`, no Dockerfile, no docker-compose. Gates run locally via `make test`, `make typecheck`, `make backtest`.

## Environment Configuration

**Required env vars** (keys only — values never read; sourced from `.env` via `Makefile` `include .env`):
- `DATA_DB_URL` - Price database connection (note: `sql_store.py` hardcodes its own URL and ignores this)
- `SYSTEM_DB_URL` - System database connection
- `BINANCE_MAIN_API_KEY` / `BINANCE_MAIN_API_SECRET` - Binance live (deferred)
- `BINANCE_SPOT_TESTNET_API_KEY` / `BINANCE_SPOT_TESTNET_API_SECRET` - Binance spot testnet (deferred)
- `BINANCE_FUTURE_TESTNET_API_KEY` / `BINANCE_FUTURE_TESTNET_API_SECRET` - Binance futures testnet (deferred)
- `OANDA_TESTNET_ACCOUNT_ID` / `OANDA_TESTNET_API_KEY` / `OANDA_TESTNET_API_SECRET` - OANDA testnet (deferred)
- `ITRADER_*` prefixed vars - Read by `pydantic-settings` `Settings`: `ITRADER_DATABASE_URL` (required `SecretStr` for live), `ITRADER_TIMEZONE`, `ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_ENVIRONMENT`

**Secrets location:**
- `.env` at repo root (present, gitignored-style; loaded by `Makefile`). Secrets are masked in code via `SecretStr` (`itrader/config/settings.py`) — masks `repr`/`str`/`model_dump`, reachable only via `.get_secret_value()`.
- OANDA additionally reads a local `oanda.cfg` file.
- **Concern:** `itrader/price_handler/store/sql_store.py` contains a hardcoded DB connection string with embedded credentials rather than reading from env — should be moved to config (deferred D-sql module).

## Webhooks & Callbacks

**Incoming:**
- None. No web server / HTTP endpoints in the codebase.

**Outgoing:**
- None (no outbound webhooks). The only outbound network calls are exchange/broker data fetches and the Binance WebSocket stream, all in deferred provider modules.

---

*Integration audit: 2026-06-14*
