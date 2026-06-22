# Codebase Concerns

**Analysis Date:** 2026-06-22

---

## Tech Debt

### Deferred: Flip/Split Full-Settlement Economics (CR-02-residual from Phase 2)

- Issue: A fill that would flip a position direction (over-close) raises `InvalidTransactionError` before any mutation as a fail-loud guard. The correct economics — split a flip fill into full-close + fresh-open, or clamp `realised_increment` to the closed quantity — are not implemented.
- Files: `itrader/portfolio_handler/portfolio.py` (on-fill settlement path), `itrader/order_handler/reconcile/reconcile_manager.py`
- Impact: A flip fill in backtest aborts the run via the fail-fast error policy. In live mode (`publish-and-continue`) the over-close order is rejected but no fill settles. Pair strategies and any strategy that issues a same-bar direction reversal via a direct opposite order cannot use the engine until this is addressed.
- Fix approach: In `portfolio.py` on-fill settlement, detect when `transaction.quantity > position.net_quantity` (over-close); split into a close transaction (settling realized PnL for the full existing size) followed by a fresh-open transaction for the remainder. Track tagged as `CR-02-residual` in `.planning/milestones/v1.4-phases/02-margin-accounting-leverage/deferred-items.md`.

### Deferred: Single Global Maintenance-Margin Rate (`_DEFAULT_MAINTENANCE_MARGIN_RATE`)

- Issue: `universe/instruments.py:62` defines `_DEFAULT_MAINTENANCE_MARGIN_RATE = Decimal("0.005")` as a single hard-coded global that applies to every symbol when no per-symbol override is declared. All liquidation logic (`PortfolioHandler.maintenance_margin`, `_collect_breaches_over_prices`) reads `Instrument.maintenance_margin_rate` which for most symbols falls back to this magic constant. No per-instrument MMR table or configuration surface exists.
- Files: `itrader/universe/instruments.py:62`, `itrader/portfolio_handler/portfolio_handler.py:458`
- Impact: A real multi-asset portfolio would use wildly wrong liquidation thresholds if symbols are not individually declared with a correct `maintenance_margin_rate` in the `Universe`. The Phase 4 liquidation cross-validation passes because it uses a single explicitly-declared test symbol.
- Fix approach: Expose a `maintenance_margin_rate` column in the universe declaration table (e.g. `settings/domains/instruments.yaml`) and validate at `derive_instruments` that every production symbol has a declared rate. Tracked as `IN-03` in `.planning/milestones/v1.4-phases/02-margin-accounting-leverage/deferred-items.md`.

### Deferred: `order_type_map` / `order_status_map` / `order_command_map` Dead Weight

- Issue: `itrader/core/enums/order.py:63-117` defines three string→enum dicts that duplicate what `OrderType(value)` (via `_missing_`) already provides case-insensitively. `TRAILING_STOP` was added to the map to keep it in sync, but the maps themselves have no remaining call sites that cannot use the enum's own string parse. They are re-exported in `core/enums/__init__.py`.
- Files: `itrader/core/enums/order.py:63`, `itrader/core/enums/__init__.py:42-44,93-95`
- Impact: Low — dead code, no behavioral risk. Each new `OrderType` member must be added to two places (enum + map), creating a maintenance hazard.
- Fix approach: Confirm no callers use the maps directly (grep confirms no `order_type_map[` usage in production code), then remove the three dicts and their `__init__.py` exports. Tracked as `IN-02` in `.planning/milestones/v1.4-phases/05-engine-native-trailing-stops/05-REVIEW.md`.

### Deferred: Dead `Portfolio.update_market_value` Entry Point

- Issue: `itrader/portfolio_handler/portfolio.py:503` defines `update_market_value(bar_event: BarEvent)`. The only live caller on the run path is `PortfolioHandler.update_portfolios_market_value` which calls `portfolio.update_market_value_of_portfolio(prices, bar_time, self._universe)` instead. The `bar_event` variant is never called on the run path.
- Files: `itrader/portfolio_handler/portfolio.py:503-515`
- Impact: Dead code only. Future maintainers may add a second call site to the wrong method, bypassing the carry-bearing `update_market_value_of_portfolio` and silently skipping borrow-carry accrual.
- Fix approach: Remove `update_market_value(bar_event)` or fold it into `update_market_value_of_portfolio` with a deprecation note. Tracked as `IN-01` in `.planning/milestones/v1.4-phases/03-shorts-borrow-carry/deferred-items.md`.

### Deferred: Unreachable `net_quantity < 0` Branch in `_validate_position_consistency`

- Issue: `itrader/portfolio_handler/position/position_manager.py:228` checks `position.net_quantity < 0 and abs(position.net_quantity) > Decimal("0.000001")`. Since `net_quantity` is derived as the absolute value of long `buy_qty - sell_qty`, this branch is structurally unreachable for a `LONG` position and is the wrong guard to catch signed-read accidents.
- Files: `itrader/portfolio_handler/position/position_manager.py:228`
- Impact: A future change that introduces a signed `net_quantity` read would silently bypass the guard. The branch reads as if it protects against negative quantity but never fires.
- Fix approach: Convert to an assertion documenting the unsigned invariant: `assert position.net_quantity >= 0, "net_quantity must be unsigned"`. Tracked as `IN-02` in `.planning/milestones/v1.4-phases/03-shorts-borrow-carry/deferred-items.md`.

### Deferred: Inconsistent Zero-Exponent Seeds in Cash/Margin Getters

- Issue: `itrader/portfolio_handler/storage/in_memory_storage.py:82` seeds `get_reserved_cash` with `Decimal("0.00")` (two decimal places) while `:96` seeds `get_locked_margin` with `Decimal("0")` (no places). Both are byte-exact today because `sum()` carries more precision, but the inconsistency is a readability trap.
- Files: `itrader/portfolio_handler/storage/in_memory_storage.py:82,96`
- Impact: No current correctness impact. Future arithmetic on these returns may propagate the exponent difference into surprising precision behavior.
- Fix approach: Pick `Decimal("0")` (idiomatic) or `Decimal("0.00")` uniformly across both. Tracked as `IN-04` in `.planning/milestones/v1.4-phases/03-shorts-borrow-carry/deferred-items.md`.

### Deferred: `position_manager.py:171` Uses Raw `Decimal(str())` Instead of `to_money`

- Issue: `itrader/portfolio_handler/position/position_manager.py:171` calls `Decimal(str(signal_leverage))` directly when comparing against `position.leverage`. The project money convention requires entering the Decimal domain via `to_money(x)` (`itrader/core/money.py`) to avoid binary-float representation artifacts if a float slips through.
- Files: `itrader/portfolio_handler/position/position_manager.py:171`
- Impact: Correctness only if `signal_leverage` is ever a float (currently it is typed `Decimal`). Convention violation, not a current bug.
- Fix approach: Replace `Decimal(str(signal_leverage))` with `to_money(signal_leverage)`. Tracked as `IN-02` in `.planning/milestones/v1.4-phases/02-margin-accounting-leverage/deferred-items.md`.

### Deferred: `process_signal` Step-0 Docstring Omits the Short SELL-Add Case

- Issue: `itrader/order_handler/admission/admission_manager.py:125-133` step-0 docstring enumerates the `LONG_ONLY` direction case, the `BUY-while-long allow_increase=False` case, and the `max_positions` case, but does not mention the `SELL-add-while-short allow_increase=False` audited rejection gate added in Phase 5.1.
- Files: `itrader/order_handler/admission/admission_manager.py:125`
- Impact: Doc-only. In a codebase where decision-anchored docstrings are load-bearing references (CLAUDE.md), an incomplete step-0 summary misleads maintainers adding short-specific logic.
- Fix approach: Add a clause covering the symmetric short SELL-add gate. Tracked as `IN-01` in `.planning/milestones/v1.4-phases/05.1-short-position-scale-in-margin-increase/05.1-REVIEW.md`.

### Deferred: `get_config_dict` Inconsistent Serialization Shape

- Issue: `itrader/execution_handler/exchanges/simulated.py:775-792` calls `float()` for `failure_rate`, `min_order_size`, `max_order_size` at the serialization edge but returns `fee_rate`, `maker_rate`, `taker_rate`, `base_slippage_pct`, `slippage_pct` as raw `Decimal` (or `None`). A caller JSON-encoding this dict receives a mixed-type map.
- Files: `itrader/execution_handler/exchanges/simulated.py:781-791`
- Impact: Any caller that JSON-encodes `get_config_dict()` will raise on the raw `Decimal` fields. Currently no production caller does this; it is a monitoring/diagnostic method only.
- Fix approach: Apply `float()` uniformly to rate fields at the serialization boundary, or return raw `Decimal` for all (and document that callers must serialize explicitly). Tracked as `IN-01` in `.planning/milestones/v1.4-phases/05-engine-native-trailing-stops/05-REVIEW.md`.

### Deferred: `Portfolio.user_id` — Unmapped Persistence Field

- Issue: `itrader/portfolio_handler/portfolio.py:52` stores `self.user_id: int`. This is an application-level user identifier with no corresponding persistence or auth layer. It is required in `add_portfolio` signature (`portfolio_handler.py:152`) and `system_spec.py:46`. Removal was deferred to an independent cleanup pass at v1.4 close.
- Files: `itrader/portfolio_handler/portfolio.py:52`, `itrader/portfolio_handler/portfolio_handler.py:152`, `itrader/trading_system/system_spec.py:46`
- Impact: Low. Adds an unnecessary required constructor parameter that callers must supply with a meaningless integer. Cleanup deferred per STATE.md.

---

## Known Bugs

### Market-Hours Validator Uses Tz-Naive Time Comparison

- Symptoms: `_validate_market_hours` in `EnhancedOrderValidator` calls `order.time.time()` (strips timezone) and compares against naive `time(9,30)` / `time(16,0)` market-hours bounds.
- Files: `itrader/order_handler/order_validator.py:328-351`
- Trigger: Only reached when the portfolio's exchange is `"NYSE"` or `"NASDAQ"` — never reached on the crypto/csv backtest path (exchange is `"simulated"` or `"csv"`). Oracle-dark.
- Workaround: None. The comparison is always skipped on current run paths.
- Fix: When activating NYSE/NASDAQ validation, convert `order.time` to the exchange's local timezone before extracting `.time()`. Tracked as `IN-04` in `.planning/milestones/v1.4-phases/05-engine-native-trailing-stops/05-REVIEW.md`.

### Live System Falls Back to In-Memory Order Storage Silently

- Symptoms: `LiveTradingSystem.__init__` (line 137) catches `NotImplementedError` from `OrderStorageFactory.create('live', ...)` and falls back to in-memory storage with only a `logger.warning`. Orders are lost across restarts without operator awareness.
- Files: `itrader/trading_system/live_trading_system.py:130-140`, `itrader/order_handler/storage/postgresql_storage.py` (all methods raise `NotImplementedError`)
- Trigger: Any live run when `SYSTEM_DB_URL` is set but the PostgreSQL storage class has not been implemented.
- Workaround: Ensure `SYSTEM_DB_URL` is unset; the code takes the in-memory path explicitly.

---

## Security Considerations

### Live Trading Interface Validates Quantity/Price as `float()` — Entry Boundary Gap

- Risk: `itrader/trading_system/trading_interface.py:180,189` converts incoming order parameters to `float` for validation. If an external API passes a string like `"1e300"` or `"NaN"`, the float cast succeeds, passing the `> 0` check. The float value is then used to construct an `OrderEvent` before the Decimal money domain begins.
- Files: `itrader/trading_system/trading_interface.py:170-198`
- Current mitigation: None at this boundary; the `EnhancedOrderValidator` downstream rejects extreme prices via `_validate_price_ranges`, but a NaN would not fail `> 0`.
- Recommendations: Replace `float(quantity)` / `float(price)` with `to_money(quantity)` / `to_money(price)` at the `TradingInterface` boundary; wrap in a `try/except (InvalidOperation, ValueError)` and return an error. This also eliminates the float-for-money policy gap at this site.

### Environment Secrets Only Validated at Import Time

- Risk: `itrader/__init__.py` initializes `config = SystemConfig.default()` on import, loading env vars via `pydantic-settings`. The `.env` file at repo root is loaded by `Makefile` and available to all `make` targets. No runtime secret rotation is possible without a process restart.
- Files: `itrader/__init__.py`, `itrader/config/settings.py`
- Current mitigation: `.env` is gitignored in production. The settings layer validates structure but does not scrub secrets from process memory.
- Recommendations: For live trading, source secrets from a secrets manager rather than `.env` files. No change needed for the backtest path.

---

## Performance Bottlenecks

### `_fit_beta` and `_coint_pvalue` Duplicate Log-Array Computation in `EthBtcPairStrategy`

- Problem: `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:129-130` and `:165-166` each independently compute `np.log(win_A["close"].to_numpy(dtype=float)[:self.beta_warmup])` and `np.log(win_B["close"].to_numpy(dtype=float)[:self.beta_warmup])`. Both are called from `evaluate_pair` on every bar during the fit-once gate, doubling the log computation.
- Files: `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:121,149`
- Cause: `_fit_beta` and `_coint_pvalue` are separate methods without a shared intermediate.
- Improvement: Extract the shared log arrays into a helper or cache the result as an instance attribute after the first fit. Tracked as `IN-03` in `.planning/milestones/v1.4-phases/06-pair-trading-flagship/06-REVIEW.md` (accepted deferral — fit-once, dormant after warmup).

### Carry Accrual Charges Full Multi-Day Gap at Current Close Mark

- Problem: `itrader/portfolio_handler/portfolio.py:671` computes short carry as `days × current_price × |net_quantity| × borrow_rate / 365`. For a gap of N days (e.g. weekend) it charges the full interval at the CURRENT bar's close, not a per-day interpolation. For instruments with significant price movement over the gap, carry is over- or under-stated.
- Files: `itrader/portfolio_handler/portfolio.py:666-742`
- Cause: The bar feed delivers only close prices; no per-day mark feed exists.
- Improvement: A per-day borrow-rate time-series with per-day price marks ("Phase B" perp realism). Tracked as `IN-03` in `.planning/milestones/v1.4-phases/03-shorts-borrow-carry/deferred-items.md`.

---

## Fragile Areas

### Screeners Subsystem: Untyped, Untested, Not Mypy-Strict

- Files: `itrader/screeners_handler/screeners_handler.py`, `itrader/screeners_handler/screeners/volume_spyke.py`, `itrader/screeners_handler/screeners/base.py`
- Why fragile: The `ScreenersHandler` is excluded from `mypy --strict` via `[[tool.mypy.overrides]]` (`ignore_errors = true`). It has no dedicated unit tests (no `tests/unit/screeners/` directory). The `volume_spyke.py` screener uses a `TODO` noting the `sma` call does not accept the `window` argument as expected. `init_screeners` calls `get_timenow_awere()` (wall-clock) at wiring time, violating the determinism contract.
- Safe modification: Any change to `ScreenersHandler` must be hand-verified — no test catches regressions. Do not add `screen_markets` to the BAR route in backtest without adding unit tests first.
- Test coverage: No screener-specific unit tests; only incidental coverage via the event-wiring integration test.

### PostgreSQL Order Storage: Entire Interface Raises `NotImplementedError`

- Files: `itrader/order_handler/storage/postgresql_storage.py`
- Why fragile: All 15 methods of `PostgreSQLOrderStorage` raise `NotImplementedError("To be implemented in Phase 2")`. The `OrderStorageFactory` selects it for `environment='live'`. Any live trading path that reaches order storage will raise immediately.
- Safe modification: Do not expose `environment='live'` to operators until PostgreSQL storage is implemented. The live system currently catches the `NotImplementedError` in `__init__` and falls back to in-memory (itself a fragile silent degradation — see Known Bugs).

### `my_strategies/` — Compliance TODOs Not Hooked to the Engine

- Files: `itrader/strategy_handler/my_strategies/scalping/Stoch_RSI_Keltner_strategy.py:67`, `itrader/strategy_handler/my_strategies/momentum/ATR_Hawkes_Momentum_strategy.py:129`, `itrader/strategy_handler/my_strategies/scalping/RSI_scalping_strategy.py:56`, `itrader/strategy_handler/my_strategies/scalping/VWAP_BB_RSI_scalping_strategy.py:38`
- Why fragile: Multiple strategies contain `# TODO: da spostare in order_handler.compliance` comments next to inline long-only enforcement logic. These strategies implement their own direction filtering rather than declaring `direction = Direction.LONG_ONLY` on the strategy class. If any of these strategies are wired into a short-capable run, the engine will not enforce the direction gate and the strategy's own inline logic will be the only safeguard.
- Safe modification: These strategies are under `my_strategies/` (excluded from mypy-strict). Do not wire them into production runs without migrating the compliance logic to the `direction` class attribute.

### Pair Strategy Re-Entry After Single-Leg Liquidation (D-07×D-12 Gap)

- Files: `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`, `itrader/strategy_handler/pair_base.py`
- Why fragile: `PairStrategy._in_pair` tracks whether a pair is open using the `PortfolioReadModel`. If one leg is force-liquidated while the other remains open, `_in_pair` may still read as True (because one position exists), blocking a fresh entry; OR the open leg triggers an unbalanced `evaluate_pair` close signal. The D-07×D-12 interaction is documented as accepted for the current flagship (ETH/BTC has never been simultaneously levered to the liquidation threshold in the golden data), but is an unguarded edge.
- Safe modification: Before using the pair strategy in a liquidation-possible margin configuration, add a pair-consistency guard: if one leg is missing, log and skip `evaluate_pair` rather than potentially firing a half-close.

### Trailing-Stop `PercentFromFill` Cross-Val Script Uses a 500%-TP Sentinel

- Files: `scripts/crossval/trailing_run.py:100-105`
- Why fragile: `PercentFromFill(tp_pct=Decimal("5"), ...)` sets the TP 500% above the fill to keep it unreachable. A maintainer copying this snippet into a real strategy would place a reachable TP at 500%, not 5%.
- Safe modification: Add an explicit inline comment: `# tp_pct=5 is intentionally 500% — an unreachable sentinel so only the trailing SL exits`. Tracked as `IN-03` in `.planning/milestones/v1.4-phases/05-engine-native-trailing-stops/05-REVIEW.md`.

---

## Scaling Limits

### Bar-Close Liquidation — No Intrabar Mark Feed

- Current behavior: Maintenance-margin breach is detected once per bar using the bar's `close` price (`PortfolioHandler._collect_breaches_over_prices`, `portfolio_handler.py:613`). A large intrabar gap (open-to-low) that would breach maintenance margin does NOT trigger liquidation until close.
- Files: `itrader/portfolio_handler/portfolio_handler.py:574-640`
- Limit: For daily OHLCV data this is the documented honest approximation (Phase 4 design decision). For intraday data, a position could sustain losses far beyond the maintenance margin before liquidation fires.
- Scaling path: Phase-B perp realism — a mark-price feed delivering intrabar mid-prices + a finer trigger cadence (per-minute or per-tick). Tagged `FUND-01..04` in ROADMAP.md.

### In-Memory Order and Portfolio Storage — No Restart Survival

- Current behavior: Backtest uses `InMemoryOrderStorage` and `PortfolioStateStorageFactory.create("backtest")`. All order and portfolio state is held in process memory.
- Files: `itrader/order_handler/storage/in_memory_storage.py`, `itrader/portfolio_handler/storage/storage_factory.py`
- Limit: No persistence between runs for live mode. An accidental process kill loses all live positions and orders (no reconcile on restart).
- Scaling path: Implement `PostgreSQLOrderStorage` (currently all `NotImplementedError`) and a corresponding `PortfolioStateStorage` backed by PostgreSQL. Tagged as backlog phase `999.2-nplus2-persistence-and-performance`.

---

## Dependencies at Risk

### `pandas-ta 0.4.71b0` — Pinned Beta, Abandoned Upstream

- Risk: `pyproject.toml:18` pins `pandas-ta = "0.4.71b0"`, a beta release of a library whose upstream repository has been inactive. The `b0` suffix indicates a pre-release, and the package cannot be upgraded without potentially breaking the custom indicator calls in `my_strategies/`.
- Impact: `itrader/screeners_handler/screeners/volume_spyke.py`, `itrader/strategy_handler/my_strategies/filters/` and the scalping strategies under `my_strategies/` all import from `pandas_ta` internals (`from pandas_ta import overlap`, `from pandas_ta.volatility import atr`). These internal sub-package imports break on version bumps.
- Migration plan: Migrate the `my_strategies/` and screener indicators to the `ta` library (already a dependency at `^0.11.0`) or to raw `pandas`/`numpy` equivalents, then drop `pandas-ta`.

---

## Missing Critical Features

### Perpetual Funding Rate / Mark-Price Liquidation (Phase B — Deferred to N+4)

- Problem: `Instrument.settles_funding` is an inert flag (`instrument.py:96`, always `False`). No funding-rate data pipeline, funding accrual mechanism, or mark-price liquidation trigger exists. Crypto perpetuals accrue funding every 8 hours; the engine charges daily borrow-carry as a static approximation instead.
- Blocks: Correct simulation of BTC/ETH perpetual contracts (BTCUSD, ETHUSD), which are the most liquid crypto derivatives. Current borrow-carry is a useful but imprecise proxy.

### Live-Mode PostgreSQL Order Persistence (Deferred — N+3)

- Problem: `PostgreSQLOrderStorage` raises `NotImplementedError` for all 15 methods. Live trading uses in-memory fallback silently.
- Blocks: Any live deployment that must survive a process restart or reconcile the live order mirror with the exchange.

---

## Test Coverage Gaps

### Screeners Handler — No Unit or Integration Tests

- What's not tested: `ScreenersHandler.screen_markets`, `add_screener`, `init_screeners`, `get_screeners_universe`; the `VolumeSpyke` screener; the `Screener` base class.
- Files: `itrader/screeners_handler/screeners_handler.py`, `itrader/screeners_handler/screeners/volume_spyke.py`
- Risk: Regressions in the screener dispatch (TIME event → `screen_markets`) go undetected. The `init_screeners` wall-clock call also makes deterministic testing non-trivial.
- Priority: Medium (screener subsystem is deferred/inert in backtest; it is wired in the live path).

### `my_strategies/` — No Tests, Not mypy-Strict

- What's not tested: All strategies under `itrader/strategy_handler/my_strategies/` (Stoch RSI Keltner, ATR Hawkes, RSI scalping, VWAP/BB/RSI scalping, SuperSmoothed, SuperTrend, pair-strategy filters).
- Files: `itrader/strategy_handler/my_strategies/`
- Risk: These strategies use the old signal contract style and contain inline compliance logic that should be migrated to the engine's direction/admission model. Connecting any of them to a backtest run without testing is likely to produce silent incorrect behavior.
- Priority: High before any `my_strategies/` strategy is wired to a real run.

### Live Trading System — No Integration or E2E Tests

- What's not tested: `LiveTradingSystem.start()`, `stop()`, `_process_events()`, `_publish_and_continue` error policy; `TradingInterface.create_order()`, `cancel_order()`, `get_portfolio_status()`.
- Files: `itrader/trading_system/live_trading_system.py`, `itrader/trading_system/trading_interface.py`
- Risk: The live system's threading model, start/stop lifecycle, and continue-on-error policy are entirely untested. The `_publish_and_continue` error path is injected via `_on_handler_error = self._publish_and_continue` — a method-assign suppressed by `type: ignore[method-assign]` — which is also untested.
- Priority: High before any live deployment.

### Pair Strategy — Snapshot Generates-and-Passes on First Run

- What's not tested: `tests/integration/test_pair_flagship_snapshot.py:195-200` silently generates the baseline CSV on the first run and returns `pass`, so the first execution after wiping `tests/golden/pair/` is always green regardless of what the engine produces.
- Files: `tests/integration/test_pair_flagship_snapshot.py:195-200`
- Risk: Deleting `tests/golden/pair/` before a run corrupts the oracle silently — the next committed CSV reflects whatever the engine produced, not a hand-verified correct output.
- Priority: Low (the committed CSVs are the actual mitigation; risk only opens if the golden directory is wiped). Tracked as `IN-02` in `.planning/milestones/v1.4-phases/06-pair-trading-flagship/06-REVIEW.md`.

### `_coint_pvalue` OLS Slope — Cross-Platform Reproducibility is a Snapshot Limitation

- What's not tested: `EthBtcPairStrategy._coint_pvalue` uses `statsmodels.tsa.stattools.coint` and `sm.OLS`, whose numerical outputs may differ across OS/BLAS combinations. The pair flagship snapshot test asserts trade-count and column equality but does not assert specific PnL or trade prices to full Decimal precision. In-process determinism is proven; cross-platform is not.
- Files: `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:149-170`
- Risk: CI on a different OS (e.g. Linux ARM vs macOS x86) may see different cointegration p-values, leading to different entry signals, drifting the snapshot.
- Priority: Low (documented accepted limitation). Tracked as `CR-02 advisory` in the v1.4 milestone audit.

---

*Concerns audit: 2026-06-22*
