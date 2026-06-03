# Codebase Concerns

**Analysis Date:** 2026-06-03

## Tech Debt

**PostgreSQL order storage is entirely unimplemented:**
- Issue: `PostgreSQLOrderStorage` in `itrader/order_handler/storage/postgresql_storage.py` raises `NotImplementedError` on every method, including `__init__`. The CLAUDE.md documents it as the live-mode storage backend, but live mode will crash on construction.
- Files: `itrader/order_handler/storage/postgresql_storage.py`
- Impact: Live trading cannot use durable order persistence; restarts lose all in-flight orders.
- Fix approach: Implement each method using SQLAlchemy core or an ORM model; follow the interface defined in `itrader/order_handler/base.py`.

**Dual config system — flat `config.py` alongside domain config package:**
- Issue: `itrader/config.py` (flat module) and `itrader/config/` (domain package) coexist. `CCXT.py` and `OANDA.py` import `FORBIDDEN_SYMBOLS` from `itrader.config` (the flat module), which is shadowed at import time by the package. A comment in `test/test_events/test_event_wiring.py` (lines 13–19) explicitly documents this as a pre-existing import-order bug that forces the test to stub the full handler chain.
- Files: `itrader/config.py`, `itrader/config/` (package), `itrader/price_handler/exchange/CCXT.py` line 8, `itrader/price_handler/exchange/OANDA.py` line 6
- Impact: Any test or import path that triggers `CCXT.py` or `OANDA.py` before the stub workaround will resolve `itrader.config` to the package, not the flat module, causing `ImportError: cannot import name 'FORBIDDEN_SYMBOLS'`.
- Fix approach: Merge `config.py` constants into the domain config package (or a dedicated `itrader/config/symbols.py`), then update all importers.

**`SqlHandler` hard-codes a personal username in the DB connection string:**
- Issue: `itrader/price_handler/sql_handler.py` line 18 contains `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices`. This is not read from the environment.
- Files: `itrader/price_handler/sql_handler.py`
- Impact: Breaks on any machine that is not the author's; exposes a default password.
- Fix approach: Replace with `os.getenv('DATA_DB_URL', ...)` consistent with `Config.DATA_DB_URL` in `itrader/config.py`.

**`legacy_config.py` exists with no callers:**
- Issue: `itrader/legacy_config.py` re-imports from the domain config package and re-declares `FORBIDDEN_SYMBOLS`. No production module imports it.
- Files: `itrader/legacy_config.py`
- Impact: Dead code that complicates the config story and misleads future readers.
- Fix approach: Delete the file once the dual-config issue above is resolved.

**Rolling statistics are unfinished stubs:**
- Issue: `itrader/reporting/statistics.py` lines 166–175 contain a block of rolling-Sharpe code wrapped in a docstring (never executed) with `#TODO da finire`.
- Files: `itrader/reporting/statistics.py`
- Impact: Rolling statistics are silently absent from backtest reports.
- Fix approach: Either implement the rolling window calculation or remove the dead block.

**`VariableSizer` position sizing is incomplete:**
- Issue: `itrader/strategy_handler/position_sizer/variable_sizer.py` line 55 contains `#TODO` with no implementation after computing `quantity`. The rounding call exists, but the logic for integer-only instruments is missing.
- Files: `itrader/strategy_handler/position_sizer/variable_sizer.py`
- Impact: Non-integer position sizes are sent to the exchange for instruments that require whole-unit lots (e.g. futures).
- Fix approach: Add a flag/config for `integer_only` and apply `math.floor()` when set.

**`DynamicUniverse` does not support asset removal:**
- Issue: `itrader/universe/dynamic.py` lines 11–13 document that removal of assets is not implemented.
- Files: `itrader/universe/dynamic.py`
- Impact: Once a ticker enters the universe it cannot be dropped; stale tickers accumulate over long backtests or live sessions.
- Fix approach: Add a `remove_asset` method that removes from both `strategies_universe` and `screeners_universe` lists, and add a corresponding `price_handler` cleanup hook.

**Compliance / `long_only` flag lives in strategy layer instead of order handler:**
- Issue: Multiple strategies (`VWAP_BB_RSI_scalping_strategy.py`, `RSI_scalping_strategy.py`, `Stoch_RSI_Keltner_strategy.py`, `SuperTrand_DD.py`, `SuperSmoothing_strategy.py`) each carry a `self.long_only` flag and filter signals inline. TODOs in those files note it should be in `order_handler.compliance`.
- Files: `itrader/strategy_handler/my_strategies/scalping/VWAP_BB_RSI_scalping_strategy.py` (line 38), `itrader/strategy_handler/my_strategies/scalping/RSI_scalping_strategy.py` (line 56), `itrader/strategy_handler/my_strategies/scalping/Stoch_RSI_Keltner_strategy.py` (line 67), `itrader/strategy_handler/my_strategies/trend_following/SuperTrand_DD.py` (line 129), `itrader/strategy_handler/my_strategies/trend_following/SuperSmoothing_strategy.py` (line 130)
- Impact: Compliance rules are silently scattered across strategies; adding a new strategy can accidentally omit them.
- Fix approach: Add a `ComplianceManager` in `order_handler/` that receives `SignalEvent` and rejects/modifies it before `OrderManager.on_signal` proceeds. Remove per-strategy flags.

**`RiskManager.check_cash` skips position-increase scenario:**
- Issue: `itrader/strategy_handler/risk_manager/advanced_risk_manager.py` line 45 contains `# TODO: implement check cash in case of position increase`. Cash is only checked for new positions, not for adding to an existing one.
- Files: `itrader/strategy_handler/risk_manager/advanced_risk_manager.py`
- Impact: A strategy that increases a position can overdraw cash without rejection, causing inaccurate portfolio accounting.
- Fix approach: When `ticker` is already in `open_tickers`, calculate the incremental cost and verify it against available cash.

**`OANDA.py` hardcodes config file path:**
- Issue: `itrader/price_handler/exchange/OANDA.py` line 34 calls `tpqoa.tpqoa('oanda.cfg')` with a hardcoded filename, and a commented-out duplicate exists on line 32.
- Files: `itrader/price_handler/exchange/OANDA.py`
- Impact: The path is not configurable and will fail if the working directory changes or the file is renamed.
- Fix approach: Read the path from `Config` or an environment variable; remove the commented duplicate.

## Known Bugs

**`raise NotImplemented` (not `NotImplementedError`) in event handler:**
- Symptoms: When an unknown event type reaches `process_events`, Python raises `TypeError: exceptions must derive from BaseException` at runtime because `NotImplemented` is a built-in constant, not an exception class.
- Files: `itrader/events_handler/full_event_handler.py` line 84, `itrader/events_handler/screener_event_handler.py` line 57
- Trigger: Any event type not in the dispatch chain (e.g. a newly added `EventType` member without a corresponding `elif`).
- Workaround: None — the process crashes with a `TypeError` instead of the intended descriptive message.

**`is np.nan` identity comparison is always `False`:**
- Symptoms: `temporal_statistics['mly_avg_win_pct']` is never reset to `0` when there are no winning months, so downstream callers receive `NaN` instead of `0`.
- Files: `itrader/reporting/statistics.py` line 145
- Trigger: A backtest period with zero profitable months triggers this path.
- Workaround: None; replace with `pd.isna(...)` or `math.isnan(...)`.

**Live system double-queues events before `process_events`:**
- Symptoms: In `_event_processing_loop`, the code calls `self.global_queue.get(...)` to pull an event, then immediately calls `self.global_queue.put(event)` to put it back before calling `process_events()`. `process_events` drains the queue via `get(False)` internally. This means every event is dequeued and re-enqueued once before processing — the count sentinel `task_done` is called after `put` but before the inner `get`, creating an unbalanced `task_done` / `get` sequence on the `Queue`.
- Files: `itrader/trading_system/live_trading_system.py` lines 209–223
- Trigger: Always; this is the normal operating path.
- Workaround: None; but since no `join()` is called, the task-done imbalance does not currently deadlock — it just adds latency and misleads queue-size monitoring.

**`get_statistics` on `LiveTradingSystem` calls non-existent method:**
- Symptoms: `live_trading_system.py` line 408 calls `self.reporting.get_statistics()` but `StatisticsReporting` (defined in `itrader/reporting/statistics.py`) has no `get_statistics` method. The comment on line 408 reads `# Assuming this method exists`.
- Files: `itrader/trading_system/live_trading_system.py` line 408, `itrader/reporting/statistics.py`
- Trigger: Any call to `LiveTradingSystem.get_statistics()`.
- Workaround: The method is wrapped in a try/except that swallows the `AttributeError` and returns `None`.

**`BINANCE_Live.py` ping logic is hardcoded to fire on every 5th closed bar:**
- Symptoms: Lines 103–110 of `itrader/price_handler/live_streaming/BINANCE_Live.py` send a `PingEvent` only when `self._closed == 5`. This means the system always lags five bars behind live data and ignores the configured timeframe.
- Files: `itrader/price_handler/live_streaming/BINANCE_Live.py` lines 99–110
- Trigger: Always active during live Binance streaming.
- Workaround: None; the counter is also never reset on the branch that fires the ping (only reset on the else-branch ping method that is commented out).

## Security Considerations

**Default database credentials stored in source:**
- Risk: `Config.DATA_DB_URL` defaults to `postgresql+psycopg2://postgres:1234@localhost:5432/...` and `SqlHandler.init_engine` hard-codes `tizianoiacovelli:1234`. If the environment variable is unset in production, real credentials may be overridden by these defaults or the hard-coded value is used directly.
- Files: `itrader/config.py` lines 64–65, `itrader/price_handler/sql_handler.py` line 18
- Current mitigation: `DATA_DB_URL` env override exists for `config.py`; `sql_handler.py` has no override.
- Recommendations: Remove all hardcoded credential defaults; raise `ValueError` if the required env var is absent in non-dev environments.

**`oanda.cfg` credential file path is hardcoded and relative:**
- Risk: `tpqoa.tpqoa('oanda.cfg')` resolves relative to the process working directory. If a web API or scheduler changes the working directory, a different (or missing) file is loaded silently.
- Files: `itrader/price_handler/exchange/OANDA.py` line 34
- Current mitigation: None.
- Recommendations: Resolve to an absolute path via `Path(__file__).parent / '...' / 'oanda.cfg'` or load from environment variables.

## Performance Bottlenecks

**`time.sleep(0.1)` in the simulated exchange connect path:**
- Problem: `SimulatedExchange.connect()` unconditionally sleeps 100 ms to "simulate realistic latency". This fires in every backtest that calls `connect`.
- Files: `itrader/execution_handler/exchanges/simulated.py` line 277
- Cause: Unconditional `time.sleep` under `_lock`.
- Improvement path: Gate the sleep behind the `simulate_failures` flag or remove it entirely from the backtest preset.

**`random.uniform` / `random.choice` use unseed `random` in slippage and failure simulation:**
- Problem: Both slippage models (`fixed_slippage_model.py`, `linear_slippage_model.py`) and `SimulatedExchange` use the global `random` state, making backtests non-reproducible by default.
- Files: `itrader/execution_handler/slippage_model/fixed_slippage_model.py` line 61, `itrader/execution_handler/slippage_model/linear_slippage_model.py` line 63, `itrader/execution_handler/exchanges/simulated.py` lines 142, 150, 181
- Cause: No seed is set anywhere in the trading system initialisation.
- Improvement path: Expose a `random_seed` parameter in `ExchangeConfig` and call `random.seed()` during exchange initialisation.

**In-memory order storage uses nested dict iteration for every lookup:**
- Problem: `InMemoryOrderStorage.remove_order` iterates all `active_orders` portfolios and all orders within each (O(n) scan) to find the order by key.
- Files: `itrader/order_handler/storage/in_memory_storage.py` lines 115–142
- Cause: Orders are stored in a nested `{portfolio_key: {order_key: order}}` dict but looked up without direct keying on portfolio.
- Improvement path: Since `Order` objects carry `portfolio_id`, index a flat `{order_key: order}` dict alongside the portfolio-grouped dict, enabling O(1) removal.

**Strategy direct access to `price_handler.prices` dict:**
- Problem: `SuperTrand_DD.py` line 82 accesses `self.price_handler.prices[event.ticker].loc[start_dt : event.time]` directly, bypassing the `get_resampled_bars` API. This pulls the entire in-memory price series and slices it on every bar.
- Files: `itrader/strategy_handler/my_strategies/trend_following/SuperTrand_DD.py` line 82
- Cause: Convenience shortcut around the official price handler API.
- Improvement path: Use `self.price_handler.get_resampled_bars(...)` consistently; the data handler can cache slices.

## Fragile Areas

**`BarEvent.get_last_close` type-branches around an unresolved data inconsistency:**
- Files: `itrader/events_handler/event.py` lines 72–83
- Why fragile: A TODO acknowledges that `close_data` is not consistently a `Series`, so the method has three separate type-dispatch branches. Adding a new data path that returns a different structure silently picks the wrong branch and returns the wrong price.
- Safe modification: Resolve the upstream inconsistency (standardise `BarEvent.bars` to always contain a `pd.Series` for each column); remove the type branches.
- Test coverage: No dedicated unit test for the scalar and numpy-array code paths.

**`full_event_handler.process_events` calls `queue.get(False)` inside `queue.empty()` check:**
- Files: `itrader/events_handler/full_event_handler.py` lines 61–65
- Why fragile: `queue.empty()` and `queue.get(False)` are not atomic. Under concurrent producers (live mode), an item can be removed between the `empty()` check and the `get`, causing a spurious `queue.Empty` that sets `event = None`. The next line `event.type` then raises `AttributeError`.
- Safe modification: Remove the `empty()` guard; use `try: event = queue.get(False) except queue.Empty: break` exclusively.
- Test coverage: The test stubs the queue, so the race is never exercised.

**Strategies hold a `self.portfolio = None` reference that is never populated through the standard handler flow:**
- Files: `itrader/strategy_handler/my_strategies/trend_following/SuperTrand_DD.py` line 55, `itrader/strategy_handler/my_strategies/trend_following/SuperSmoothing_strategy.py` line 41, `itrader/strategy_handler/my_strategies/mean_reversion/PriceD_BB.py` line 54, `itrader/strategy_handler/my_strategies/mean_reversion/PriceD_BB_2.py` line 54
- Why fragile: The base `Strategy` class and `StrategiesHandler` never assign `portfolio`. Strategies that access `self.portfolio.positions` raise `AttributeError` unless the caller manually injects the object before the first `calculate_signal` call.
- Safe modification: Remove direct portfolio access from strategies; derive open-position state from `SignalEvent` context or inject a read-only view via the `StrategiesHandler`.
- Test coverage: The strategy test (`test/test_strategy/test_strategy.py`) uses a mock that does not exercise the `self.portfolio` path.

**Deprecated `fillna(method='ffill')` call in OANDA data handler:**
- Files: `itrader/price_handler/exchange/OANDA.py` line 80
- Why fragile: `fillna(method=...)` was deprecated in pandas 2.1 and removed in pandas 3.0. Upgrading pandas breaks OANDA data download silently at the fill step.
- Safe modification: Replace with `data.ffill(inplace=True)`.
- Test coverage: None — price handler exchange adapters have no unit tests.

**`statistics._to_sql` uses deprecated `engine.execute`:**
- Files: `itrader/reporting/statistics.py` lines 242, 255
- Why fragile: `Engine.execute()` was removed in SQLAlchemy 2.0. Calling `_to_sql` with a 2.x engine raises `AttributeError`.
- Safe modification: Replace with `with engine.connect() as conn: conn.execute(...); conn.commit()`.
- Test coverage: None.

**`screeners_handler` frequency-based triggering is marked as untested:**
- Files: `itrader/screeners_handler/screeners/base.py` line 28
- Why fragile: `self.frequency = to_timedelta(frequency)` carries a `#TODO: da testare` comment. No test verifies that screeners fire at the correct interval.
- Safe modification: Add a unit test covering the `check_timeframe` guard in the screener base before modifying screener timing logic.
- Test coverage: No screener tests exist in `test/`.

**`volume_spyke` screener SMA window argument is silently ignored:**
- Files: `itrader/screeners_handler/screeners/volume_spyke.py` line 40
- Why fragile: `overlap.sma` does not accept `length` as a keyword argument in the version used; the TODO confirms it is broken. The screener computes a SMA with the default window regardless of configuration.
- Safe modification: Verify the `pandas_ta` API signature; use the positional `length` argument or the correct keyword.
- Test coverage: None.

## Scaling Limits

**In-memory order storage for live trading:**
- Current capacity: Unbounded in-memory dict; no eviction policy.
- Limit: Memory grows linearly with order history over long live sessions. Cancelled and filled orders remain in `all_orders` indefinitely.
- Scaling path: Implement `PostgreSQLOrderStorage` (see Tech Debt section) and add a periodic archival/cleanup job.

**Single `queue.Queue` for all event types:**
- Current capacity: Default `maxsize=0` (unbounded).
- Limit: Under burst conditions (e.g. screener produces many `SCREENER` events simultaneously with `BAR` events), high-priority pipeline events (`SIGNAL`, `ORDER`, `FILL`) can be delayed behind low-priority ones.
- Scaling path: Introduce separate queues per priority tier or use `queue.PriorityQueue` with an event-type weight.

## Dependencies at Risk

**`tpqoa` for OANDA connectivity:**
- Risk: `tpqoa` is a small community library with infrequent maintenance. The OANDA v20 REST API has changed breaking fields since the library's last update.
- Impact: OANDA data download and live feed are broken or produce malformed DataFrames.
- Migration plan: Switch to the official `oandapyV20` client and implement the `AbstractExchangeAdapter` interface directly.

**SQLAlchemy `engine.execute` API (removed in 2.0):**
- Risk: `itrader/reporting/statistics.py` uses the legacy 1.x execution style.
- Impact: `_to_sql` raises `AttributeError` on SQLAlchemy >= 2.0.
- Migration plan: Rewrite using `with engine.connect() as conn:` context manager pattern.

## Missing Critical Features

**No live order persistence:**
- Problem: The only working `OrderStorage` implementation is `InMemoryOrderStorage`. A live system restart loses all resting stop/limit orders.
- Blocks: Safe live trading with bracket orders or any multi-session strategy.

**No compliance layer in order handler:**
- Problem: `long_only`, `short_only`, and similar directional constraints are scattered across individual strategy files rather than enforced centrally.
- Blocks: Adding a new strategy without accidentally omitting compliance rules; auditing constraint coverage.

**No reconnection logic for Binance WebSocket:**
- Problem: `itrader/price_handler/live_streaming/BINANCE_Live.py` has `_on_close` and `_on_error` callbacks but no automatic reconnection loop.
- Blocks: Unattended live operation — any WebSocket drop silently stops the feed with no recovery.

## Test Coverage Gaps

**Price handler and exchange adapters:**
- What's not tested: `CCXT.py`, `OANDA.py`, `SqlHandler`, `PriceHandler.load_data`, `PriceHandler.update_data`, `BINANCE_Live.py`.
- Files: `itrader/price_handler/`
- Risk: Data download failures, malformed DataFrames, and deprecated API calls go undetected until runtime.
- Priority: High

**Screeners:**
- What's not tested: `ScreenersHandler`, `VolumeSpyke`, `MostPerforming`, `CointegratedPairs`, `BaseScreener` frequency logic.
- Files: `itrader/screeners_handler/`
- Risk: Screener misfires (wrong frequency, wrong SMA window) silently corrupt the universe sent to strategies.
- Priority: High

**Reporting and statistics:**
- What's not tested: `StatisticsReporting.calculate_statistics`, `_equity_statistics`, `_trade_statistics`, `_temporal_statistics`, `plot_charts`, `_to_sql`.
- Files: `itrader/reporting/`
- Risk: NaN-comparison bug, missing `get_statistics` method, and deprecated SQLAlchemy calls are not caught by the test suite.
- Priority: Medium

**Live trading system:**
- What's not tested: `LiveTradingSystem.start`, `stop`, `_event_processing_loop`, `get_statistics`, status callbacks, `TradingInterface`.
- Files: `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`
- Risk: The event double-queue bug, the `NotImplementedError` from PostgreSQL storage, and the missing `get_statistics` method are all in untested code paths.
- Priority: High

**Universe:**
- What's not tested: `DynamicUniverse.generate_bar_event`, `init_universe`, asset-removal gap.
- Files: `itrader/universe/dynamic.py`
- Risk: Missing bar data for a ticker causes a silent `None` to be inserted into `BarEvent.bars`, which downstream handlers do not guard against.
- Priority: Medium

---

*Concerns audit: 2026-06-03*
