# External Integrations

**Analysis Date:** 2026-07-21

## APIs & External Services

**Crypto exchange — OKX (live trading, paper-first, primary live venue as of v1.7):**
- Order/session transport: `itrader/connectors/okx.py::OkxConnector` — one `ccxt.pro` client on a single asyncio loop on a daemon thread (`name="okx-connector"`); owns auth, rate-limit budget, sandbox/region routing, and `connect`/`disconnect` lifecycle. Structural `LiveConnector` Protocol seam: `itrader/connectors/base.py`.
  - SDK/Client: `ccxt.pro` (`import ccxt.pro as ccxtpro`)
  - Auth: `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE` (a triple, all `SecretStr`; passphrase required) via `itrader/config/okx_settings.py::OkxSettings`
  - Routing: `OKX_SANDBOX` (default `True` = demo) + `OKX_REGION` (`global` | `eea`, default `global`) derive BOTH hosts
    - REST host: `www.okx.com` (global) / `eea.okx.com` (eea)
    - WS host: `wspap.okx.com` (global demo) / `ws.okx.com` (global live) / `wseeapap.okx.com` (eea demo) / `wseea.okx.com` (eea live)
- Order execution arm: `itrader/execution_handler/exchanges/okx.py::OkxExchange` — live sibling of `SimulatedExchange` (same `AbstractExchange` seam); submits/cancels via `connector.call`, streams order status + fills via `connector.spawn` on `watch_orders` / `watch_my_trades`, translates each fill into a `FillEvent` onto `global_queue`.
- Market-data arm: `itrader/price_handler/providers/okx_provider.py::OkxDataProvider` — native OKX business-candle WebSocket, plus REST snapshot backfill via lazily-imported `ccxt`; emits `BarsLoaded`/`BarsLoadFailed` events. Feeds `itrader/price_handler/feed/live_bar_feed.py::LiveBarFeed`.
- Reconnect supervision: `itrader/connectors/stream_supervisor.py` — exponential backoff/reconnect budget.

**Crypto exchange — Binance (data streaming):**
- Live kline streaming: `itrader/price_handler/providers/binance_stream.py` (`websocket-client`)
- Auth env: `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_API_KEY`/`_SECRET`, `BINANCE_FUTURE_TESTNET_API_KEY`/`_SECRET` (per-file usage — verify current names in the provider before wiring new consumers; these are not passed through the `pydantic-settings` layer like OKX/DB creds)

**Generic crypto exchange access — CCXT:**
- Unified provider: `itrader/price_handler/providers/ccxt_provider.py` (historical OHLCV download) — deferred subsystem (mypy `ignore_errors`/`ignore_missing_imports`)

**Forex — OANDA:**
- Provider: `itrader/price_handler/providers/oanda_provider.py` (via `tpqoa`) — deferred subsystem
- Auth: `oanda.cfg` file (external to `.env`)

**Offline replay (test/CI seam):**
- `itrader/price_handler/providers/replay_provider.py` — replays the golden CSV as confirm-gated `ClosedBar` dicts through the SAME live feed seam an OKX provider drives (`set_bar_sink` → `LiveBarFeed.update`). Used for deterministic, single-thread, CI-safe live-path exercise (paper-replay parity gate).

## Data Storage

**Databases:**
- Shared SQL spine: `itrader/storage/engine.py::SqlEngine` — a single Engine + fresh MetaData and NOTHING else (no query methods); every storage concern *composes* one `SqlEngine` by reference rather than inheriting a shared base. This is the successor to the file previously named `itrader/storage/backend.py::SqlBackend` — the module has been renamed/restructured to `engine.py::SqlEngine` as of this refresh; do not reference the old `backend.py` path.
- Backend selection: `SqlSettings` (`itrader/config/sql.py`), `env_prefix="ITRADER_DATABASE_"` — component vars `ITRADER_DATABASE_HOST`/`_PORT`/`_USER`/`_NAME`/`_PASSWORD` (default port `5544`, deliberately not 5432); URL assembled via `sqlalchemy.URL.create`. Optional verbatim override `ITRADER_DATABASE_URL`. Backend switch is config-not-code: `SqlDriver` enum (`SQLITE_PYSQLITE` default, `POSTGRESQL_PSYCOPG2`, `SQLITE_LIBSQL` reserved Turso slot).
- Fail-loud: `SqlSettings._require_pg_credentials` validator raises `pydantic.ValidationError` if Postgres is selected with no password/URL.
- Storage concerns riding the spine: `itrader/storage/halt_record_store.py`, `itrader/storage/strategy_registry_store.py`, `itrader/storage/system_stats_store.py`, `itrader/storage/system_store.py`, `itrader/storage/venue_store.py`. Order-mirror persistence has its own concern (see below).
- Order storage: `itrader/order_handler/storage/storage_factory.py::OrderStorageFactory` selects by environment string — `backtest`/`test` → `itrader/order_handler/storage/in_memory_storage.py::InMemoryOrderStorage`; `live` → `itrader/order_handler/storage/cached_sql_storage.py::CachedSqlOrderStorage` wrapping `itrader/order_handler/storage/sql_storage.py::SqlOrderStorage`. **Confirmed:** `order_handler/storage/postgresql_storage.py` no longer exists in the codebase — the `NotImplementedError` placeholder referenced by the 2026-07-07 doc and top-level CLAUDE.md is gone, replaced by the SQL/cached-SQL pair (D-05/D-06).
- Price database: PostgreSQL (`itrader/price_handler/store/sql_store.py`, read-only on the run path)

**Schema migrations:**
- Alembic chain at repo-root `migrations/` (`migrations/env.py`, `alembic.ini::script_location = migrations`) — this is a RELOCATION from the previously-documented `itrader/storage/migrations/`; that path no longer holds the chain.
- Versions present: `2cbf0bf6b0b6_operational_baseline.py`, `47f2b41f3ffe_portfolio_account_state.py`, `d10_halt_records.py`, `hl5_transaction_venue_trade_id.py`, `p05_venue_order_id.py`, `module_config.py`, `p10_strategy_portfolio_subs.py`, `strategy_registry.py`, `system_stats.py`, `system_store.py`, `venue_config.py` — the last six are new since 2026-07-07, reflecting the v1.8 Phase 9 (runtime config) and Phase 10/10.1 (strategies registry + strategy-handler refactor) schema additions.

**File Storage:**
- Committed golden OHLCV CSVs under `data/` (e.g. `data/BTCUSD_1d_ohlcv_2018_2026.csv`); run artifacts under `output/`

**Caching:**
- None (in-memory ring buffers only — `LiveBarFeed` bounded `deque` per `(symbol, timeframe)`)

## Authentication & Identity

**Auth Provider:**
- None (no end-user auth). All credentials are outbound venue/DB API keys.
- Credential discipline: `SecretStr` end-to-end for OKX (`OkxSettings`) and DB (`SqlSettings`) — masked in repr/logs, surfaced only via `.get_secret_value()` at the client edge.

## Monitoring & Observability

**Error Tracking / Alerting:**
- `itrader/trading_system/alert_sink.py` — `AlertSink` Protocol (swap-a-fake egress seam) with a `LogAlertSink` implementation (structured `logger.critical`, `alert=True`). External push (PagerDuty/Slack/webhook) remains architected-but-deferred. CRITICAL/halt `ErrorEvent`s route through this sink.
- Error route consumer: `itrader/events_handler/full_event_handler.py::EventHandler._log_error_event` — structured log sink for the `ERROR` route, self-guarded against error→error livelock (source-tagged, never republishes its own failures as new `ErrorEvent`s).

**Logs:**
- structlog (`itrader/logger.py`); console (color) or JSON renderer. Env knobs: `ITRADER_LOG_LEVEL`, `ITRADER_DISABLE_LOGS` (via `itrader/config/log.py::LogConfig`). Bind context via `get_itrader_logger().bind(component="...")`.

## CI/CD & Deployment

**Hosting:**
- None detected (no Dockerfile, docker-compose, or deploy manifest)

**CI Pipeline:**
- None detected (no `.github/workflows`, etc.)

## Environment Configuration

**Required env vars (names only — never values):**
- Logging: `ITRADER_LOG_LEVEL`, `ITRADER_DISABLE_LOGS`
- Operational DB: `ITRADER_DATABASE_HOST`, `ITRADER_DATABASE_PORT` (default 5544), `ITRADER_DATABASE_USER`, `ITRADER_DATABASE_NAME`, `ITRADER_DATABASE_PASSWORD` (or verbatim `ITRADER_DATABASE_URL`)
- OKX (live only): `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE`, `OKX_SANDBOX` (default true), `OKX_REGION` (`global`/`eea`)
- Binance (live only, per `itrader/price_handler/providers/binance_stream.py`): `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_API_KEY`/`_SECRET`, `BINANCE_FUTURE_TESTNET_API_KEY`/`_SECRET`
- OANDA (live only): credentials via `oanda.cfg`, not `.env`

**Secrets location:**
- `.env` at repo root, loaded by `Makefile` via `include .env` + `.EXPORT_ALL_VARIABLES`. Never read/quote its contents directly.
- OANDA additionally reads `oanda.cfg`.
- Per user memory: `OKX_API_*` in `.env` are a demo sub-account (no real money) — still verify `sandbox=True` before any order.

## Webhooks & Callbacks

**Incoming:**
- None (no web server component in the codebase)

**Outgoing:**
- OKX WebSocket subscriptions (`watch_orders`, `watch_my_trades`, native business-candle socket) via `ccxt.pro`
- Binance WebSocket kline subscription (`websocket-client`)
- Alert egress is a deferred seam (`AlertSink`); no outbound HTTP webhook wired this milestone

---

*Integration audit: 2026-07-21*
