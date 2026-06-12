# External Integrations

**Analysis Date:** 2026-06-12

## APIs & External Services

**Crypto Exchange Data (deferred — D-oanda subsystem):**
- CCXT unified exchange library - Fetches OHLCV data from any CCXT-supported exchange (Binance, KuCoin, etc.)
  - SDK/Client: `ccxt ^4.5.56`
  - Implementation: `itrader/price_handler/providers/ccxt_provider.py::CCXT_exchange`
  - Auth: Exchange-specific API keys (not currently wired in pyproject; legacy provider not on backtest run path)
  - Status: Deferred (mypy `ignore_errors = true`, not imported on run path)

**OANDA REST API (deferred — D-oanda subsystem):**
- OANDA v20 API - Fetches forex OHLCV historical data
  - SDK/Client: `tpqoa` (not declared in `pyproject.toml`; loaded via transitive install)
  - Auth: `oanda.cfg` file in working directory (`itrader/price_handler/providers/oanda_provider.py` calls `tpqoa.tpqoa('oanda.cfg')`)
  - Implementation: `itrader/price_handler/providers/oanda_provider.py::OANDA_exchange`
  - Status: Deferred (mypy `ignore_errors = true`, not imported on run path)

**Binance WebSocket Stream (deferred — D-live subsystem):**
- Binance klines WebSocket - Streams live OHLCV bar data
  - SDK/Client: `websocket-client` (`websocket` package)
  - Endpoint: `wss://stream.binance.com:9443/stream?streams=...`
  - Implementation: `itrader/price_handler/providers/binance_stream.py::BINANCELiveStreamer`
  - Auth: None (public WebSocket endpoint for market data)
  - Status: Quarantined (comment: "D-live module — not imported anywhere"; marked in mypy overrides)

## Data Storage

**Databases:**
- PostgreSQL (price storage)
  - Connection: `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices` (hardcoded in `itrader/price_handler/store/sql_store.py::SqlHandler.init_engine` — a known concern)
  - Client: SQLAlchemy ^2.0.50 (`create_engine`, `inspect`, `text`) + sqlalchemy-utils for `database_exists`/`create_database`
  - Adapter: psycopg2-binary ^2.9.12
  - Usage: Read-only on the backtest run path; `itrader/price_handler/store/sql_store.py` used only during data-download/normalize scripts

- PostgreSQL (live order storage)
  - Connection: `ITRADER_DATABASE_URL` env var (via `Settings.database_url: SecretStr`)
  - Client: `itrader/order_handler/storage/postgresql_storage.py::PostgreSQLOrderStorage` — **stub only** (`NotImplementedError` on all methods; tagged "Phase 2")
  - Status: Not wired; deferred (mypy `ignore_errors = true`)

**File Storage:**
- Local CSV files under `data/` — golden OHLCV datasets:
  - `data/BTCUSD_1d_ohlcv_2018_2026.csv` — primary backtest golden dataset
  - `data/BTCUSD_1d_ohlcv.csv`, `data/ETHUSD_1d_ohlcv.csv`, `data/SOLUSD_1d_ohlcv.csv`, `data/AAVEUSD_1d_ohlcv.csv`
  - Raw provider CSVs under `data/raw/` (normalized via `scripts/normalize_data.py`)
  - Loaded by `itrader/price_handler/store/csv_store.py::CsvPriceStore` (eager load on init)

**Caching:**
- None — no Redis, Memcached, or similar external cache detected. In-memory dict caching inside `CsvPriceStore` (precomputed resampled frames via `pandas`) at run init.

## Authentication & Identity

**Auth Provider:**
- Custom UUIDv7 scheme — no external auth provider
  - Implementation: `itrader/outils/id_generator.py::IDGenerator`, backed by `uuid-utils ^0.16.0`
  - All entity IDs (orders, portfolios, positions, signals, fills, events) are `uuid.UUID` produced by `uuid_utils.compat.uuid7()`
  - Process singleton: `idgen = IDGenerator()` initialized in `itrader/__init__.py`

**OANDA Auth:**
- `oanda.cfg` file — OANDA v20 credentials (account ID, access token). Expected at working directory root; read by `tpqoa.tpqoa('oanda.cfg')`.

## Monitoring & Observability

**Error Tracking:**
- None — no Sentry, Datadog, or external error tracker detected.

**Logs:**
- structlog ^24.4.0 — structured logging with component context binding (`itrader/logger.py`)
- Console output: colored `ConsoleRenderer` by default
- JSON output: enabled via `ITRADER_JSON_LOGS=true` env var; UUID-safe serializer (`WR-01`) handles `uuid.UUID` values
- Log level: controlled via `ITRADER_LOG_LEVEL` env var (default `INFO`)
- All components bind: `self.logger = get_itrader_logger().bind(component="ClassName")`

**Metrics / Health Check:**
- `MonitoringSettings` in `itrader/config/system.py` declares ports (`metrics_port=9090`, `health_check_port=8080`, `profiling_port=8081`) but none are wired to an actual server — configuration-only stubs.

## CI/CD & Deployment

**Hosting:**
- Not detected — no Dockerfile, docker-compose, Heroku, Fly.io, or cloud deployment config found.

**CI Pipeline:**
- Not detected — no GitHub Actions, CircleCI, or similar CI workflow files found.

**Pre-commit:**
- `Makefile` has a `precommit: pre-commit run --all-files --hook-stage manual` target, but no `.pre-commit-config.yaml` is present in the repo root.

## Environment Configuration

**Required env vars (live path):**
- `ITRADER_DATABASE_URL` — PostgreSQL DSN (`SecretStr`, required-no-default in `itrader/config/settings.py`; absent = `ValidationError` on live init)

**Optional env vars (backtest path safe without them):**
- `ITRADER_LOG_LEVEL` — Logging level (default `INFO`)
- `ITRADER_JSON_LOGS` — JSON log rendering toggle (default `false`/off)

**Secrets location:**
- `.env` at repo root (gitignored; loaded by `Makefile` via `include .env`)
- `oanda.cfg` at working directory root (gitignored via `credentials*` glob in `.gitignore`)

## Cross-Validation & Testing Oracles

**backtesting 0.6.5 (dev dependency):**
- Gating cross-validation oracle for metrics validation
- Referenced in `tests/golden/CROSS-VALIDATION.md` and `tests/unit/reporting/test_metrics.py`

**backtrader 1.9.78.123 (dev dependency):**
- Second gating cross-validation oracle

**nautilus-trader 1.227.0 (dev dependency):**
- Non-gating reconciliation oracle (results informational, not CI-blocking)

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP server or webhook endpoint detected.

**Outgoing:**
- None — no outbound HTTP webhook calls detected.

## Data Download Utilities

**Scripts (offline, not on run path):**
- `scripts/normalize_data.py` — normalizes raw provider CSVs under `data/raw/` into the golden OHLCV schema (`data/<TICKER>_1d_ohlcv.csv`)
- `scripts/run_backtest.py` — generates the deterministic backtest oracle (`tests/golden/trades.csv`, `tests/golden/equity.csv`, `tests/golden/summary.json`)
- `scripts/cross_validate.py` / `scripts/crossval/` — cross-validation helpers

---

*Integration audit: 2026-06-12*
