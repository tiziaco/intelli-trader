# External Integrations

**Analysis Date:** 2026-06-07

## APIs & External Services

**Crypto Exchange Data (CCXT):**
- ccxt 4.5.56 — unified interface to 100+ crypto exchanges (Binance, Coinbase, Kraken, etc.)
  - SDK/Client: `ccxt` package; instantiated as `getattr(ccxt, name)()` in `itrader/price_handler/providers/ccxt_provider.py`
  - Auth: No API key required for public OHLCV data download; private endpoints would need exchange-specific keys
  - Status: Active — used by `CCXT_exchange.download_data()` for historical OHLCV ingestion
  - Data: `fetch_ohlcv()` with paginated 1000-bar requests

**Binance Live Streaming:**
- websocket-client — WebSocket connection to `wss://stream.binance.com:9443/stream`
  - SDK/Client: `websocket.WebSocketApp` in `itrader/price_handler/providers/binance_stream.py`
  - Auth: None (public stream endpoint)
  - Status: **Quarantined / D-live deferred** — `BINANCELiveStreamer` is not imported on any active run path; `prices` buffer reference broken after Store/Feed split. Rebuilding is deferred to D-live milestone.
  - Protocol: Subscribes to `{symbol}@kline_{timeframe}` streams; processes closed-bar messages

**OANDA REST API:**
- tpqoa — OANDA REST v20 wrapper (not declared in `pyproject.toml`)
  - SDK/Client: `tpqoa.tpqoa('oanda.cfg')` in `itrader/price_handler/providers/oanda_provider.py`
  - Auth: `oanda.cfg` credentials file at repo root (must be provided manually; gitignored)
  - Status: **D-oanda deferred** — `oanda_provider.py` excluded from mypy scope; not on active backtest run path

## Data Storage

**Price Database (PostgreSQL):**
- PostgreSQL — OHLCV price history storage
  - Connection: Hardcoded as `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices` in `itrader/price_handler/store/sql_store.py` (tech debt: credentials in source)
  - Client: SQLAlchemy 2.0.50 + psycopg2-binary 2.9.12
  - Usage: `SqlHandler` in `itrader/price_handler/store/sql_store.py` — `to_database()`, `read_prices()`, `get_symbols_SQL()`
  - Auto-creates database if missing via `sqlalchemy-utils.create_database()`
  - Status: **D-sql deferred** — `sql_store.py` excluded from mypy scope; not exercised on the golden backtest path (CSV feed used instead)

**Order Storage (PostgreSQL — Live Mode):**
- PostgreSQL — persistent order mirror for live trading
  - Client: `itrader/order_handler/storage/postgresql_storage.py` — `PostgreSQLOrderStorage`
  - Status: **Not implemented** — all methods raise `NotImplementedError("To be implemented in Phase 2")`; storage factory returns `InMemoryOrderStorage` for backtest

**CSV File Storage (Active — Backtest):**
- Local filesystem — OHLCV golden dataset
  - Location: `data/BTCUSD_1d_ohlcv_2018_2026.csv`
  - Client: `itrader/price_handler/store/csv_store.py`
  - Status: Active — this is the primary data source for all backtest runs

**In-Memory Storage (Active — Backtest):**
- `itrader/order_handler/storage/in_memory_storage.py` — `InMemoryOrderStorage`
  - Used for all backtest runs via `OrderStorageFactory.create('backtest')`
  - No external dependency
- `itrader/portfolio_handler/storage/in_memory_storage.py` — portfolio state
  - No external dependency

## Authentication & Identity

**Auth Provider:**
- None — no authentication provider integrated
- Implementation: No auth layer; live API credentials are file-based (`oanda.cfg`) or env-var based (`ITRADER_DATABASE_URL`)

**ID Generation:**
- uuid-utils 0.16.0 (Rust-backed) — UUIDv7 time-ordered IDs
  - Implementation: `IDGenerator` in `itrader/outils/id_generator.py`; wraps `uuid_utils.compat.uuid7()` returning stdlib `uuid.UUID`
  - Scope: All entity IDs — transactions, portfolios, positions, orders, strategies, screeners
  - Singleton: `idgen` initialized in `itrader/__init__.py`

## Monitoring & Observability

**Error Tracking:**
- None — no external error tracking service (e.g., Sentry) integrated

**Logs:**
- structlog 24.4.0 — structured logging via `ITraderStructLogger` in `itrader/logger.py`
- Output: Colored console (default) or JSON (`ITRADER_JSON_LOGS=true`)
- Level: Controlled by `ITRADER_LOG_LEVEL` env var (default `INFO`)
- Pattern: All handlers bind a component logger via `get_itrader_logger().bind(component="ClassName")`

**Metrics / Profiling:**
- `SystemConfig.monitoring` has ports for Prometheus metrics (9090) and health check (8080) — **not wired to any actual collector**; config model only, no exporter implemented

**Performance Reporting:**
- plotly 6.8.0 — `itrader/reporting/plots.py` (D-reporting deferred; not on backtest path)
- scipy `linregress` — performance metrics in `itrader/reporting/performance.py`
- sqlalchemy-based reporting engine — `itrader/reporting/engine_logger.py`, `itrader/reporting/statistics.py` (D-sql/reporting deferred; excluded from mypy)

## CI/CD & Deployment

**Hosting:**
- No deployment target configured — pure library/application

**CI Pipeline:**
- None detected — no `.github/workflows/`, `.circleci/`, `.travis.yml`, or similar

**Pre-commit:**
- `Makefile` has `precommit: pre-commit run --all-files --hook-stage manual` target
- No `.pre-commit-config.yaml` detected at repo root

## Environment Configuration

**Required env vars (live path only):**
- `ITRADER_DATABASE_URL` — PostgreSQL DSN; declared as required-no-default `SecretStr` in `itrader/config/settings.py`; backtest path never instantiates `Settings` so this is never required for backtest

**Optional env vars (all paths):**
- `ITRADER_LOG_LEVEL` — defaults to `INFO`
- `ITRADER_JSON_LOGS` — defaults to `false`

**Secrets location:**
- `.env` file at repo root (gitignored); loaded by `Makefile` via `include .env`
- `oanda.cfg` at repo root (gitignored); read directly by `tpqoa.tpqoa()`
- Credentials are NOT injected via pydantic-settings on the active backtest path — `Settings` is only instantiated when a live caller explicitly constructs it

## Webhooks & Callbacks

**Incoming:**
- None — no HTTP webhook endpoints

**Outgoing:**
- None — no outgoing webhook calls

## Exchange Simulation (Internal)

The `SimulatedExchange` in `itrader/execution_handler/exchanges/simulated.py` is an internal component, not an external integration. It supports four named configuration presets — `default` (zero fee/slippage), `realistic` (0.1% fee + linear slippage), `high_fee` (maker/taker 0.8%/1.0%), `low_latency` (0.05% fee) — defined in `itrader/config/exchange.py::get_exchange_preset()`.

---

*Integration audit: 2026-06-07*
