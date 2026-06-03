# External Integrations

**Analysis Date:** 2026-06-03

## APIs & External Services

**Cryptocurrency Exchanges (via CCXT):**
- CCXT-supported exchanges (Binance, Kraken, etc.) — historical OHLCV data download for backtesting
  - SDK/Client: `ccxt` 4.4.65
  - Auth: No API key needed for public OHLCV data; key/secret would be exchange-specific env vars
  - Implementation: `itrader/price_handler/exchange/CCXT.py` — `CCXT_exchange` class; instantiates any exchange via `getattr(ccxt, name)()`

**Binance WebSocket (Live Streaming):**
- Binance klines WebSocket stream — real-time candlestick data for live trading
  - SDK/Client: `websocket-client` (websocket stdlib wrapper)
  - Endpoint: `wss://stream.binance.com:9443/stream?streams=`
  - Auth: No auth for public klines stream
  - Implementation: `itrader/price_handler/live_streaming/BINANCE_Live.py` — `BINANCELiveStreamer` class; builds multi-symbol stream URL dynamically and emits `PingEvent` to the global queue on bar close

**OANDA (Forex):**
- OANDA REST API — historical OHLCV data for forex instruments
  - SDK/Client: `tpqoa` (not in `pyproject.toml` — must be installed separately or is a transitive dep)
  - Auth: Requires `oanda.cfg` file at working directory root; format defined by tpqoa library
  - Implementation: `itrader/price_handler/exchange/OANDA.py` — `OANDA_exchange` class
  - Note: Has unresolved TODOs (`load_markets()` call doesn't exist on tpqoa); partially broken

## Data Storage

**Databases:**
- PostgreSQL — price history storage and (future) order storage
  - Connection: Hardcoded in `itrader/price_handler/sql_handler.py`: `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices`
  - Client: SQLAlchemy 2.0.38 with psycopg2-binary 2.9.10
  - Auto-creates database if it does not exist via `sqlalchemy_utils.create_database`
  - Tables: One table per ticker symbol (dynamic, lowercase ticker name)
  - Live order storage: `itrader/order_handler/storage/postgresql_storage.py` — stub only, raises `NotImplementedError` throughout (Phase 2 placeholder)

**File Storage:**
- YAML configuration files — written/read by `FileConfigProvider` in `itrader/config/core/provider.py`
  - Location: `settings/` directory at repo root (gitignored in production)
  - Auto-created on first write
  - Backup copies preserved in `settings/backups/`

**In-Memory Storage:**
- Order storage for backtesting: `itrader/order_handler/storage/in_memory_storage.py`
- Price data: Class-level dict on `PriceHandler` base class (`itrader/price_handler/base.py`)

**Caching:**
- Config file cache in `FileConfigProvider` — mtime-based invalidation, no external cache service

## Authentication & Identity

**Auth Provider:**
- None — no user authentication system in the trading framework itself
- API-key based auth for exchange connections (OANDA via `oanda.cfg`, CCXT per-exchange)
- `SecuritySettings` in `itrader/config/system/config.py` defines fields for future API key auth (`enable_api_key_auth`, session timeout, rate limiting) but none are wired up

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, or similar integration

**Logs:**
- structlog 24.4.0 — structured logging with key-value context
- Logger initialized as process-wide singleton in `itrader/__init__.py` via `init_logger(config)`
- Console output: colored, human-readable format (ISO timestamps, component-prefixed messages)
- Optional JSON output: toggle via `setup_logging(json_logs=True)` in `itrader/logger.py`
- File logging: configurable in `settings/domains/system.default.yaml` (`logging.enable_file_logging`, `logging.log_file`)
- Each component binds its name: `get_itrader_logger().bind(component="ComponentName")`

**Metrics / Health Check:**
- `MonitoringSettings` in `itrader/config/system/config.py` declares ports (9090 metrics, 8080 health), but no metrics server is wired up
- `SystemConfig.monitoring.enable_profiling` / `enable_tracing` flags exist but are not connected to any backend

**Notifications (Configured, Not Active):**
- `NotificationSettings` in `itrader/config/system/config.py` defines fields for:
  - Email (SMTP): `enable_email`, `email_smtp_host`, `email_smtp_port`, `email_username`
  - Slack: `enable_slack`, `slack_webhook_url`
  - Discord: `enable_discord`, `discord_webhook_url`
- None of these are wired to actual sending logic in the codebase

## CI/CD & Deployment

**Hosting:**
- Not configured — no deployment manifests, Dockerfiles, or cloud config present

**CI Pipeline:**
- None — no `.github/workflows/`, `.circleci/`, or similar CI config detected

**Version Control:**
- Git (repository: `https://github.com/tiziaco/IntelliTrade.com`)
- Sensitive files gitignored: `.env`, `credentials*`, `.venv/`, `settings/` (YAML configs)

## Environment Configuration

**Required env vars / config files:**
- `.env` at repo root — loaded by `Makefile` for `make` targets; specific keys not determinable without reading contents
- `settings/` YAML files — domain configs for `portfolio`, `trading`, `data`, `system`, `exchange` domains; loaded lazily by `ConfigRegistry` on first access
- `oanda.cfg` — required only when using `OANDA_exchange`; read by `tpqoa.tpqoa('oanda.cfg')`
- PostgreSQL credentials — hardcoded in `itrader/price_handler/sql_handler.py` (connection string not driven by env vars)

**Secrets location:**
- `.env` file (gitignored)
- `oanda.cfg` file (not tracked — not in `.gitignore` explicitly but `credentials*` pattern covers it)
- PostgreSQL credentials are currently hardcoded in `itrader/price_handler/sql_handler.py` — not externalised

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP server or webhook receiver implemented

**Outgoing:**
- Binance WebSocket callbacks: `_on_open`, `_on_close`, `_on_error`, `_on_message` in `itrader/price_handler/live_streaming/BINANCE_Live.py`
- These are not outgoing HTTP webhooks but WebSocket event callbacks feeding into the internal event queue

---

*Integration audit: 2026-06-03*
