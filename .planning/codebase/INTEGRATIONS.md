# External Integrations

**Analysis Date:** 2026-07-07

## APIs & External Services

**Crypto exchange — OKX (live trading, paper-first, primary live venue as of v1.7):**
- Order/session transport: `itrader/connectors/okx.py::OkxConnector` — one `ccxt.pro` client on a single asyncio loop on a daemon thread (`name="okx-connector"`); owns auth, rate-limit budget, sandbox/region routing, and `connect`/`disconnect` lifecycle. Structural `LiveConnector` Protocol seam: `itrader/connectors/base.py`.
  - SDK/Client: `ccxt.pro` (`import ccxt.pro as ccxtpro`)
  - Auth: `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` (a triple, all `SecretStr`; passphrase required) via `itrader/config/okx_settings.py::OkxSettings`
  - Routing: `OKX_SANDBOX` (default `True` = demo) + `OKX_REGION` (`global` | `eea`, default `global`) derive BOTH hosts
    - REST host: `www.okx.com` (global) / `eea.okx.com` (eea)
    - WS host: `wspap.okx.com` (global demo) / `ws.okx.com` (global live) / `wseeapap.okx.com` (eea demo) / `wseea.okx.com` (eea live), port `8443`, path `/ws/v5`
- Order execution arm: `itrader/execution_handler/exchanges/okx.py::OkxExchange` — live sibling of `SimulatedExchange` (same `AbstractExchange` seam); submits/cancels via `connector.call`, streams order status + fills via `connector.spawn` on `watch_orders` / `watch_my_trades`, translates each fill into a frozen `FillEvent` onto `global_queue`. clOrdId correlation key is Base62-of-UUID (`_CLORDID_ALPHABET`, WR-04).
- Market-data arm: `itrader/price_handler/providers/okx_provider.py::OkxDataProvider` — native OKX business-candle WebSocket over `aiohttp`, plus REST snapshot backfill via lazily-imported `ccxt`; emits `BarsLoaded` / `BarsLoadFailed` events. Feeds `itrader/price_handler/feed/live_bar_feed.py::LiveBarFeed`.
- Reconnect supervision: exponential backoff with debounce + retry ceiling → HALT on exhaustion (`_STREAM_RECONNECT_*` constants in `exchanges/okx.py`, D-19/D-20).

**Crypto exchange — Binance (data streaming):**
- Live kline streaming: `itrader/price_handler/providers/binance_stream.py` (`websocket-client`)
- Auth env: `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_API_KEY`/`_SECRET`, `BINANCE_FUTURE_TESTNET_API_KEY`/`_SECRET`

**Generic crypto exchange access — CCXT:**
- Unified provider: `itrader/price_handler/providers/ccxt_provider.py` (historical OHLCV download)

**Forex — OANDA:**
- Provider: `itrader/price_handler/providers/oanda_provider.py` (via `tpqoa`)
- Auth: `oanda.cfg` file + `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET`

**Offline replay (test/CI seam):**
- `itrader/price_handler/providers/replay_provider.py` — replays the golden CSV as confirm-gated `ClosedBar` dicts through the SAME live feed seam an OKX provider drives (`set_bar_sink` → `LiveBarFeed.update`). Used by `scripts/run_live_paper.py` for deterministic, single-thread, CI-safe live-path exercise.

## Data Storage

**Databases:**
- Operational store (live path): PostgreSQL via `postgresql+psycopg2://`
  - Connection: unified `SqlSettings` (`itrader/config/sql.py`), `env_prefix="ITRADER_DATABASE_"` — component vars `ITRADER_DATABASE_HOST`/`_PORT`/`_USER`/`_NAME`/`_PASSWORD` (default port `5544`); URL assembled via `sqlalchemy.URL.create`. Optional verbatim override `ITRADER_DATABASE_URL`.
  - Client/spine: `itrader/storage/backend.py::SqlBackend` (single Engine + MetaData; per-concern stores compose it by reference — has-a, no shared god base)
  - Concerns on the spine: order storage, portfolio-account-state, signal, results (`Sql<Concern>Storage`)
  - Fail-loud: `_require_pg_credentials` validator raises `pydantic.ValidationError` if Postgres selected with no password/URL
- Research / results store: SQLite (`SqlResultsStore`, `itrader/results/sql_storage.py`) — idempotent `create_all(checkfirst=True)`, no Alembic; DataFrames stored as byte-deterministic gzip blobs (`mtime=0` + fixed `compresslevel`, `orient="table"` JSON).
- Price database: PostgreSQL (`itrader/price_handler/store/sql_store.py`, read-only on the run path)
- Backend switch is config-not-code: `SqlDriver` enum (`SQLITE_PYSQLITE`, `POSTGRESQL_PSYCOPG2`, `SQLITE_LIBSQL` reserved Turso slot, D-15).

**Schema migrations:**
- Alembic chain at `itrader/storage/migrations/` (`env.py` imports `NAMING_CONVENTION` from `itrader/storage/backend.py` so `create_all` and autogenerate emit identical constraint names)
- Versions: `2cbf0bf6b0b6_operational_baseline.py`, `47f2b41f3ffe_portfolio_account_state.py`, `d10_halt_records.py`, `hl5_transaction_venue_trade_id.py`, `p05_venue_order_id.py`

**File Storage:**
- Committed golden OHLCV CSVs under `data/` (e.g. `data/BTCUSD_1d_ohlcv_2018_2026.csv`); run artifacts under `output/`

**Caching:**
- None (in-memory ring buffers only — `LiveBarFeed` bounded `deque` per `(symbol, timeframe)`)

## Authentication & Identity

**Auth Provider:**
- None (no end-user auth). All credentials are outbound venue/DB API keys.
- Credential discipline: `SecretStr` end-to-end for OKX (`OkxSettings`) and DB (`SqlSettings`) — masked in repr/logs, surfaced only via `.get_secret_value()` at the client edge; the OKX connector imports no domain-event module (grep-guarded) so secrets never reach event payloads.

## Monitoring & Observability

**Error Tracking / Alerting:**
- `itrader/trading_system/alert_sink.py` — `AlertSink` Protocol (swap-a-fake egress seam) with one shipped implementation `LogAlertSink` (marked structured `logger.critical`, `alert=True`). External push (PagerDuty / Slack / webhook) is architected-but-deferred (RES-01, D-06). CRITICAL/halt `ErrorEvent`s route through this sink.

**Logs:**
- structlog (`itrader/logger.py`); console (color) or JSON renderer. Env: `ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_DISABLE_LOGS`. Bind context via `get_itrader_logger().bind(component="...")`.

## CI/CD & Deployment

**Hosting:**
- None detected (no Dockerfile, docker-compose, or deploy manifest)

**CI Pipeline:**
- None detected (no `.github/workflows`, etc.)

## Environment Configuration

**Required env vars (see `.env.example`):**
- Logging: `ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_DISABLE_LOGS`
- Operational DB: `ITRADER_DATABASE_HOST`, `ITRADER_DATABASE_PORT` (5544), `ITRADER_DATABASE_USER`, `ITRADER_DATABASE_NAME`, `ITRADER_DATABASE_PASSWORD` (or verbatim `ITRADER_DATABASE_URL`)
- OKX (live only): `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE`, `OKX_SANDBOX` (default true), `OKX_REGION` (global/eea)
- Binance (live only): `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_API_KEY`/`_SECRET`, `BINANCE_FUTURE_TESTNET_API_KEY`/`_SECRET`
- OANDA (live only): `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET`
- Legacy D-live seams (documented-only, not wired): `DATA_DB_URL`, `SYSTEM_DB_URL`

**Secrets location:**
- `.env` at repo root (gitignored); `.env.example` committed as the documented surface (no real secrets). OANDA additionally reads `oanda.cfg`.
- NOTE: `OKX_API_*` in `.env` are a demo sub-account (no real money), authorized for live-sandbox tests — still verify `sandbox=True` before any order.

## Webhooks & Callbacks

**Incoming:**
- None (no web server yet; FastAPI application layer deferred to a later phase)

**Outgoing:**
- OKX WebSocket subscriptions (`watch_orders`, `watch_my_trades`, native business-candle socket) via `ccxt.pro` / `aiohttp`
- Binance WebSocket kline subscription (`websocket-client`)
- Alert egress is a deferred seam (`AlertSink`); no outbound HTTP webhook wired this milestone

---

*Integration audit: 2026-07-07*
