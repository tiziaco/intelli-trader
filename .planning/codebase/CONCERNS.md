# Codebase Concerns

**Analysis Date:** 2026-06-12
**Codebase state:** HEAD `68fff46` — v1.2 Consolidation shipped. 39/46 v1.2-CLEANUP-REVIEW items fixed; W3-07 missed; 10 findings deferred to 999.5/v-next. Golden master locked at 134 trades / `final_equity 46189.87730727451`.

---

## Tech Debt

**PostgreSQL order storage is a complete stub (FL-05):**
- Issue: `PostgreSQLOrderStorage.__init__` raises `NotImplementedError` immediately; every method raises the same. Live trading falls back to in-memory order storage silently (with a warning). Orders do not survive a restart in live mode.
- Files: `itrader/order_handler/storage/postgresql_storage.py` (all 58 lines are stubs)
- Impact: Live order persistence is completely absent. `LiveTradingSystem` catches the `NotImplementedError` at startup and downgrades to in-memory with a warning — the fallback is safe but silent in terms of data loss on restart.
- Fix approach: Implement using `sqlalchemy` (already a dependency). Wire from `OrderStorageFactory.create('live', db_url)`. Owned by backlog 999.2 (N+2 — Persistence & Performance).

**`Order.action` and `_PendingBracket.action` typed as `str` instead of `Side` (W2-39 / 999.5-a):**
- Issue: `Order.action: str` at `itrader/order_handler/order.py:49`; `_PendingBracket.action: str` at `itrader/order_handler/brackets/bracket_book.py:40`. All events carry `action: Side` but the entity stores a raw string. The comment "stores str until M4" never completed the follow-through.
- Files: `itrader/order_handler/order.py:49`, `itrader/order_handler/brackets/bracket_book.py:40`, `itrader/order_handler/brackets/levels.py:27`
- Impact: Loss of type safety on the bracket/reconcile path; a typo in an action string silently misbehaves instead of failing at the type boundary. Mypy cannot catch mismatches.
- Fix approach: Retype to `Side` throughout. FRAGILE — touches the reconcile/admission path; requires golden-master re-run. Owned by 999.5-(a) (Signal contract completion).

**`create_order` is a second, unvalidated signal→order path (W4-09 / 999.5-d):**
- Issue: `OrderHandler.create_order` at `itrader/order_handler/order_handler.py:192` bypasses the `process_signal` admission gates and size-enforcement. It was kept for the D-live interface but is publicly callable today.
- Files: `itrader/order_handler/order_handler.py:192`, `itrader/order_handler/admission/admission_manager.py:277`
- Impact: A caller using `create_order` directly can produce an `OrderEvent` that never ran the admission gates (direction/max-positions/increase checks, cash reservation). On the backtest path this path is not used by any strategy; the risk is live mode.
- Fix approach: Either gate with the same admission pipeline or restrict visibility. Decision needed (owner-gated per ROADMAP 999.5-d).

**`ExecutionHandler._resolve_rng_seed` constructs a second `SystemConfig.default()` instead of injection (W4-06):**
- Issue: `ExecutionHandler._resolve_rng_seed` calls `SystemConfig.default()` directly at handler construction rather than receiving the seed as a constructor argument.
- Files: `itrader/execution_handler/execution_handler.py:54-62`
- Impact: A second config parse at every `ExecutionHandler` construction; config cannot be overridden in tests without patching the class method. Low severity on the backtest path but inconsistent with the injection model used everywhere else.
- Fix approach: Pass `rng_seed` (or the full `SystemConfig`) into `ExecutionHandler.__init__` from the composition root. Owned by 999.5-(b) (composition/config interface).

**`TIMEZONE` constant is a module-level parse of `Settings.model_fields["timezone"].default` (stale-init risk):**
- Issue: `itrader/config/__init__.py:62` derives `TIMEZONE` at import time by reading the Pydantic `FieldInfo.default` rather than constructing a `Settings()` instance. An env-var override of `ITRADER_TIMEZONE` at runtime would NOT be reflected in this constant.
- Files: `itrader/config/__init__.py:62`; callers: `itrader/price_handler/store/csv_store.py`, `itrader/outils/time_parser.py`, `itrader/price_handler/providers/ccxt_provider.py`
- Impact: In backtest mode the default is always used — the golden run is unaffected. In live mode or when the env var is set, the timezone used in CSVs/feeds would silently diverge from `Settings().timezone`.
- Fix approach: Pass `timezone` as a constructor argument from the composition root rather than relying on the module-level constant.

**`OrderConfig` does not exist; `OrderManager` takes loose constructor parameters (SYN-05 / 999.5-b):**
- Issue: Every other domain has a Pydantic config model (`ExchangeConfig`, `PortfolioConfig`, `SystemConfig`). `OrderManager` receives `market_execution` as a stringly-typed parameter, with no config object.
- Files: `itrader/order_handler/order_manager.py:47-50`; `itrader/config/` (no `order.py`)
- Impact: No validation, no YAML override, no runtime config-update surface for order behavior. Inconsistent with the rest of the config system.
- Fix approach: Create `config/order.py::OrderConfig` and thread it through `OrderHandler`/`OrderManager`. Owned by 999.5-(b).

**`get_active_portfolios()` is a list comprehension per tick (W1-13 descoped):**
- Issue: `PortfolioHandler.get_active_portfolios()` at `itrader/portfolio_handler/portfolio_handler.py:207-209` rebuilds the active-portfolio list on every call. It is called twice per tick from `backtest_trading_system.py:220,285` and once per tick from `live_trading_system.py:314`.
- Files: `itrader/portfolio_handler/portfolio_handler.py:207-209`, `itrader/trading_system/backtest_trading_system.py:220,285`
- Impact: O(n) per tick per call. Negligible for single-portfolio runs; scales linearly with portfolio count in multi-portfolio backtests. Descoped from v1.2 (D-10 decision); low priority until multi-portfolio workloads become common.
- Fix approach: Cache in a `_active_portfolios: list[Portfolio]` maintained on `add_portfolio`/`remove_portfolio`. Owned by 999.5-(b) or standalone.

**`double get_position()` call in admission→sizing (W1-11 / 999.5-a):**
- Issue: `AdmissionManager` calls `portfolio_handler.get_position()` separately in `_check_increase_gate` (`admission_manager.py:404`) and in the sizing resolver (`admission_manager.py:484,583`). The snapshot is fetched from the read-model twice for the same tick.
- Files: `itrader/order_handler/admission/admission_manager.py:404,484,583`
- Impact: Two read-model calls per entry signal where position exists. Threading a snapshot through is safe but touches the fragile admission sequence. Owned by 999.5-(a).

**`pytz` is used in several modules despite stdlib `zoneinfo` being available (Python 3.9+):**
- Issue: `pytz` imported in `itrader/screeners_handler/screeners_handler.py:3`, `itrader/outils/time_parser.py:2`, `itrader/price_handler/providers/ccxt_provider.py:2`, `itrader/price_handler/providers/oanda_provider.py:2`. `pytz` uses a non-standard timezone folding model that can interact poorly with `datetime.replace` on DST boundaries.
- Files: All four files above
- Impact: Mostly cosmetic on crypto (UTC markets, no DST ambiguity); but the `time_parser.py` usage is on the active path. No known bug, but `zoneinfo` is the modern replacement.
- Fix approach: Replace `pytz.timezone(tz).localize(dt)` with `dt.replace(tzinfo=ZoneInfo(tz))`. Low priority.

---

## Known Bugs

**`SqlHandler.delete_all_tables` uses unparameterized DDL with string formatting — SQL injection (FL-06):**
- Symptoms: `DROP TABLE IF EXISTS <symbol>` is constructed via `f'DROP TABLE IF EXISTS {"%s"};' % sym` at `sql_store.py:35`. The symbol comes from `get_symbols_SQL()` which reads table names from the database, but the format is still unsafe.
- Files: `itrader/price_handler/store/sql_store.py:35`
- Trigger: Any call to `delete_all_tables()` with a symbol name containing SQL metacharacters, or if the DB is compromised and returns a malicious table name.
- Workaround: `SqlHandler` is quarantined — not imported at package level (`price_handler/store/__init__.py` documents this). Not on the backtest run path.

**`SqlHandler.init_engine` has hardcoded credentials:**
- Symptoms: `create_engine('postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices')` at `sql_store.py:17`.
- Files: `itrader/price_handler/store/sql_store.py:17`
- Trigger: Any call that constructs `SqlHandler`.
- Workaround: Module is quarantined and covered by `ignore_errors = true` in mypy. Fix: read from `Settings` / environment variable.

**`Order.expire_order()` exists but is never called on the backtest or live path:**
- Symptoms: Resting stop/limit orders that never fill remain in `PENDING` status at run end. The `EXPIRED` status and `VALID_ORDER_TRANSITIONS` transition are defined in `core/enums/order.py:72,83`. `expire_order()` at `order_handler/order.py:425` is never invoked from the engine.
- Files: `itrader/order_handler/order.py:425`; `itrader/core/enums/order.py:72,83`; `itrader/trading_system/backtest_trading_system.py` (no run-end sweep)
- Trigger: Any backtest that ends with resting orders.
- Workaround: None currently. The equity curve is unaffected (positions are marked-to-market from the bar feed), but the order mirror is inaccurate at run end. Owned by 999.5-(d).

**`PortfolioValidator.validate_transaction_data` accepts `float` parameters — bypasses Decimal policy:**
- Symptoms: `itrader/portfolio_handler/validators.py:20-53` accepts `price: float`, `quantity: float`, `commission: float` and uses `isinstance(price, (int, float))` as the type guard. This class is not on the main fill path but could silently accept float money.
- Files: `itrader/portfolio_handler/validators.py:20-53`
- Trigger: Any caller that uses `PortfolioValidator.validate_transaction_data`.
- Workaround: The main fill path (`transact_shares` → `process_transaction`) does not call this validator directly. Low risk in practice.

**`itrader/portfolio_handler/portfolio.py:26` defines `TOLERANCE = 1e-3` as a float constant:**
- Symptoms: `TOLERANCE = 1e-3` is defined at module level but not used in any Decimal comparison in that file (position quantity guard uses `Decimal("0.000001")` correctly). Dead float constant at the money module boundary creates confusion.
- Files: `itrader/portfolio_handler/portfolio.py:26`
- Trigger: Any reader who assumes `TOLERANCE` drives a live comparison.
- Workaround: N/A — it is simply dead code that could mislead.

---

## Security Considerations

**Hardcoded PostgreSQL credentials in `SqlHandler` (FL-06):**
- Risk: Username `tizianoiacovelli` and password `1234` are in plaintext source code at `sql_store.py:17`. If the file is committed to a public repo or leaked, credentials are exposed.
- Files: `itrader/price_handler/store/sql_store.py:17`
- Current mitigation: The module is quarantined (not imported at package level); `ignore_errors = true` in mypy. Not on any active execution path.
- Recommendations: Read from `Settings` (which supports `ITRADER_` env-var prefix via `pydantic-settings`); remove hardcoded credentials entirely.

**SQL table-name injection in `SqlHandler.delete_all_tables` and `read_prices`:**
- Risk: Symbol name is interpolated directly into DDL/DML. `delete_all_tables` uses `%` string formatting into a `text()` call; `read_prices` passes the raw `symbol` as the table name to `pd.read_sql`.
- Files: `itrader/price_handler/store/sql_store.py:35,60-70`
- Current mitigation: Module is quarantined; not reachable from the backtest path.
- Recommendations: Use SQLAlchemy `Table`/`quoted_name` to safely construct DDL; parameterize symbol lookups.

**`LiveTradingSystem` falls back to in-memory order storage when `SYSTEM_DB_URL` is unset:**
- Risk: Silent data loss — orders are not persisted and are lost on restart. The warning is logged but not escalated to an error or startup failure.
- Files: `itrader/trading_system/live_trading_system.py:121-135`
- Current mitigation: Warning log at `WARNING` level.
- Recommendations: Make the fallback opt-in via a config flag (e.g. `allow_memory_fallback=False` by default); fail loudly in production.

---

## Performance Bottlenecks

**`SMAMACDStrategy.generate_signal` recomputes full-window SMA + MACD from scratch on every tick (W1-05 / 999.5-c):**
- Problem: Both SMA slices and the MACD indicator are computed over the full bar window on every bar. The W1-12 MACD-inside-guard reorder (shipped in v1.2 Phase 3) reduced wasted MACD calls, but SMA is still computed unconditionally. At 100-bar windows over a 2018–2026 daily dataset this is dominated by pandas rolling — not a crisis, but scales poorly.
- Files: `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:78-93`
- Cause: Stateless recompute-everything design inherited from the original strategy. The IND-01 indicator framework (999.5-c) will add an opt-in incremental state layer; the stateless path stays as the byte-exact baseline.
- Improvement path: Owned by 999.5-(c). Short-term: no change needed (single-strategy golden run is fast). Long-term: declared-indicator framework with incremental state.

**Data-download providers have no retry, timeout, or rate-limit backoff (FL-10):**
- Problem: `CcxtProvider.download_data` at `itrader/price_handler/providers/ccxt_provider.py` catches a broad `Exception` and re-raises immediately (`except Exception as e: raise`). Any transient network failure aborts the download with no retry.
- Files: `itrader/price_handler/providers/ccxt_provider.py:35`, `itrader/price_handler/providers/oanda_provider.py`
- Cause: No retry/backoff wrapper around the ccxt/tpqoa calls.
- Improvement path: Add `tenacity` or a simple exponential-backoff loop around the exchange fetch. Owned by backlog 999.4 (D-live).

---

## Fragile Areas

**`test_position_manager.py` asserts through `pm._storage` private internals (W3-07 — MISSED in v1.2):**
- Files: `tests/unit/portfolio/test_position_manager.py:62,63,79,80,118,135,136,148,149,354,361,362,393,426` (~14 sites)
- Why fragile: Tests reach into `pm._storage` directly instead of using `get_all_positions()` / `get_closed_positions()`. Any rename or backend swap of `_storage` breaks these tests without a corresponding contract change. This was the one item in the v1.2 cleanup review that was planned (NAME-04, Phase 5) but not completed.
- Safe modification: Replace `pm._storage.get_positions()` with `pm.get_all_positions()` and `pm._storage.get_closed_positions()` with `pm.get_closed_positions()`. SAFE — no golden-master re-run needed.
- Test coverage: These tests are themselves the coverage; fixing them is a pure refactor.

**Broad `except Exception` in domain logic — 32 sites (FL-12):**
- Files: `itrader/order_handler/admission/admission_manager.py:247,258,303,652`, `itrader/order_handler/reconcile/reconcile_manager.py:194,218`, `itrader/order_handler/lifecycle/lifecycle_manager.py:141,215`, `itrader/order_handler/brackets/bracket_manager.py:209`, `itrader/portfolio_handler/portfolio_handler.py:163,203,341,368,467,480,491`, `itrader/execution_handler/exchanges/simulated.py:154,315`, `itrader/events_handler/full_event_handler.py:126`, `itrader/trading_system/live_trading_system.py:234,271,328,367,503`
- Why fragile: Broad catches swallow unexpected programming errors (AttributeError, TypeError) silently. The event loop must not stall (documented in CONVENTIONS.md as the intentional run-mode policy), but inside domain managers the intent is to catch domain exceptions — a programming error like a missing attribute is indistinguishable from a handled domain failure.
- Safe modification: Narrow to typed domain exceptions (`ITraderError` subclasses) as each handler is touched. Awareness-only; by-design at the event-loop boundary per CLAUDE.md.

**Screeners subsystem is wired but untested and deferred (FL-09):**
- Files: `itrader/screeners_handler/screeners_handler.py`, `itrader/screeners_handler/screeners/volume_spyke.py:40`, `itrader/screeners_handler/screeners/base.py:29`
- Why fragile: `ScreenersHandler` is wired into both `BacktestTradingSystem` and `LiveTradingSystem` and registered in `EventHandler._routes` for the TIME event — but no screeners are ever added in any test or golden run. The `volume_spyke` screener has a confirmed bug (TODO: `sma` does not accept `window` as an argument). The `base.py` `to_timedelta` call is marked untested.
- Safe modification: Do not add screeners until the subsystem is hardened. Adding any screener to a live run risks silent failures swallowed by the broad handler catches.
- Test coverage: Zero screener unit tests. Integration test `test_dispatch_registry.py` covers only the empty SCREENER route.

**Binance WebSocket streamer has an unbounded `completed_bars` accumulation bug (FL-11):**
- Files: `itrader/price_handler/providers/binance_stream.py:175-176`
- Why fragile: `self.completed_bars = []` is reset to a new empty list and then `.append(msg['s'])` is called — effectively only ever holding one element per `_process_bar` call. While this reset actually prevents unbounded growth (the list is always length 1), the `prices[sym]` DataFrame is sliced to `tail(max_prices_length)` but the `completed_bars` reference pattern is confusing and not tested. The streamer is also completely excluded from mypy (`ignore_errors = true`).
- Safe modification: Owned by backlog 999.4 (D-live). Do not use `BinanceStream` in production without a review of the full streaming path.

**`LiveTradingSystem` uses `BacktestBarFeed` and `CsvPriceStore` as a stub (D-live gap):**
- Files: `itrader/trading_system/live_trading_system.py:106-107`
- Why fragile: The live system wires `CsvPriceStore()` (with no CSV path — it constructs but reads no data) and `BacktestBarFeed` as a shim. Calling `feed.bind()` in `_initialize_live_session` will fail silently because the store has no bars. Any live strategy that requests bar data will receive an empty frame or raise.
- Safe modification: Only safe to use `LiveTradingSystem` with strategies that do not call `feed.generate_bar_event`. A real live feed is owned by backlog 999.4 (D-live).

---

## Scaling Limits

**In-memory order storage — backtest only:**
- Current capacity: All orders for all portfolios held in a Python dict. No limit enforced, but memory grows linearly with trade count across the full run.
- Limit: Memory-only; no disk overflow. Fine for a single multi-year backtest (134 trades for SMA_MACD). Would need measurement for high-frequency or universe-wide runs.
- Scaling path: `PostgreSQLOrderStorage` once implemented (999.2).

**In-memory portfolio state storage — per-portfolio snapshot list:**
- Current capacity: `metrics_manager` stores up to `max_snapshots=10000` equity snapshots per portfolio (configurable); the trim guard fires on every tick now that W1-15 was fixed with a `snapshot_count()` accessor (shipped v1.2 Phase 3).
- Limit: 10000 daily bars ≈ 27 years of daily data. The golden dataset (2018–2026, ~2920 bars) is safely within this limit.
- Scaling path: Persist snapshots to PostgreSQL (999.2).

---

## Dependencies at Risk

**`pandas-ta 0.4.71b0` is a beta pin (FL-14):**
- Risk: The package version pinned in `pyproject.toml:18` is a pre-release beta (`0.4.71b0`). Beta packages may have breaking API changes in patch releases or be abandoned. Used by `my_strategies/` filters and the screener's `volume_spyke` screener.
- Impact: Not on the reference backtest path (`SMA_MACD` uses `ta`, not `pandas-ta`). Risk is isolated to `my_strategies/` and the deferred screeners subsystem.
- Migration plan: Pin to a stable release if one ships; or vendor the required indicator functions. Low urgency while `my_strategies/` is excluded from scope.

**`pandas-ta` is also excluded from mypy (`ignore_missing_imports = true`):**
- Risk: API changes in `pandas-ta` are invisible to the type checker.
- Files: `pyproject.toml:120-123`

---

## Missing Critical Features

**Live price feed — no real streaming bar source:**
- Problem: `LiveTradingSystem` uses `CsvPriceStore` and `BacktestBarFeed` as a stub. There is no wired path from `BinanceStream` or `CcxtProvider` to the event queue's BAR route.
- Blocks: Any live trading deployment.

**OANDA provider is unfinished with Italian-language TODOs (FL-07):**
- Problem: `itrader/price_handler/providers/oanda_provider.py:36` (`#TODO: da modificare`) and `:74` (`# TODO: da vedere se serve`) indicate incomplete translation/porting from an earlier Italian codebase. The `load_markets()` call is tagged as needing rework.
- Files: `itrader/price_handler/providers/oanda_provider.py:36,74`
- Blocks: OANDA live data ingestion.

**Deferred mypy coverage — live system, SQL store, providers, screeners:**
- Problem: `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`, `itrader/price_handler/store/sql_store.py`, all provider modules, `itrader/screeners_handler.*` carry `ignore_errors = true` in `pyproject.toml:87-100`. Type errors in these modules are completely invisible to the gate.
- Files: `pyproject.toml:86-100`
- Blocks: mypy cannot catch regressions in the live path.

**`stale pyproject.toml` mypy override for the deleted `screener_event_handler.py`:**
- Problem: `pyproject.toml:96` lists `itrader.events_handler.screener_event_handler` as an `ignore_errors` module. The file no longer exists in the tree (deleted in a prior cleanup). The override is a no-op but documents a latent `AttributeError` risk if the module is ever recreated without proper initialization.
- Files: `pyproject.toml:96`
- Fix: Remove the stale override entry.

---

## Test Coverage Gaps

**`LiveTradingSystem` and `TradingInterface` have zero test coverage (FL-13):**
- What's not tested: All threading, start/stop/status lifecycle, `_publish_and_continue` error policy, `_initialize_live_session`, `_event_processing_loop`, `TradingInterface` order creation and validation.
- Files: `itrader/trading_system/live_trading_system.py` (550 lines, 0 tests), `itrader/trading_system/trading_interface.py` (220 lines, 0 tests)
- Risk: Any regression in the live system is undetectable until a live run.
- Priority: High (live path; the most critical surface without coverage).

**Screeners subsystem has zero unit tests:**
- What's not tested: `ScreenersHandler.screen_markets`, `ScreenersHandler.init_screeners`, all concrete screeners under `screeners_handler/screeners/`.
- Files: `itrader/screeners_handler/` (all files)
- Risk: The subsystem is wired into the engine and will silently fail or misbehave when a screener is added.
- Priority: Medium — deferred to 999.4 (D-screener).

**`my_strategies/` has no test coverage and is excluded from mypy:**
- What's not tested: `ATR_Hawkes_Momentum_strategy`, `RSI_scalping_strategy`, `VWAP_BB_RSI_scalping_strategy`, `Stoch_RSI_Keltner_strategy`, and custom indicators in `my_strategies/custom_indicators/`.
- Files: `itrader/strategy_handler/my_strategies/` (all files)
- Risk: Strategies that carry compliance TODOs (`long_only` guard not moved to `order_handler.compliance` — 5 files) will silently accept short signals that the order handler may or may not reject.
- Priority: Low — `my_strategies/` is out of scope per ROADMAP; targeted for relocation to a separate repo.

**`test_position_manager.py` uses private `pm._storage` instead of public API (W3-07 MISSED):**
- What's not tested: The PUBLIC `get_all_positions()` / `get_closed_positions()` query path (only the internal storage is asserted).
- Files: `tests/unit/portfolio/test_position_manager.py:62,63,79,80,118,135,136,148,149,354,361,362,393,426`
- Risk: A backend swap or rename of `_storage` breaks the tests without signaling a behavioral contract change. Low immediate risk.
- Priority: Medium — SAFE fix (rewrite assertions to public API; no golden-master re-run needed).

---

*Concerns audit: 2026-06-12 — HEAD 68fff46, v1.2 Consolidation shipped*
