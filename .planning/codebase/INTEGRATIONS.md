---
last_mapped_commit: 6b15b25
---
# External Integrations

**Analysis Date:** 2026-06-30

## APIs & External Services

**Crypto exchange data (offline/research):**
- CCXT (unified crypto-exchange interface) - Fetch OHLCV + tradable symbols from any CCXT-supported exchange
  - SDK/Client: `ccxt` ^4.5.56 (`itrader/price_handler/providers/ccxt_provider.py` — `CCXT_exchange`)
  - Auth: none for public market data; instantiated via `getattr(ccxt, name)()`
  - Mypy override (deferred D-oanda), not on the backtest run path

**Forex data (OANDA):**
- OANDA - FX OHLCV download/streaming
  - SDK/Client: `tpqoa` (`itrader/price_handler/providers/oanda_provider.py` — `OANDA_exchange`)
  - Auth: reads an `oanda.cfg` file at construction (`tpqoa.tpqoa('oanda.cfg')`); env vars `OANDA_TESTNET_ACCOUNT_ID`, `OANDA_TESTNET_API_KEY`, `OANDA_TESTNET_API_SECRET` documented in `.env.example`
  - Mypy override (deferred D-oanda), not on the backtest run path

**Binance live streaming (quarantined, D-live):**
- Binance WebSocket kline stream - Live OHLCV → `BarEvent`s
  - SDK/Client: `websocket-client` (`itrader/price_handler/providers/binance_stream.py` — `BINANCELiveStreamer`)
  - Auth: `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_*`, `BINANCE_FUTURE_TESTNET_*` (documented in `.env.example`)
  - Quarantined: NOT imported on any run path (D-18 deleted the legacy base); D-live owns rebuilding it

## Data Storage

**Databases:**

PostgreSQL — the durable operational store + price database (v1.6 Persistence Foundation):
- Driver: `postgresql+psycopg2` (`psycopg2-binary`), selected via `SqlDriver.POSTGRESQL_PSYCOPG2`
- Connection: assembled from component env vars `ITRADER_DATABASE_HOST`/`PORT`/`USER`/`NAME`/`PASSWORD` via `sqlalchemy.URL.create` (URL-escapes special chars). Default port `5544` (NOT 5432). Optional verbatim override `ITRADER_DATABASE_URL` (`SecretStr`).
- Config: unified `SqlSettings` (`itrader/config/sql.py`), `env_prefix="ITRADER_DATABASE_"`, fail-loud Postgres validator (requires password or url)
- Engine spine: `SqlBackend` (`itrader/storage/backend.py`) — one Engine + MetaData, composed by each storage concern
- Schema source of truth: `build_order_tables` / `build_portfolio_tables` / `build_signal_tables` registrars in `itrader/order_handler/storage/models.py`, `itrader/portfolio_handler/storage/models.py`, `itrader/strategy_handler/storage/models.py`
- Migrations: Alembic chain in `itrader/storage/migrations/versions/` — `2cbf0bf6b0b6_operational_baseline.py` (base) → `47f2b41f3ffe_portfolio_account_state.py`. `render_as_batch=True` for portable ALTER (SQLite/libSQL). URL resolved lazily in `env.py` (never in `alembic.ini`).

SQLite — the ephemeral research/results store:
- Driver: `sqlite+pysqlite`, default `:memory:` (backtest) or an on-disk file (results store, `SqlSettings.results_default()`)
- Built by `MetaData.create_all()` — runs NO Alembic, carries no `alembic_version` table (the create_all-vs-Alembic split is intentional, MIG-01/D-14)
- Results store: `itrader/results/sql_storage.py` (+ `base.py`, `models.py`, `records.py`, `serializers.py`)
- Cross-dialect types (`itrader/storage/types.py`): `Uuid(as_uuid=True)` (CHAR(32) on SQLite / native UUID on PG), `UtcIsoText` (ISO-8601 UTC TEXT both dialects), `json_variant()` (JSON on SQLite / JSONB on PG). No Decimal-as-text decorator — money never lands on SQLite this milestone (D-13).

libSQL / Turso:
- `SqlDriver.SQLITE_LIBSQL` is a SLOT only (D-15) — driver NOT added; escape path is one URL change, zero code change.

Price CSV store (offline, run path):
- `CsvPriceStore` (`itrader/price_handler/store/csv_store.py`) — eager-loads the committed golden CSV (`data/BTCUSD_1d_ohlcv_2018_2026.csv`), read-only

**Per-handler storage backends (pluggable via factories):**
- Order mirror: `OrderStorageFactory` (`itrader/order_handler/storage/storage_factory.py`) — `in_memory` (backtest/test) vs `live` (SQL spine, wrapped by `CachedSqlOrderStorage`)
- Portfolio: `itrader/portfolio_handler/storage/storage_factory.py` — `in_memory_storage.py` / `sql_storage.py` / `cached_sql_storage.py`
- Strategy/signals: `itrader/strategy_handler/storage/storage_factory.py` — same three-backend pattern

**File Storage:**
- Local filesystem only — golden datasets under `data/`, run artifacts under `output/` (`make backtest` writes `trades.csv`, `equity.csv`, `summary.json`)

**Caching:**
- In-process only — no external cache (Redis/Memcached). Caches are classified, not unified, in `docs/CACHE-CLASSIFICATION.md`:
  - (a) hot-path data cache: per-tick recent-bars feed (`itrader/price_handler/feed/bar_feed.py`, `cache_registration.py`) — Q7-protected, Arrow/columnar REJECTED on the per-tick path
  - (b) storage-index lookup: solved by Phase-3 SQL `WHERE`/indexes — documentation only
  - (c) pure-function memoization (`lru_cache`/`functools.cache`)
  - (d) live-retention working-set caches: `CachedSql*Storage` decorators (store-first write-through over an in-memory working set; `itrader/*/storage/cached_sql_storage.py`)
  - Drift guard: `tests/integration/test_cache_classification.py`

## Authentication & Identity

**Auth Provider:**
- None — no end-user auth (no web layer yet). External API auth is via env-var credentials (exchange API keys, OANDA cfg). All DB secrets are `SecretStr` (`SqlSettings.password`/`url`), masked in repr/str/logs.

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry/Datadog). Domain errors flow as `ErrorEvent`/`PortfolioErrorEvent` on the queue; `EventHandler._log_error_event` is the structured-log sink.

**Logs:**
- structlog ^24.4.0 (`itrader/logger.py`) — console (color) or JSON renderer. Component context via `get_itrader_logger().bind(component="...")`. `ITRADER_DISABLE_LOGS` kill-switch.

## CI/CD & Deployment

**Hosting:**
- None detected — no deployment target configured

**CI Pipeline:**
- None detected — no `.github/workflows`, no CI config. Quality gates run locally via `make test` / `make typecheck` / `make perf-w1`.

## Environment Configuration

**Required env vars (live/operational only — backtest needs none):**
- `ITRADER_DATABASE_HOST`, `ITRADER_DATABASE_PORT` (default 5544), `ITRADER_DATABASE_USER`, `ITRADER_DATABASE_NAME`, `ITRADER_DATABASE_PASSWORD` — operational Postgres store
- `ITRADER_DATABASE_URL` — optional verbatim override (wins when set)
- `ITRADER_LOG_LEVEL`, `ITRADER_JSON_LOGS`, `ITRADER_DISABLE_LOGS` — logging
- `BINANCE_MAIN_API_KEY`/`_SECRET`, `BINANCE_SPOT_TESTNET_*`, `BINANCE_FUTURE_TESTNET_*` — Binance live (not wired)
- `OANDA_TESTNET_ACCOUNT_ID`/`_API_KEY`/`_API_SECRET` — OANDA (also reads `oanda.cfg`)
- `DATA_DB_URL`, `SYSTEM_DB_URL` — legacy D-live seams, documented only, NOT wired to `SqlSettings` (reconciliation deferred, Open Q4/D-09)

**Secrets location:**
- `.env` at repo root (gitignored). `.env.example` is the committed, value-free surface. `alembic.ini::sqlalchemy.url` is intentionally blank — no credential-bearing URL is ever committed (SEC-01).

## Webhooks & Callbacks

**Incoming:**
- None (no web/HTTP layer present)

**Outgoing:**
- None

---

*Integration audit: 2026-06-30*
