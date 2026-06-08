# External Integrations

**Analysis Date:** 2026-06-08

## APIs & External Services

**Crypto market data (CCXT):**
- CCXT unified exchange API - Historical OHLCV download
  - SDK/Client: `ccxt` ^4.5.56 (`itrader/price_handler/providers/ccxt_provider.py`)
  - Exchange selected dynamically: `getattr(ccxt, name)()` (line 19); no API key required for public OHLCV (`fetch_ohlcv`, lines 112/116)
  - Symbol convention: `BTCUSDT` → `BTC/USDT` (`ccxt_provider.py:108`)
  - Errors handled: `ccxt.NetworkError`, `ccxt.ExchangeError`

**Crypto live streaming (Binance):**
- Binance WebSocket kline stream - Real-time bars (live mode only)
  - Client: `websocket-client` (`itrader/price_handler/providers/binance_stream.py`)
  - Endpoint: `wss://stream.binance.com:9443/stream?streams=` (`binance_stream.py:201`), built per-symbol as `<sym>@kline_<timeframe>` (line 205)
  - Auth: `BINANCE_MAIN_API_KEY` / `BINANCE_MAIN_API_SECRET` (and SPOT/FUTURE testnet variants) in `.env`; public kline stream itself needs no auth

**Forex (OANDA — deferred):**
- OANDA v20 API - Forex data download (`OANDA_exchange` in `itrader/price_handler/providers/oanda_provider.py`)
  - Client: `tpqoa` reading credentials from `oanda.cfg` (`oanda_provider.py:34`); `tpqoa` is NOT a declared dependency — provider is non-functional until installed
  - Auth: `OANDA_TESTNET_ACCOUNT_ID` / `OANDA_TESTNET_API_KEY` / `OANDA_TESTNET_API_SECRET` in `.env`
  - mypy-deferred (`tool.mypy.overrides`, D-oanda)

## Data Storage

**Databases:**
- PostgreSQL - Price history store
  - Client: SQLAlchemy 2.0 engine + `sqlalchemy-utils` (`itrader/price_handler/store/sql_store.py`)
  - Connection: HARDCODED in `sql_store.py:17` as `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices` (inline credentials — see CONCERNS). `.env` also exposes `DATA_DB_URL` and `SYSTEM_DB_URL`, which appear unused by the SQL store.
  - Auto-creates the database via `database_exists` / `create_database`
- PostgreSQL - Live order storage (NOT implemented)
  - `PostgreSQLOrderStorage.__init__` raises `NotImplementedError` (`itrader/order_handler/storage/postgresql_storage.py`); placeholder for live mode

**File Storage:**
- CSV price store - `itrader/price_handler/store/csv_store.py`
- Golden reference dataset: `data/BTCUSD_1d_ohlcv_2018_2026.csv` (the fixed backtest input)

**In-memory storage (backtest):**
- `InMemoryOrderStorage` - Default order mirror for backtest (`itrader/order_handler/storage/in_memory_storage.py`); selected via `OrderStorageFactory` (`itrader/order_handler/storage/storage_factory.py`)

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- None for the application — no end-user auth layer
- Exchange API keys (Binance, OANDA) are credentials for outbound data providers, stored in `.env`

**Internal IDs:**
- Single UUIDv7 scheme via Rust-backed `uuid-utils` (`itrader/outils/id_generator.py`); time-ordered, collision-safe, index-friendly (RFC 9562)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Rollbar/etc. detected)

**Logs:**
- structlog (`itrader/logger.py`); `setup_logging(json_logs, log_level)` chooses `structlog.processors.JSONRenderer` (production) or `structlog.dev.ConsoleRenderer(colors=True)` (dev). Level/JSON toggled by env (`_env_log_level`, `_env_json_logs`). Bind a component logger via `get_itrader_logger().bind(component="...")`.

## CI/CD & Deployment

**Hosting:**
- Not configured — no deployment target detected

**CI Pipeline:**
- None (no `.github/workflows/`, no `.pre-commit-config.yaml`)

## Environment Configuration

**Required env var KEYS** (names only, from `.env`; values not read):
- `DATA_DB_URL`, `SYSTEM_DB_URL` - Database URLs
- `BINANCE_MAIN_API_KEY`, `BINANCE_MAIN_API_SECRET`
- `BINANCE_SPOT_TESTNET_API_KEY`, `BINANCE_SPOT_TESTNET_API_SECRET`
- `BINANCE_FUTURE_TESTNET_API_KEY`, `BINANCE_FUTURE_TESTNET_API_SECRET`
- `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET`
- pydantic-settings reads `ITRADER_`-prefixed vars (`itrader/config/settings.py`)

**Secrets location:**
- `.env` at repo root (exchange keys + DB URLs), loaded by `Makefile`
- `oanda.cfg` expected by the OANDA provider (`tpqoa`)
- NOTE: PostgreSQL credentials are hardcoded inline in `itrader/price_handler/store/sql_store.py:17` rather than sourced from env

## Webhooks & Callbacks

**Incoming:**
- None (no web server / HTTP endpoints in repo)

**Outgoing:**
- Binance WebSocket callbacks: `_on_open`, `_on_close`, `_on_message` registered on `websocket.WebSocketApp` (`itrader/price_handler/providers/binance_stream.py:52`); `run_forever()` drives the stream

---

*Integration audit: 2026-06-08*
