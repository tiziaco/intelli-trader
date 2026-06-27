# External Integrations

**Analysis Date:** 2026-06-27

> All external integrations live in `itrader/price_handler/providers/` and the SQL stores. They are **off the backtest path** — the reference `SMA_MACD` backtest runs fully offline from a committed CSV (`data/BTCUSD_1d_ohlcv_2018_2026.csv`). Most providers are deferred (D-live / D-oanda) and excluded from `mypy --strict`.

## APIs & External Services

**Crypto exchanges (market data):**
- CCXT unified exchange interface (`itrader/price_handler/providers/ccxt_provider.py`)
  - SDK/Client: `ccxt` ^4.5.56; `self.exchange = getattr(ccxt, name)()` then `fetch_ohlcv(symbol, timeframe, since, limit=1000)`
  - Auth: public OHLCV endpoints (no key for historical fetch in current code path)
  - Symbol munging: `SYMBOL[:-4] + '/' + SYMBOL[-4:]` to CCXT pair form

- Binance live kline stream (`itrader/price_handler/providers/binance_stream.py`)
  - SDK/Client: `websocket-client` (`websocket.WebSocketApp`)
  - Endpoint: `wss://stream.binance.com:9443/stream?streams=...`
  - Auth: public stream (no key)

**Forex (OANDA):**
- OANDA via `tpqoa` (`itrader/price_handler/providers/oanda_provider.py`)
  - SDK/Client: `tpqoa.tpqoa('oanda.cfg')`
  - Auth: `oanda.cfg` config file at repo root (account id + access token) — currently commented out in source

## Data Storage

**Databases:**
- PostgreSQL — price database (`itrader/price_handler/store/sql_store.py`)
  - Connection: `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices` (hardcoded inline — see CONCERNS)
  - Client: SQLAlchemy ^2.0.50 (`create_engine`, `inspect`, `text`) + `psycopg2-binary`; helpers from `sqlalchemy-utils`
  - Read-only on the run path

- PostgreSQL — live order storage (`itrader/order_handler/storage/postgresql_storage.py`)
  - Connection: `SYSTEM_DB_URL` env var, read in `itrader/trading_system/live_trading_system.py` (`_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")`); unset → falls back to in-memory storage (WR-10, no hardcoded credential fallback)
  - Status: `PostgreSQLOrderStorage` is a `NotImplementedError` placeholder

- Backtest order storage: in-memory (`itrader/order_handler/storage/in_memory_storage.py`), selected via `OrderStorageFactory`

**File Storage:**
- Local filesystem only — committed golden CSV under `data/` is the backtest price source (`CsvPriceStore`, `itrader/price_handler/store/csv_store.py`)

**Caching:**
- None (in-process pandas frames; no external cache)

## Authentication & Identity

**Auth Provider:**
- None — no user auth subsystem. External-service auth only:
  - PostgreSQL: connection-string credentials (`ITRADER_DATABASE_URL` SecretStr / `SYSTEM_DB_URL` / hardcoded sql_store DSN)
  - OANDA: `oanda.cfg` file
  - Exchange (CCXT/Binance): public endpoints, no key in current code

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Datadog). Errors flow as `ErrorEvent`/`PortfolioErrorEvent` on the queue and are sunk by `EventHandler._log_error_event`.

**Logs:**
- structlog ^24.4.0 (`itrader/logger.py`). Console (color, `ConsoleRenderer`) by default; JSON (`JSONRenderer`) when `ITRADER_JSON_LOGS` is truthy. Level via `ITRADER_LOG_LEVEL` (default INFO). Full kill-switch via `ITRADER_DISABLE_LOGS`.

## CI/CD & Deployment

**Hosting:**
- Not detected — no deployment target configured

**CI Pipeline:**
- None detected (no `.github/workflows/`, no Dockerfile, no docker-compose)

## Environment Configuration

**Required env vars (live path only):**
- `ITRADER_DATABASE_URL` - required-no-default `SecretStr` in `Settings`; live instantiation without it raises `pydantic.ValidationError`
- `SYSTEM_DB_URL` - live order-storage Postgres DSN (read in `live_trading_system.py`)

**Optional env vars:**
- `ITRADER_LOG_LEVEL` (default INFO), `ITRADER_JSON_LOGS` (default false), `ITRADER_DISABLE_LOGS` (default false), `ITRADER_HANDLER_FLAG`
- `ITRADER_*` prefix consumed by `pydantic-settings` (`env_prefix="ITRADER_"`, `extra="ignore"`)

**Secrets location:**
- `.env` at repo root (present, loaded by `Makefile` `include .env`); `oanda.cfg` for OANDA. Backtest path is env-free and never reads secrets.

## Webhooks & Callbacks

**Incoming:**
- None (no web server)

**Outgoing:**
- Binance WebSocket callbacks (`_on_open`/`_on_close`/`_on_message` on `WebSocketApp`) — inbound stream, not HTTP webhooks

---

*Integration audit: 2026-06-27*
