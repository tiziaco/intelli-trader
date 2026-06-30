---
last_mapped_commit: 6b15b25
---
# Codebase Concerns

**Analysis Date:** 2026-06-30

> Scope note: this is a deliberately-disciplined refactor codebase. Many apparent
> "inconsistencies" are documented decisions (cited as `D-NN` / `WR-NN` / `T-NN` /
> `M5-NN` tags in code). This document separates **genuine concerns** (act on these)
> from **intentional documented decisions** (do NOT re-litigate — see the final
> section). When in doubt, grep the cited tag before "fixing" anything.

## Tech Debt

**v1.6 operational SQL stores built+tested but only partially wired into live (the biggest debt):**
- Issue: Milestone v1.6 delivered three durable `Sql<Concern>Storage` + `CachedSql<Concern>Storage` backends (order / portfolio-state / signal), each with integration tests under `tests/integration/storage/`. Only the **order** store is wired into the live composition root. The **signal** store still uses the in-memory backend, and the **portfolio-state** store is not wired at all.
- Files:
  - `itrader/trading_system/live_trading_system.py:113` — `self._signal_store = SignalStorageFactory.create('backtest')` (in-memory; comment admits "captured signals will NOT survive a restart until a persistent backend lands").
  - `itrader/trading_system/live_trading_system.py:123-150` — only `order_storage` routes to the SQL spine (and only when `SYSTEM_DB_URL` is set).
  - `itrader/portfolio_handler/storage/storage_factory.py` — `SqlPortfolioStateStorage` `'live'` arm exists and is tested (`tests/integration/storage/test_sql_portfolio_storage.py`) but `PortfolioStorageFactory` is never called from `live_trading_system.py` (grep confirms no reference).
  - `itrader/strategy_handler/storage/cached_sql_storage.py` — `CachedSqlSignalStorage` exists and is tested but is not wired.
- Impact: Live portfolio account state and captured signals are NOT durable across a restart even when a Postgres URL is configured; only the order mirror persists. The v1.6 "persistence foundation" is a foundation, not a finished integration.
- Fix approach: A "Phase 4" follow-up (already referenced in `live_trading_system.py:139` as "Phase 4 owns the shared operational-backend composition root") that builds ONE shared `SqlBackend` and injects it into all three factories from a single live composition root, replacing the three independent `create('backtest')` / URL-gated calls.

**`SignalStorageFactory.create('backtest')` used as a live fallback by naming:**
- Issue: The live system constructs its signal sink by passing the literal `'backtest'` environment to the signal factory. This works but couples "live has no persistent signal store yet" to the string `'backtest'`, which is semantically wrong for a live run and easy to miss when the SQL arm is finally wired.
- Files: `itrader/trading_system/live_trading_system.py:113`.
- Impact: Low now; a readability/correctness trap when the persistent signal arm lands.
- Fix approach: Route through the same shared-backend live composition root as the order store; drop the `'backtest'` string in the live path.

**Offline ingestion pipeline is a hard `NotImplementedError` stub:**
- Issue: The provider→store ingestion entry point always raises.
- Files: `itrader/price_handler/ingestion.py:45` (`raise NotImplementedError("offline ingestion pipeline — deferred to the persistence milestone (D-sql)")`).
- Impact: No supported path to populate the SQL price store from a provider; data ingestion is manual/external.
- Fix approach: Implement the documented `provider.fetch_ohlcv → store.write_bars` loop behind the existing `PriceProvider` / `PriceStore` seams (the contract is already written in the module docstring).

**Italian-language TODOs in the deferred provider/screener subsystems:**
- Issue: A cluster of `#TODO: da modificare` / `da vedere se serve` / `da testare` / `da spostare in order_handler.compliance` markers — untriaged, non-English, in mypy-deferred code.
- Files: `itrader/price_handler/providers/oanda_provider.py:36,74`; `itrader/price_handler/providers/ccxt_provider.py:57`; `itrader/screeners_handler/screeners/volume_spyke.py:40`; `itrader/screeners_handler/screeners/base.py:29`; `itrader/strategy_handler/my_strategies/scalping/*` (multiple, all "da spostare in order_handler.compliance"); `itrader/strategy_handler/my_strategies/momentum/ATR_Hawkes_Momentum_strategy.py:129`.
- Impact: Hidden, untracked work in subsystems outside the strict-typing gate; the `my_strategies/*` ones reference a `compliance` long-only/short check that should live in `order_handler` but is duplicated across strategies.
- Fix approach: Triage into the backlog; the recurring "da spostare in order_handler.compliance" suggests a single `order_handler` admission/compliance rule that should subsume the per-strategy `long_only` checks. Note `my_strategies/*` is flagged "relocated to a separate repo" in mypy overrides — confirm whether these files are still in-scope at all before investing.

## Known Bugs

**No high-confidence latent bugs surfaced in in-scope (strict-typed, golden-locked) code.** The backtest path is regression-locked by the byte-exact oracle (`tests/integration/test_backtest_oracle.py`) and `mypy --strict` over `itrader/`. Defects, if any, concentrate in the mypy-deferred subsystems below (live trading, screeners, providers), which have little-to-no automated coverage.

## Security Considerations

**Live DB URL handled correctly — no embedded-credential default (good):**
- Risk: A default connection string with embedded credentials would leak secrets and silently materialize a non-durable store.
- Files: `itrader/trading_system/live_trading_system.py:127-150` — `SYSTEM_DB_URL` unset → loud warning + in-memory fallback (WR-10), never a baked-in credential string. URL wrapped in `pydantic.SecretStr`.
- Current mitigation: Adequate. Keep this pattern; do not regress to a default URL.

**SQL access is parameterized end-to-end (good — SEC-01 / T-03-03):**
- Risk: SQL injection via f-string/format SQL.
- Files: `itrader/order_handler/storage/sql_storage.py`, `itrader/portfolio_handler/storage/sql_storage.py`, `itrader/results/sql_storage.py`, `itrader/price_handler/store/sql_store.py` — all use SQLAlchemy Core `Table`/`Column` objects + bound params; grep for f-string SQL found none (the only `format`-adjacent hit is `.isoformat()` on a value, not SQL text).
- Current mitigation: Adequate.
- Recommendations: Preserve the "never f-string SQL" rule (documented as SEC-01) when extending the operational stores.

**Secrets live in `.env` / `oanda.cfg` at repo root:**
- Risk: Credential files present in the working tree; accidental commit risk.
- Files: `.env` (present, loaded by `Makefile` via `include .env`), `oanda.cfg` (referenced by `itrader/price_handler/providers/oanda_provider.py`).
- Current mitigation: `.env` is gitignored in prod (per project docs); contents not inspected here.
- Recommendations: Confirm `.env` and `oanda.cfg` are gitignored; ensure no test fixture or migration writes a credential into `alembic.ini` (the migration test deliberately injects the URL programmatically — `tests/integration/storage/test_migrations.py` — keep that pattern).

## Performance Bottlenecks

**Per-tick `searchsorted` history hotspot — already FIXED, do not regress (PERF-06 / D-10):**
- Problem: The W2 profiling found ~13.2% of wall time in a per-tick `searchsorted` over the full price index in `BacktestBarFeed.window()`.
- Files: `itrader/price_handler/feed/bar_feed.py:307-318,490,563-620`.
- Status: Resolved. Replaced by a per-`(ticker, alias)` monotonic int64-ns forward cursor (`_cursor` / `_cursor_cut`); cold/backward seeks SAFE-REBUILD via `searchsorted`, the hot forward path is a pure cursor advance. This is a known-fragile optimization — the comments (D-10/D-11) warn that a wrong cursor would leak/hide a bar, so the `iloc` slice is kept cursor-only by decision.
- Improvement path: None needed; treat the cursor invariants as load-bearing. Any change here must keep the oracle byte-exact.

**Decimal metrics math converts to `float` at the reporting edge (acceptable):**
- Problem: `metrics_manager.py` casts `Decimal` equity/returns to `float` for ratio math (Sharpe/Sortino/Calmar via scipy/numpy).
- Files: `itrader/portfolio_handler/metrics/metrics_manager.py:370-371,457-468,596`; `itrader/portfolio_handler/validators.py:145`; `itrader/portfolio_handler/portfolio.py:185,638`.
- Cause: Statistical libraries (scipy `linregress`, numpy) operate on float; money policy explicitly allows `float()` at the serialization/reporting edge.
- Improvement path: None required — this is the sanctioned edge. Flagged only so a future reviewer does not mistake it for a money-policy violation. The hot ledger path (cash/position) stays Decimal.

## Fragile Areas

**`CachedSql*Storage` cache-vs-store consistency (live-only, new in v1.6):**
- Files: `itrader/order_handler/storage/cached_sql_storage.py`, `itrader/portfolio_handler/storage/cached_sql_storage.py`, `itrader/strategy_handler/storage/cached_sql_storage.py`.
- Why fragile: Store-first / persist-then-acknowledge ordering, terminal-state eviction gates (`_can_evict`, bracket-parent-resident), and restart rehydration (open-only + parents of live children) are subtle invariants. A bug in eviction or rehydration could serve stale or missing orders from the cache. The design explicitly accepts NO cross-method transaction (bracket atomicity is deferred to "N+4 reconciliation").
- Safe modification: Never mutate the cache before the store commit returns (the whole D-04 topology depends on the cache being rebuildable from the store). Keep the `RLock` around cache-mutation + read-through. Add tests for the rehydration path specifically.
- Test coverage: Integration tests exist (`tests/integration/storage/test_cached_sql_*_storage.py`) but exercise the wrapper in isolation, NOT through a live run (the wrapper is unwired for signals/portfolio — see Tech Debt).

**`MatchingEngine` intrabar trigger / OCO evaluation:**
- Files: `itrader/execution_handler/matching_engine.py` (497 lines), `itrader/execution_handler/exchanges/simulated.py` (789 lines).
- Why fragile: Gap-aware fills, same-bar OCO priority, and stop/limit trigger evaluation against intrabar high/low are correctness-critical and have many edge cases (gaps, same-bar both-sides). This is the source of truth for fills.
- Safe modification: Covered by extensive `tests/e2e/matching/` and golden oracles — run the full e2e + oracle suite on any change. Do not move matching into the order handler (documented anti-pattern).
- Test coverage: Good (e2e matching dirs + oracle).

**Reconcile manager terminal-status fallthrough:**
- Files: `itrader/order_handler/reconcile/reconcile_manager.py:112,257` — an `else: raise NotImplementedError` guards an unmapped terminal `FillStatus`.
- Why fragile: A new `FillStatus` member without a reconcile arm raises at runtime (by design — "fail loud BEFORE should_release is armed so the reservation stays held"). Correct, but means adding a fill status requires touching this file.
- Safe modification: When adding a `FillStatus`, add its reconcile arm here in the same change.

**Large multi-responsibility modules (complexity hotspots):**
- Files (>700 lines): `itrader/strategy_handler/base.py` (946), `itrader/order_handler/admission/admission_manager.py` (940), `itrader/portfolio_handler/portfolio_handler.py` (935), `itrader/portfolio_handler/portfolio.py` (873), `itrader/execution_handler/exchanges/simulated.py` (789), `itrader/price_handler/feed/bar_feed.py` (709).
- Why fragile: High line count concentrates logic; `strategy_handler/base.py` in particular is a 946-line base class. Changes ripple widely.
- Safe modification: These are well-documented with decision tags; lean on the test suite. Not flagged for urgent refactor — flagged so planners scope changes to these files generously.

## Scaling Limits

**Live event loop is a single daemon thread:**
- Current capacity: One background thread drains `global_queue` (`itrader/trading_system/live_trading_system.py`); per-portfolio `threading.RLock` for state.
- Limit: Single-threaded event processing caps live throughput at one event at a time; fine for the current scope (low-frequency strategies) but not a high-frequency design.
- Scaling path: Out of scope for the backtest-correctness milestone; revisit only if live HFT becomes a requirement.

**SQL connection pool fixed at 20:**
- Current capacity: `connection_pool_size: int = 20` (`itrader/config/system.py:43`).
- Limit: Adequate for a single-process live system; would need tuning for multi-process / web-app fan-out (note the FastAPI-wrapping plan in user memory — Alembic chain already framework-owned).
- Scaling path: Expose pool size via `SqlSettings` if the planned FastAPI layer introduces concurrent request workers.

## Dependencies at Risk

**`pandas-ta 0.4.71b0` — pinned beta:**
- Risk: A beta-versioned pin used in strategy filters and SLTP models; betas can be yanked or change API.
- Impact: Strategy indicators (`itrader/strategy_handler/`) could break on a forced upgrade.
- Migration plan: Vendor or pin-freeze; evaluate the stable `ta` library or a maintained fork if it destabilizes.

**`psycopg2-binary` for production Postgres:**
- Risk: `-binary` is discouraged for production deployments (it bundles its own libpq); fine for dev.
- Impact: Potential binary-compat issues in some deploy targets.
- Migration plan: Switch to `psycopg2` (source) or `psycopg` (v3) for the production/FastAPI deploy.

**`nautilus-trader 1.227.0` — heavy non-gating oracle:**
- Risk: A large, fast-moving dependency pulled in only as a non-gating reconciliation oracle.
- Impact: Dependency-resolution weight; not on the run path.
- Migration plan: Keep as a dev/test-only extra; ensure it is not imported by `itrader/` runtime code.

## Missing Critical Features

**Live trading is "minimal conformance," not a real live system (D-live deferred):**
- Problem: `LiveTradingSystem` wires the same component graph but uses the offline `CsvPriceStore` + `BacktestBarFeed` ("a real live feed is owned by D-live"), and the live universe/feed are not implemented. Event-type handling in the processing loop is a TODO.
- Files: `itrader/trading_system/live_trading_system.py:100-116,281` (`# TODO: Add more specific event type handling ... 'ORDER_FILLED' 'ORDER_CREATED'`).
- Blocks: Any actual live deployment. The live path imports and constructs but does not stream real market data.

**`PostgreSQLOrderStorage` was a stub — now RETIRED (not a concern):**
- Status: The old `NotImplementedError` placeholder was deleted and replaced by the real `SqlOrderStorage` on the shared SQL spine (D-05). There is deliberately NO `'postgresql'` factory arm (D-06). The earlier "may be a NotImplementedError placeholder" suspicion is resolved — it no longer exists.
- Files: `itrader/order_handler/storage/sql_storage.py` (the real implementation), `itrader/order_handler/storage/storage_factory.py` (no `'postgresql'` arm — `'live'` only).

## Test Coverage Gaps

**Live trading subsystem — essentially untested:**
- What's not tested: `LiveTradingSystem` lifecycle (start/stop/status), the threaded processing loop, the publish-and-continue error policy, `TradingInterface` order creation/validation. No dedicated test file exists.
- Files: `itrader/trading_system/live_trading_system.py` (611 lines), `itrader/trading_system/trading_interface.py`.
- Risk: Live lifecycle and error-handling regressions go unnoticed; the SQL-store live wiring (and its gaps) has no end-to-end test.
- Priority: Medium (live is deferred, but the v1.6 persistence wiring it touches is shipped).

**Screeners subsystem — no behavioral coverage:**
- What's not tested: Concrete screeners (`volume_spyke.py`, etc.) and screening behavior; only event-dispatch wiring touches `ScreenersHandler`.
- Files: `itrader/screeners_handler/` (mypy-deferred via `screeners_handler.*` override).
- Risk: Low while screening is a deferred subsystem; will need coverage before it is activated.
- Priority: Low.

**Price providers (CCXT / OANDA / Binance stream) — no tests:**
- What's not tested: `ccxt_provider.py`, `oanda_provider.py`, `binance_stream.py`, `exchange_base.py` (all mypy `ignore_errors`).
- Files: `itrader/price_handler/providers/`.
- Risk: Provider integrations are unverified and carry untriaged TODOs; not on the backtest run path, so backtest correctness is unaffected.
- Priority: Low now; High before the ingestion pipeline (above) is implemented against them.

**Cached SQL stores tested in isolation, not through a live run:**
- What's not tested: The `CachedSql*Storage` wrappers exercised end-to-end inside a running `LiveTradingSystem` (because two of three are unwired). Restart-rehydration is the riskiest untested-at-integration path.
- Files: `tests/integration/storage/test_cached_sql_*_storage.py` cover the wrappers directly; no test drives them via `live_trading_system.py`.
- Risk: Wiring bugs (wrong env string, missing factory call) are invisible to the suite.
- Priority: Medium — couple this with the Phase-4 live composition-root work.

**Postgres-backed storage tests skip silently when Docker is absent:**
- What's not tested (on a Dockerless box): The Postgres arm of every cross-backend storage test `pytest.skip`s when no Docker daemon is present (D-11); only the in-process SQLite arm runs.
- Files: `tests/integration/storage/conftest.py` (testcontainers `pg_engine`, `pg_backend`).
- Risk: Postgres-specific behavior (Numeric exactness, FK ordering, naming convention) is unverified on a developer machine without Docker — green local run ≠ green Postgres. CI must run Docker to exercise the PG arm.
- Priority: Medium — ensure CI provisions Docker so the PG arm is not perpetually skipped.

---

## Intentional Documented Decisions (NOT concerns — do not "fix")

These are surfaced so they are not mistaken for debt. Each is anchored to a decision tag in code; grep the tag before touching.

- **Dual-layer order-validator overlap** (`itrader/order_handler/order_validator.py` + `itrader/execution_handler/exchanges/simulated.py`): defense-in-depth, justified-by-decision (D-03a). The live `TradingInterface`/`OrderEvent` path bypasses the domain validator, so the exchange-side validation is load-bearing. **Do NOT remove.**
- **Broad `except Exception` run-mode policy** (33 occurrences): backtest is **fail-fast** (`EventHandler._on_handler_error` re-raises; `backtest_trading_system.py:382` re-raises under `_strict_persist`); live is **publish-and-continue** (`live_trading_system.py` emits `ErrorEvent` and keeps draining). This asymmetry is intentional, not an inconsistency. `ExecutionHandler.on_order`/`on_market_data` swallow per-exchange exceptions by design (queue-stall prevention).
- **Config-domain `str, Enum` placement**: the seven config enums (`FeeModelType`, `SlippageModelType`, `PortfolioType`, …) live in `config/` not `core/enums/` by design — relocating would invert the core→config dependency.
- **Tab/space indentation split**: handler modules use tabs; `config/`, `core/`, `price_handler/feed/`, the events package, and the v1.6 `storage/` modules use 4 spaces. Match the file; a mixed-indent diff raises `TabError`.
- **`float()` at the reporting/serialization edge**: sanctioned by the money policy; the ledger path stays Decimal.
- **SQL stores quarantined from package `__init__` re-export** (GATE-01): keeps the backtest import path SQLAlchemy-free. `Sql*`/`CachedSql*` are imported lazily inside factory `'live'` arms and under `TYPE_CHECKING`. Do not add them to any `__init__.py` barrel.
- **`create_all()` vs Alembic split** (D-14): the ephemeral research/results store uses `MetaData.create_all()`; the durable operational store evolves under the Alembic chain (`itrader/storage/migrations/`). Proven by `tests/integration/storage/test_migrations.py`.
- **Unrouted-event `NotImplementedError`** (`full_event_handler.py:117`, KB1): silent event drops are a tampering risk, so an unrouted `EventType` raises by design.

---

*Concerns audit: 2026-06-30*
