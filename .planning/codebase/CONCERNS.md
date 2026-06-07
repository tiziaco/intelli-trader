# Codebase Concerns

**Analysis Date:** 2026-06-07

---

## Tech Debt

**Wall-Clock Leaks in Domain Code (D-09/D-10 incomplete):**
- Issue: `BacktestClock` is constructed and advanced per tick in the run loop but has zero domain consumers. `datetime.now()` is called directly in `MetricsManager.record_snapshot()`, `MetricsManager._get_latest_metrics()`, `MetricsManager._cache_timestamp`, `PositionManager.calculate_holding_period()`, and `SimulatedExchange` lifecycle tracking. The clock seam exists but is not wired.
- Files: `itrader/portfolio_handler/metrics/metrics_manager.py:138,224,252,467`, `itrader/portfolio_handler/position/position_manager.py:337`, `itrader/execution_handler/exchanges/simulated.py:94,117,304,349,377`
- Impact: Backtest result determinism is preserved only because the result-bearing paths receive `ping_event.time` explicitly. Any future consumer of `datetime.now()` in portfolio metrics will produce non-reproducible outputs.
- Fix approach: Pass `clock.now()` through the `record_snapshot()` call chain from `portfolio.record_metrics(time_event.time)`; replace the `datetime.now()` fallback in `MetricsManager.record_snapshot()`.

**Float Leaks at Portfolio Property Boundary:**
- Issue: `Portfolio.total_market_value`, `Portfolio.total_equity`, `Portfolio.total_unrealised_pnl`, `Portfolio.total_realised_pnl`, and `Portfolio.total_pnl` all return `float`. `MetricsManager` repeatedly coerces `Decimal` snapshots to `float` in `_get_latest_metrics()`, `_calculate_max_drawdown()`, and `_calculate_performance_metrics()`. The order validator performs all cash sufficiency checks in `float` domain, documented as "float-domain until M4".
- Files: `itrader/portfolio_handler/portfolio.py:223,230,240,245,250`, `itrader/portfolio_handler/metrics/metrics_manager.py:195,200,279,326,327,501,502`, `itrader/order_handler/order_validator.py:200,211,314,336,438,439,478`
- Impact: float arithmetic on large BTC prices accumulates rounding error across thousands of backtest bars. Intentional for M4 milestone but creates a correctness gap in production validator cash checks (insufficient-funds logic is float-based while ledger is Decimal).
- Fix approach: Replace `Portfolio` property return types with `Decimal`; update `MetricsManager` aggregate helpers; replace `float(order.price)` / `float(order.quantity)` in `EnhancedOrderValidator` with native `Decimal` comparisons.

**`TradingInterface` Bypasses Decimal Domain:**
- Issue: `TradingInterface.create_market_order()` and `create_limit_order()` accept `quantity: float` and `price: float` parameters, convert them with `float(quantity)` / `float(price)`, and construct `OrderEvent` with `price=0.0` (a float literal) for market orders.
- Files: `itrader/trading_system/trading_interface.py:53,79,95,108,148,180,189`
- Impact: Live orders entering through the API surface re-introduce float money that the `Order.__post_init__` will coerce via `to_money(Decimal(str(float)))` — introducing the known binary-float-repr artifact the comment in `core/money.py:17` explicitly forbids.
- Fix approach: Change interface signatures to accept `str | Decimal`, construct `to_money()` at the boundary before constructing `OrderEvent`.

**`Order.created_at` / `Order.updated_at` Type-Ignored `None` Defaults:**
- Issue: Two `Order` dataclass fields are annotated `datetime` but defaulted to `None` with `# type: ignore[assignment]`.
- Files: `itrader/order_handler/order.py:63-64`
- Impact: Any code that uses `order.created_at` without a `None` guard will fail at runtime; mypy is silenced here, so static analysis will not catch callers that assume the type is always `datetime`.
- Fix approach: Change annotation to `Optional[datetime]`, remove the `type: ignore` suppression.

**`statistics.py` / `_to_sql` Uses Deprecated SQLAlchemy `engine.execute()`:**
- Issue: `StatisticsReporting._to_sql()` calls `self.engine.execute()`, which was removed in SQLAlchemy 2.0. The `statistics.py` module also lacks `self.engine` (there is no constructor assignment for it), so `_to_sql` would raise `AttributeError` before reaching the deprecated call.
- Files: `itrader/reporting/statistics.py:245,258`
- Impact: The `_to_sql` path is completely broken and will raise at runtime if called.
- Fix approach: Delete or rewrite using `with engine.begin() as conn: conn.execute(...)` (SQLAlchemy 2.0 style).

**Hardcoded Credentials in `SqlHandler`:**
- Issue: `SqlHandler.init_engine()` contains a hardcoded PostgreSQL connection string including username and password `tizianoiacovelli:1234`.
- Files: `itrader/price_handler/store/sql_store.py:17`
- Impact: This is a security risk if the file is ever shared or published. The username/password are developer-specific and will fail on any other machine.
- Fix approach: Read from an environment variable or the config system (`get_data_config().db_url`); remove credential from source.

**`order_manager.py` Broad `except Exception` Swallowing:**
- Issue: `OrderManager` uses `except Exception as e` in seven locations (lines 185, 319, 330, 375, 543, 703, 769) with logging and either re-raise or silent continue. The bare `except Exception` at line 330 swallows without re-raise.
- Files: `itrader/order_handler/order_manager.py:185,319,330,375,543,703,769`
- Impact: Silent swallowing at line 330 means OCO/bracket child operations can fail invisibly, leaving the order book in an inconsistent half-cancelled state without surfacing to the queue.
- Fix approach: Replace with typed exception handling; bare `except Exception` blocks that continue silently must log with `exc_info=True` and emit a failure event or re-raise.

---

## Known Bugs

**`StatisticsReporting._prepare_data` References Non-Existent `portfolio.metrics`:**
- Symptoms: Calling `reporting.print_summary()`, `reporting.plot_charts()`, or `reporting.plot_signals()` raises `AttributeError: 'Portfolio' object has no attribute 'metrics'`. `portfolio.metrics` was removed when `MetricsManager` was refactored; the method now delegates to `portfolio.metrics_manager.get_current_metrics()`.
- Files: `itrader/reporting/statistics.py:72`, `itrader/portfolio_handler/portfolio.py`
- Trigger: `TradingSystem.run(print_summary=True)` or any direct call to `reporting.print_summary()`.
- Workaround: Always call `TradingSystem.run(print_summary=False)`. The production path (`scripts/run_backtest.py`) uses `print_summary=False`.

**`LiveTradingSystem.get_statistics()` Calls `calculate_statistics()` Without Required Arguments:**
- Symptoms: `live_system.get_statistics()` will raise `TypeError: calculate_statistics() missing 2 required positional arguments: 'positions' and 'equity_metrics'`.
- Files: `itrader/trading_system/live_trading_system.py:452`, `itrader/reporting/statistics.py:152`
- Trigger: Any call to `live_system.get_statistics()` on a running live system.
- Workaround: The live system also calls `reporting.get_statistics()` which is not defined on `StatisticsReporting`, so the method would fail before reaching the reporting call regardless.

**`TradingInterface.create_market_order()` Creates `OrderEvent` with `price=0.0`:**
- Symptoms: Market orders created through `TradingInterface` carry `price=Decimal("0")` after `Order.__post_init__` coercion. `EnhancedOrderValidator._validate_price()` checks `if float(order.price) <= 0` and will reject the market order as invalid.
- Files: `itrader/trading_system/trading_interface.py:79`, `itrader/order_handler/order_validator.py:200`
- Trigger: Any live market order created via `TradingInterface.create_market_order()`.
- Workaround: None in the current code — live market orders are blocked by the validator.

---

## Security Considerations

**Hardcoded Database Credentials:**
- Risk: Username `tizianoiacovelli` and password `1234` are committed in plain text.
- Files: `itrader/price_handler/store/sql_store.py:17`
- Current mitigation: The `sql_store` module is quarantined — not imported at package level and unreachable on the backtest run path.
- Recommendations: Move to environment variable (`DATABASE_URL`) or the existing config system; add `.env` to `.gitignore` enforcement; scan git history for any committed credentials.

**No Input Validation on `TradingInterface` Symbol/Side Parameters:**
- Risk: `symbol` and `side` strings from the web API are passed directly into `OrderEvent` and `Side(side)` enum coercion without sanitization. An invalid `side` value raises `ValueError` inside the `try/except Exception` block, which is caught and returns `False`, but the logged error leaks the invalid input value.
- Files: `itrader/trading_system/trading_interface.py:78,130`
- Current mitigation: `except Exception` prevents crashes.
- Recommendations: Validate `side` and `symbol` before constructing events; return structured error responses rather than `bool`.

---

## Performance Bottlenecks

**`BacktestBarFeed.precompute()` Resample on Startup, but Per-Tick Fallback Remains:**
- Issue: M5-03 pre-computes resampled frames once at run-init, but if a strategy's `timeframe` is not in `_mega` the fallback path in `BacktestBarFeed.get_window()` resamples the entire megaframe on every tick.
- Files: `itrader/price_handler/feed/bar_feed.py`
- Cause: The `precompute()` call in `TradingSystem._initialise_backtest_session()` covers registered strategies, but any dynamic use of an unregistered timeframe would hit the fallback.
- Improvement path: Assert that all required timeframes are pre-computed before entering the hot loop; raise loudly on cache miss rather than silently resampling.

**`MetricsManager` Cache Uses Wall-Clock for TTL:**
- Issue: The `_cache_timestamp` dict uses `datetime.now()` for cache invalidation in `_cache_timestamp[cache_key] = datetime.now()` and `cache_age = datetime.now() - self._cache_timestamp[cache_key]`. In backtest mode, bar time advances faster than wall-clock time, so cache age checks may never expire.
- Files: `itrader/portfolio_handler/metrics/metrics_manager.py:252,467`
- Cause: The clock seam is not wired into the metrics manager.
- Improvement path: Replace wall-clock cache TTL with bar-tick-count or advance the clock seam into `MetricsManager`.

---

## Fragile Areas

**`StatisticsReporting` / Reporting Subsystem:**
- Files: `itrader/reporting/statistics.py`, `itrader/reporting/performance.py`, `itrader/reporting/plots.py`
- Why fragile: Multiple broken call paths (`_to_sql`, `print_summary`), dangling `portfolio.metrics` reference, `calculate_statistics()` signature mismatch between the live and backtest callers, unimplemented rolling statistics (marked `#TODO da finire`), and `performance.py` using pervasive `Any` annotations throughout. `calculate_profict_factor` is a public API function with a misspelled name committed in golden outputs.
- Safe modification: Do not call `print_summary()`, `plot_charts()`, `plot_signals()`, or `_to_sql()` outside tests that mock the data. The `scripts/run_backtest.py` oracle path bypasses all of this correctly.
- Test coverage: Zero test coverage for the reporting module.

**`ScreenersHandler` (Deferred Subsystem):**
- Files: `itrader/screeners_handler/screeners_handler.py`, `itrader/screeners_handler/screeners/`
- Why fragile: `ScreenersHandler` constructor is untyped (`# type: ignore[no-untyped-call]`), the screener base uses `#TODO: da testare` on the frequency parameter, and `volume_spyke.py` has a known broken SMA call. The handler is constructed in both `TradingSystem` and `LiveTradingSystem` and wired to the event dispatch, but no screeners are registered in the reference run.
- Safe modification: Only add screeners after verifying `Screener.frequency` wiring and the `screen_markets` dispatch path. Do not enable in production without test coverage.
- Test coverage: No unit tests for screeners. The event-wiring integration test does not exercise screener dispatch.

**`PostgreSQLOrderStorage` (Stub — Live Mode Blocked):**
- Files: `itrader/order_handler/storage/postgresql_storage.py`
- Why fragile: Every method raises `NotImplementedError("To be implemented in Phase 2")`. The `__init__` itself raises, so `OrderStorageFactory.create('live', db_url)` will always fail immediately.
- Safe modification: Do not use `mode='live'` in `OrderStorageFactory`. Live trading is completely blocked on order persistence.
- Test coverage: None.

**`LiveTradingSystem` — Untested in CI:**
- Files: `itrader/trading_system/live_trading_system.py`
- Why fragile: No unit tests exist for `LiveTradingSystem`, `TradingInterface`, or `BINANCELiveStreamer`. The 484-line live system is the most complex module in the repo and handles threading, state machines, and lifecycle, all without test coverage.
- Safe modification: Any change to `LiveTradingSystem` should be manually tested. Do not refactor threading logic without adding tests first.
- Test coverage: No test file covers `live_trading_system.py` or `trading_interface.py`.

**`MatchingEngine` OCO Priority on Same-Bar Fill:**
- Files: `itrader/execution_handler/matching_engine.py:303`, `itrader/execution_handler/exchanges/simulated.py`
- Why fragile: Same-bar OCO priority resolution (`_pick_oco_winner`) selects the resting order whose trigger was hit first based on intrabar high/low distance heuristics. Edge cases with equal distances or simultaneous stop/limit triggers are resolved by arbitrary dict iteration order.
- Safe modification: Regression-lock via the golden oracle before changing any matching logic.
- Test coverage: `tests/unit/execution/test_matching_engine.py` covers basic fill scenarios but OCO tie-breaking has limited coverage.

---

## Scaling Limits

**Single-Symbol Golden Dataset:**
- Current capacity: `CsvPriceStore` defaults to `{CSV_TICKER: CSV_DEFAULT_PATH}` = `{"BTCUSD": "data/BTCUSD_1d_ohlcv_2018_2026.csv"}`. The backtest run path is validated only on this one instrument.
- Limit: Multi-symbol strategies are untested with the CSV store. The `DynamicUniverse` generates `BarEvent`s per symbol, but the `BacktestBarFeed` megaframe and resample cache are keyed by ticker list — adding tickers adds O(n) resample cost at init.
- Scaling path: Wire multi-symbol CSV paths via `CsvPriceStore(symbol_map={...})`; add an integration test with two symbols before extending production use.

**In-Memory Order Storage:**
- Current capacity: `InMemoryOrderStorage` holds all orders in Python dicts with no eviction. Long-running backtests accumulate `FILLED` / `CANCELLED` orders indefinitely.
- Limit: Memory usage grows linearly with trade count. For large universes or long histories this will eventually exhaust available RAM.
- Scaling path: Add a compaction step that archives terminal-state orders to a separate list after a configurable threshold.

---

## Dependencies at Risk

**`pytz` (Legacy Timezone Library):**
- Risk: `pytz` is a pre-PEP-615 library superseded by `zoneinfo` (stdlib since Python 3.9). It uses the `pytz.localize()` / `astimezone()` two-step idiom that differs from the `datetime(tz=...)` stdlib pattern. Mixing `pytz`-aware and `zoneinfo`-aware datetimes can cause subtle comparison failures.
- Files: `itrader/outils/time_parser.py:2`, `itrader/price_handler/providers/ccxt_provider.py:2`, `itrader/price_handler/providers/oanda_provider.py:2`, `itrader/screeners_handler/screeners_handler.py:3`
- Impact: The backtest path hardcodes `TIMEZONE = "Europe/Paris"` as the global tick timezone. Running on a machine configured for a different DST offset can shift bar timestamps and break the backtest oracle.
- Migration plan: Replace `pytz.timezone(...)` with `zoneinfo.ZoneInfo(...)` throughout; use `datetime(..., tzinfo=ZoneInfo("Europe/Paris"))` idiom.

**`sqlalchemy-utils` / `psycopg2-binary`:**
- Risk: `sql_store.py` uses `sqlalchemy_utils.database_exists` and `create_database`, adding a non-trivial dependency for a quarantined module. `psycopg2-binary` is a binary wheel that may conflict with system-level PostgreSQL client libraries.
- Files: `itrader/price_handler/store/sql_store.py:2-3`
- Impact: These imports are guarded (not imported at package level), so no run-path risk. Risk is limited to developer environment setup.
- Migration plan: Replace `sqlalchemy-utils` helpers with native SQLAlchemy 2.0 introspection; keep `psycopg2-binary` in `[tool.poetry.dependencies]` but document that it requires PostgreSQL 14+.

**`websocket-client` / Binance Live Streamer:**
- Risk: `BINANCELiveStreamer` is explicitly quarantined as a `D-live` deferred module. It uses `pd.DataFrame.from_dict(..., dtype=float)` — a `float`-domain entry point — and references `self.prices` which was never initialised in the current code.
- Files: `itrader/price_handler/providers/binance_stream.py:179,181`
- Impact: The live streaming path is completely broken. Any call to `BINANCELiveStreamer.on_message()` that attempts to append data will raise `AttributeError`.
- Migration plan: Rebuild on the new `PriceStore`/`BarFeed` seams introduced in Plan 06-05 before connecting to a live exchange.

---

## Missing Critical Features

**Live Order Persistence:**
- Problem: `PostgreSQLOrderStorage` raises `NotImplementedError` on construction. Live trading has no durable order store — all orders vanish on process restart.
- Blocks: Live trading mode is effectively unusable for any production scenario.

**Price Ingestion Pipeline:**
- Problem: `itrader/price_handler/ingestion.py` raises `NotImplementedError` ("offline ingestion pipeline — deferred to the persistence milestone (D-sql)"). There is no working code path to download new price data into the system.
- Blocks: Updating the golden dataset, backtesting on new date ranges, or running on any new instrument requires manual CSV placement.

**End-to-End Reporting:**
- Problem: `StatisticsReporting.print_summary()` is broken (see Known Bugs). There is no working automated path from a completed backtest to a rendered performance report.
- Blocks: Human-readable backtest results require manual construction from `output/trades.csv` and `output/equity.csv`.

---

## Test Coverage Gaps

**Reporting Module:**
- What's not tested: `StatisticsReporting`, `EngineLogger`, `performance.py` calculation functions, `plots.py` chart constructors.
- Files: `itrader/reporting/statistics.py`, `itrader/reporting/performance.py`, `itrader/reporting/plots.py`, `itrader/reporting/engine_logger.py`
- Risk: Known bugs in `_prepare_data` and `calculate_statistics()` signature mismatches go undetected.
- Priority: Medium — the oracle integration test provides end-to-end behavioral coverage; the reporting module is a display layer.

**Live Trading System:**
- What's not tested: `LiveTradingSystem` lifecycle (start/stop/status), threading behavior, idle timeout, `TradingInterface` order creation.
- Files: `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`
- Risk: Threading bugs (race on `_stats`, idle loop behavior, graceful shutdown) are invisible until live deployment.
- Priority: High — live trading with untested threading is a production risk.

**Screeners Handler:**
- What's not tested: `ScreenersHandler.screen_markets()`, `Screener.calculate_signal()`, `VolumeSpyke`, `MostPerforming`, `BestScreener`, `CointegrationPairsScreener`.
- Files: `itrader/screeners_handler/screeners_handler.py`, `itrader/screeners_handler/screeners/`
- Risk: Screener event dispatch is wired into both trading systems; a buggy screener can corrupt the queue or trigger incorrect universe updates silently.
- Priority: Medium — screeners are not used in the reference backtest.

**`DynamicUniverse`:**
- What's not tested: `DynamicUniverse.generate_bar_event()`, universe update on screener events, bar event emission ordering.
- Files: `itrader/universe/dynamic.py`
- Risk: The universe is in the critical path for every backtest bar; ordering bugs would corrupt trade timing.
- Priority: High — tested indirectly through the oracle integration test only.

**`SimulatedExchange` Edge Cases:**
- What's not tested: Expired orders, `health_check()` failure path, config hot-reload via `update_config()`, `get_status()` telemetry.
- Files: `itrader/execution_handler/exchanges/simulated.py`
- Risk: Order expiry logic (lines 340–395) uses `datetime.now()` and has no test; a clock change or DST transition could cause mass order expiry.
- Priority: Medium — the golden dataset does not exercise order expiry.

---

*Concerns audit: 2026-06-07*
