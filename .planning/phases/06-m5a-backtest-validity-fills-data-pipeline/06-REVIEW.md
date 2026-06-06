---
phase: 06-m5a-backtest-validity-fills-data-pipeline
reviewed: 2026-06-06T12:00:00Z
depth: standard
files_reviewed: 60
files_reviewed_list:
  - itrader/core/bar.py
  - itrader/events_handler/events/fill.py
  - itrader/events_handler/events/market.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/base.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/fee_model/__init__.py
  - itrader/execution_handler/fee_model/base.py
  - itrader/execution_handler/fee_model/maker_taker_fee_model.py
  - itrader/execution_handler/fee_model/percent_fee_model.py
  - itrader/execution_handler/fee_model/zero_fee_model.py
  - itrader/execution_handler/matching_engine.py
  - itrader/execution_handler/result_objects.py
  - itrader/execution_handler/slippage_model/base.py
  - itrader/execution_handler/slippage_model/fixed_slippage_model.py
  - itrader/execution_handler/slippage_model/linear_slippage_model.py
  - itrader/execution_handler/slippage_model/zero_slippage_model.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/price_handler/__init__.py
  - itrader/price_handler/feed/__init__.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/feed/base.py
  - itrader/price_handler/ingestion.py
  - itrader/price_handler/providers/__init__.py
  - itrader/price_handler/providers/base.py
  - itrader/price_handler/providers/binance_stream.py
  - itrader/price_handler/store/__init__.py
  - itrader/price_handler/store/base.py
  - itrader/price_handler/store/csv_store.py
  - itrader/reporting/statistics.py
  - itrader/screeners_handler/screeners_handler.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/dynamic.py
  - tests/conftest.py
  - tests/golden/REFREEZE-06-04.md
  - tests/golden/REFREEZE-M5A.md
  - tests/integration/test_execution_handler_routing.py
  - tests/unit/core/test_bar.py
  - tests/unit/events/test_bar_event_ohlc.py
  - tests/unit/events/test_event_immutability.py
  - tests/unit/events/test_events.py
  - tests/unit/execution/exchanges/test_simulated_exchange.py
  - tests/unit/execution/test_fee_models.py
  - tests/unit/execution/test_matching_engine.py
  - tests/unit/execution/test_slippage_models.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order.py
  - tests/unit/order/test_stop_limit_orders.py
  - tests/unit/portfolio/test_cash_reservations.py
  - tests/unit/portfolio/test_portfolio_update.py
  - tests/unit/price/test_bar_feed.py
  - tests/unit/price/test_csv_store.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 11
  info: 12
  total: 23
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-06-06 (re-reviewed after gap-closure wave — see Re-review note)
**Depth:** standard
**Files Reviewed:** 60
**Status:** issues_found

## Summary

Phase 06 (M5a — backtest validity, fills & data pipeline) was reviewed at standard depth:
the new Decimal `Bar` struct, the Provider/Store/Feed split, the look-ahead-safe
`BacktestBarFeed`, Decimal-native matching/fee/slippage, the next-bar-open fill flip in
`SimulatedExchange`/`MatchingEngine`, and the supporting tests + golden re-freeze notes.

The core deliverables are solid: the bar-timing contract math in `BacktestBarFeed.window`
(rule 3/4 cutoff) is correct and well regression-locked; the matching engine's
trigger/gap/OCO logic matches its documented semantics for the market-only golden path;
the Decimal money path holds end-to-end with deliberate identity normalizations; the two
golden re-freezes are properly documented and behavior-identity-checked.

One Critical defect was found in the matching engine's bracket handling (children can
fill while their parent entry has never filled — reachable through the public
limit/stop-primary + SL/TP signal path), plus a set of Warnings concentrated in the
exchange config plumbing, determinism seams, the off-by-one CSV date window, and the
dormant-but-importable reporting module.

**Re-review note (2026-06-06):** 4 files were re-reviewed at standard depth after the
gap-closure wave (commits `7e63dd3`..`dca839c`): `itrader/execution_handler/matching_engine.py`,
`itrader/portfolio_handler/portfolio_handler.py`, `tests/unit/execution/test_matching_engine.py`,
`tests/unit/portfolio/test_portfolio_update.py`. CR-01 and WR-06 are RESOLVED (verified
below). The two-pass parent-filled gate was traced through its edge cases — same-bar
limit/stop-parent unlock, OCO sibling arbitration, parents-before-children fill ordering,
cancelled-parent orphan handling (covered by the order-domain WR-05 cascade within one
tick drain), and book-mutation-during-iteration safety — and no new defects were found.
All 142 execution-unit + integration tests pass. No new findings; open totals drop to
0 critical / 11 warning / 12 info.

## Critical Issues

### CR-01: Bracket children can fill before (or without) their parent entry filling — unintended reverse positions

**Status: RESOLVED** (plan 06-07, commit fc65dd2)
Verified on re-review: `MatchingEngine.on_bar` now runs two passes — pass 1 fills
parents/standalone orders and pops them from the book; pass 2 skips any child whose
`parent_order_id` still keys `self._resting` (dormant: cannot fill, cannot OCO-cancel).
Four new regression tests (`test_limit_parent_resting_shields_children`,
`test_limit_parent_fill_same_bar_unlocks_children`,
`test_children_dormant_until_parent_triggers_then_work_later_bar`,
`test_stop_parent_resting_shields_children`) lock the defect; the accepted same-bar
market-parent rule and parents-before-children fill ordering are preserved by
construction (pass-1 fills precede pass-2 fills).

**File:** `itrader/execution_handler/matching_engine.py:178-267` (with `itrader/order_handler/order_manager.py:440-551`)
**Issue:** `OrderManager._assemble_bracket_and_emit` emits the parent AND its SL/TP
children immediately, and `SimulatedExchange.on_order` rests all of them in the book at
once. `MatchingEngine.on_bar` evaluates every resting order against the bar with **no
check that a bracket child's parent has filled**. For a MARKET parent this is safe (the
parent fills unconditionally at the first bar, ordered parents-before-children). But
`_build_primary_order` also supports LIMIT and STOP primaries with brackets
(`signal.order_type is OrderType.LIMIT` + `stop_loss`/`take_profit > 0`): a BUY-limit
entry at 95 with a TP SELL-limit at 110 will see the TP fill on a rally bar
(high ≥ 110) while the entry never triggered — the portfolio settles a SELL against a
flat book and silently **opens a short position** (confirmed portfolio semantics: a SELL
with no position opens a short, `tests/unit/portfolio/test_portfolio_update.py:40-66`).
Worse, the orphaned parent keeps resting and can fill later, now unprotected (its OCO
children were consumed). The same-bar-bracket-rule comment ("a parent market order
filling at this bar's open does NOT shield its children") only covers the market-parent
case; nothing enforces it.
**Fix:** Gate child evaluation on parent fill state. Minimal engine-level fix in
`MatchingEngine.on_bar` candidate collection:

```python
# 1. Collect candidate fills (price reached).
for order in list(self._resting.values()):
    # A bracket child is dormant until its parent has left the book
    # (parent filled/cancelled). A still-resting parent means no position
    # exists to protect — the child must not trigger.
    if (order.parent_order_id is not None
            and order.parent_order_id in self._resting):
        # exception: the parent is a MARKET order that fills THIS bar —
        # handle by evaluating parents first, then re-checking children
        # against the post-parent book.
        ...
```

Concretely: split `on_bar` into two passes — (1) evaluate and fill parents/standalone
orders, removing them from the book; (2) evaluate children only for brackets whose
parent is no longer resting (filled this bar or earlier). This preserves the accepted
same-bar rule for market parents while making a never-filled limit/stop parent shield
its children. Alternatively (order-domain fix): hold child OrderEvents in the
OrderManager until the parent's EXECUTED fill reconciles, and emit them then.

## Warnings

### WR-01: `SimulatedExchange.update_config` leaves fee/slippage models stale for several keys

**File:** `itrader/execution_handler/exchanges/simulated.py:572-578`
**Issue:** The rebuild triggers are `any(k.startswith('fee_'))` and
`any(k.startswith('slippage_'))`. `maker_rate` and `taker_rate` do not start with
`fee_`, and `base_slippage_pct` does not start with `slippage_` — so
`update_config(maker_rate=0.002)` or `update_config(base_slippage_pct=0.05)` mutates the
config object but the **active model keeps the old rates**. Fees/slippage silently
diverge from configuration. (The existing tests mask this by always passing
`*_model_type` together with the rate.)
**Fix:** Trigger on the explicit key sets:

```python
_FEE_KEYS = {'fee_model_type', 'fee_rate', 'maker_rate', 'taker_rate'}
_SLIPPAGE_KEYS = {'slippage_model_type', 'base_slippage_pct', 'slippage_pct'}
if _FEE_KEYS & kwargs.keys():
    self.fee_model = self._init_fee_model()
if _SLIPPAGE_KEYS & kwargs.keys():
    self.slippage_model = self._init_slippage_model()
```

### WR-02: `health_check` consumes the shared seeded RNG — monitoring perturbs determinism

**File:** `itrader/execution_handler/exchanges/simulated.py:363`
**Issue:** `latency_ms=self._rng.uniform(10, 50)` draws from the **same injected seeded
RNG** used for failure simulation (`_admit_order`) and slippage jitter (the engine
wiring shares one instance, per the constructor docstring). Any `health_check()` call —
e.g. from a status endpoint or monitoring loop — advances the RNG stream and changes
every subsequent failure/slippage draw, silently breaking the "runs must be
reproducible" determinism constraint.
**Fix:** Use a separate non-deterministic RNG (or a constant) for telemetry:
`latency_ms=25.0` or `self._telemetry_rng = random.Random()` kept distinct from the
deterministic `self._rng`.

### WR-03: Commission is computed on the pre-slippage price, not the executed notional

**File:** `itrader/execution_handler/exchanges/simulated.py:203-213`
**Issue:** `_emit_fill` calls `fee_model.calculate_fee(quantity=quantity, price=price, ...)`
with the raw matched `fill_price`, then computes `executed_price = price *
slippage_factor` afterwards. Real exchanges charge fees on the executed notional
(`executed_price * quantity`). With any non-zero slippage the commission is wrong by the
slippage factor. The golden run pins zero fee/zero slippage so the oracle is unaffected,
but any fee+slippage configuration produces systematically mispriced commissions.
**Fix:** Compute `executed_price` first and pass it to the fee model:

```python
executed_price = price if event.order_type is OrderType.LIMIT \
    else price * self.slippage_model.calculate_slippage_factor(...)
commission = self.fee_model.calculate_fee(
    quantity=quantity, price=executed_price, side=side,
    order_type=order_type, is_maker=is_maker)
```

### WR-04: CSV store date window is off-by-one — `.loc` slice includes the bar stamped `end_date + 1 day`

**File:** `itrader/price_handler/store/csv_store.py:179-181`
**Issue:** `end = pd.Timestamp(self.end_date, tz=TIMEZONE) + pd.Timedelta(days=1)` then
`data.loc[start:end]`. Pandas label slicing is **inclusive of both endpoints**, so a bar
stamped exactly `end_date + 1d 00:00` (i.e. the full bar of the day AFTER the documented
inclusive end) is included. The pin exists precisely to insulate the oracle "if the CSV
is ever regenerated" — but a regenerated CSV containing a `2026-06-04` bar would leak
exactly one extra bar into the frozen window, shifting the equity grid and the last-bar
edge silently. The same defect leaks one extra bar for any intraday dataset.
**Fix:** Make the upper bound exclusive:

```python
end_excl = pd.Timestamp(self.end_date, tz=TIMEZONE) + pd.Timedelta(days=1)
data = data[(data.index >= start) & (data.index < end_excl)]
```

### WR-05: Position mark-to-market timestamps use the wall clock, not the bar time; the bar-time path is dead code

**File:** `itrader/portfolio_handler/portfolio.py:436-442` (and `itrader/portfolio_handler/portfolio_handler.py:327-353`)
**Issue:** The live BAR route is `update_portfolios_market_value(bar_event)` →
`portfolio.update_market_value_of_portfolio(prices)` which discards `bar_event.time` and
stamps every position update with `datetime.now(UTC)` — twice (`update_position_market_values`
timestamp and `_last_activity`). This violates the project's own event-derived-timestamp
rule (D-12, enforced everywhere else this phase) and the injected-clock determinism
constraint; position `current_time`/audit timestamps become non-reproducible.
Meanwhile `Portfolio.update_market_value(bar_event)` — which correctly uses
`bar_event.time` — is called from nowhere.
**Fix:** Thread the event time through the routed path:

```python
# PortfolioHandler.update_portfolios_market_value
portfolio.update_market_value_of_portfolio(prices, bar_event.time)
# Portfolio
def update_market_value_of_portfolio(self, prices, time: datetime) -> None:
    self.position_manager.update_position_market_values(prices, time)
    self._last_activity = time
```
and delete the unused `update_market_value`.

### WR-06: `PortfolioHandler.update_portfolios_market` reads a nonexistent `close_price` field — dead and broken

**Status: RESOLVED** (plan 06-08, commit dca839c)
Verified on re-review: the method is deleted; grep confirms no remaining callers anywhere
in `itrader/` or `tests/` (only the correct `update_portfolios_market_value` survives,
wired in `full_event_handler.py:71`), and the colliding test was renamed to
`test_update_portfolios_market_value`.

**File:** `itrader/portfolio_handler/portfolio_handler.py:355-377`
**Issue:** The "backward compatible" method extracts prices via
`getattr(bar, 'close_price', None)` — the M5-02 `Bar` struct has `close`, not
`close_price`, so every price resolves to `None`; if ever called it would feed `None`
prices into `update_current_price_time`. No production or test caller exists (verified
by grep). Dead code that actively encodes the pre-M5 payload shape.
**Fix:** Delete the method (or fix to `bar.close` if a legacy caller is expected).

### WR-07: `activate_screener`/`deactivate_screener` index guard is off by one — index 0 toggles the LAST screener

**File:** `itrader/screeners_handler/screeners_handler.py:117-140`
**Issue:** The guard `0 <= screener_index <= len(self.screeners)` accepts `0`, but the
body indexes `self.screeners[screener_index - 1]` (1-based) — so `screener_index=0`
resolves to `self.screeners[-1]` and silently toggles the **last** screener while
logging "Screener 0 activated." A 1-based API must reject 0.
**Fix:** `if 1 <= screener_index <= len(self.screeners):` in both methods. Also note
`deactivate_screener` computes an unused `length` local.

### WR-08: `StatisticsReporting` is broken on every public path yet reachable from `run(print_summary=True)` and `LiveTradingSystem.get_statistics`

**File:** `itrader/reporting/statistics.py:72,91,147,240-258` (and `itrader/trading_system/backtest_trading_system.py:182-187`)
**Issue:** Multiple independent defects in one module:
- `_prepare_data` reads `portfolio.metrics` — `Portfolio` has no such attribute
  (verified; it has `metrics_manager`/`record_metrics`) → `AttributeError` on every
  `print_summary`/`plot_charts`/`plot_signals` call.
- `_equity_statistics` uses `df['cum_returns'][-1]` — positional `[-1]` on a
  non-integer index is deprecated in pandas 2.x (FutureWarning; removed in 3.0) and
  fails any test under `filterwarnings=["error"]`. Use `.iloc[-1]`.
- `_temporal_statistics` checks `x is np.nan` — `np.mean(...)` returns a fresh float64
  NaN, never the `np.nan` singleton, so the 0-substitution never fires. Use `np.isnan`.
- `_to_sql` references `self.engine`, `self.meta`, `self._get_positions` — none exist —
  and uses the SQLAlchemy 1.x `engine.execute` API removed in SQLAlchemy 2.0 (pinned
  2.0.50).
- `_trade_statistics`/`_prepare_data` divide by `df.shape[0]` and access
  `positions.total_sold` — a zero-trade run raises before any guard.
- `TradingSystem.run(print_summary=True)` calls `calculate_statistics()` with no
  arguments although the signature requires `(positions, equity_metrics)` → immediate
  `TypeError`. The known-broken state is documented in a comment, but the parameter
  remains a public, crashing API.
**Fix:** Either quarantine the module the same way providers/sql_store were (and remove
the `print_summary` parameter until reporting is rebuilt), or fix `_prepare_data` to
read `portfolio.metrics_manager` snapshots and repair the items above.

### WR-09: `OrderManager.on_fill` swallows all reconciliation exceptions — mirror desync continues silently

**File:** `itrader/order_handler/order_manager.py:185-187`
**Issue:** The entire reconciliation body is wrapped in `except Exception as e:
self.logger.error(...)` with no re-raise. The backtest policy elsewhere is fail-fast
(`_on_handler_error` re-raises so "a handler failure must abort the run rather than
silently corrupt state", T-04-15) — but a failure inside mirror reconciliation (storage
error, bad state transition, release failure) is logged and the run continues with the
order mirror permanently desynced from exchange truth, exactly the corrupted-state
outcome the fail-fast seam exists to prevent.
**Fix:** Narrow the try to the WR-05 orphan-cancel block (which is genuinely best-effort)
and let core reconciliation exceptions propagate to the dispatcher's policy seam, or
re-raise after logging in backtest mode.

### WR-10: `market_execution` parameter is dead and its documented semantics no longer exist

**File:** `itrader/order_handler/order_manager.py:45,63-66,80` (and `itrader/order_handler/order_handler.py:40,52-57,63`)
**Issue:** After the D-13 single-matching-path flip, market orders ALWAYS rest and fill
next-bar-open. `market_execution` is stored and logged but read nowhere
(verified by grep), yet both docstrings still promise `"immediate": Execute market
orders immediately (live trading)` — a behavior that was deleted this phase. A future
maintainer (or live wiring) configuring `"immediate"` will get silently different
behavior than documented.
**Fix:** Remove the parameter and its docstrings from both classes (and the two
constructor call sites in tests), or replace the docstring with "retained for API
compatibility; has no effect since D-13 (next-bar-open is the only fill path)".

### WR-11: A next-open gap-up beyond the 5% sizing buffer aborts the entire backtest instead of rejecting the order

**File:** `itrader/order_handler/order_manager.py:627-629` (with `itrader/portfolio_handler/portfolio.py:307-309`)
**Issue:** Entry sizing reserves `0.95 * available_cash` at the decision close; the fill
settles at the next bar's open. The settlement funds invariant checks the ledger
balance, so the run tolerates a gap up to ~+5.26% (`1/0.95`). Beyond that,
`assert_funds_invariant` raises `InsufficientFundsError`, which propagates through the
fail-fast seam and **aborts the whole run** mid-stream — not a rejected order, not a
smaller fill. The REFREEZE-M5A note records trade 122 entering at +4.25% above its
estimate — uncomfortably close to the hard 5.26% cliff on real data. The A4 assumption
("holds empirically") is dataset-dependent, not structural.
**Fix:** Decide and encode the policy explicitly: either (a) clamp the fill-time debit by
re-sizing the quantity down to available balance at settlement (a real-exchange
semantic), or (b) catch `InsufficientFundsError` at the FILL boundary and reconcile the
order REJECTED with an ErrorEvent, keeping the run alive. At minimum document the cliff
next to the `0.95` constant so the buffer and the invariant are visibly coupled.

### WR-12: Live event loop catch-and-continue leaves events half-processed (no live `_on_handler_error` override)

**File:** `itrader/trading_system/live_trading_system.py:242-286` (with `itrader/events_handler/full_event_handler.py:120-141`)
**Issue:** `_dispatch`'s `_on_handler_error` re-raises (backtest policy). The documented
live design is to override that method with publish-and-continue; `LiveTradingSystem`
never overrides it — instead the processing loop catches `Exception` and `continue`s.
The difference matters: when handler 1 of an event fails (e.g. `portfolio_handler.on_fill`
raises after settling cash), the re-raise unwinds out of `_dispatch`, so handler 2
(`order_handler.on_fill` mirror reconciliation) **never runs for that event** — the
loop then continues with the portfolio and order mirror permanently inconsistent.
Live mode is deferred (D-live), but this file ships and starts a thread today.
**Fix:** Implement the documented seam: subclass/override `_on_handler_error` for live to
publish an `ErrorEvent` and continue, so per-handler failures don't skip sibling
handlers; keep the loop-level catch only as a last-resort guard.

## Info

### IN-01: `BarFeed.window` has no guard for `timeframe < base_timeframe`

**File:** `itrader/price_handler/feed/bar_feed.py:250-254`
**Issue:** With e.g. a 4h timeframe on a 1d store, `cutoff = asof - tf + base` lies in
the FUTURE (`asof + 20h`); the upsampled resample produces mostly-NaN rows, and
future-stamped all-NaN buckets enter the window. No data leak (rows are NaN), but the
window silently degrades instead of failing loudly (FR7 spirit).
**Fix:** Raise `ValueError` in `window`/`precompute` when `timeframe < self._base_timeframe`.

### IN-02: `CsvPriceStore.read_bars` returns the internal mutable frame reference

**File:** `itrader/price_handler/store/csv_store.py:90-94`
**Issue:** Callers receive the store's own `pd.DataFrame`; any in-place mutation (a
strategy editing its window's parent, a feed normalization) would corrupt the canonical
store for the rest of the run. The read-only contract is convention-only.
**Fix:** Return a defensive copy, or document the no-mutation contract on `PriceStore.read_bars`.

### IN-03: `MatchingEngine.on_bar` silently skips malformed resting orders

**File:** `itrader/execution_handler/matching_engine.py:199-205`
**Issue:** `except (TypeError, ValueError, KeyError): continue` drops a malformed order's
evaluation with no logging and no removal — the order is retried (and re-skipped) every
bar forever. The module is intentionally log-free, but a permanently-skipped order is
invisible.
**Fix:** Collect skipped order ids and return/expose them so the exchange can log once,
or remove the order from the book on a malformed evaluation.

### IN-04: Quarantined `binance_stream` references undefined attributes

**File:** `itrader/price_handler/providers/binance_stream.py:94,164,183,203-205`
**Issue:** `self.symbols`, `self.timeframe`, `self.prices`, and `self.time` (read in
`_on_message` before `_store_bar` ever sets it) are never initialized — every live
method would raise `AttributeError`. Documented as quarantined D-live; noted for the
record so the rebuild starts from the contract, not this code.
**Fix:** None required now; covered by D-live.

### IN-05: Fee vs slippage `validate_inputs` contracts are inconsistent

**File:** `itrader/execution_handler/fee_model/base.py:58-65` (vs `slippage_model/base.py:104-111`)
**Issue:** FeeModel validates `side` case-sensitively (`side not in ("buy", "sell")`)
while SlippageModel lowercases; FeeModel allows `int` quantity but requires `Decimal`
price. Harmless today (the exchange lowercases at the boundary) but the two "unified"
ABCs drift.
**Fix:** Align both: lowercase side in FeeModel; pick one quantity type rule.

### IN-06: Events do not enforce their Decimal money contract — tests construct float-money events

**File:** `tests/integration/test_execution_handler_routing.py:22-26`, `tests/unit/execution/exchanges/test_simulated_exchange.py:203-216`, `tests/unit/order/test_order_manager.py:91-96`
**Issue:** `OrderEvent`/`FillEvent` declare `Decimal` fields but perform no construction
normalization, and multiple tests pass `price=40.0`, `quantity=1.0`, `order_id=1`
(int, not OrderId UUID). The float-money correctness rule is upheld only because
production factories normalize; the test suite legitimizes float money on events, which
weakens the regression net for the "no float money" definition of done.
**Fix:** Either add `__post_init__` `to_money` normalization to money-carrying events, or
sweep test constructors to `Decimal(str(x))` (the harness in the same file already does).

### IN-07: Backtest tick grid is derived from the first store symbol only

**File:** `itrader/trading_system/backtest_trading_system.py:140-141`
**Issue:** `set_dates(self.store.index(self.store.symbols()[0]))` — fine for the
single-symbol golden run, but with a multi-symbol store the ping grid is whichever
symbol happens to be first in dict order; other symbols' bars off that grid never tick.
**Fix:** Union the indexes across `store.symbols()` (or assert single-symbol until
multi-symbol is in scope).

### IN-08: `ScreenersHandler.screen_markets` dead intermediate write; `assign_symbol` hardcodes `strategies[0]`

**File:** `itrader/screeners_handler/screeners_handler.py:83-92`, `itrader/strategy_handler/strategies_handler.py:77-94`
**Issue:** Inside the loop `self.last_results[event.time] = {}` is written and then the
whole dict is replaced after the loop — dead store. `assign_symbol` operates only on
`self.strategies[0]` and reads a `settings` attribute not on the base class (marked
TEMPORARY). Both are deferred-subsystem (D-screener) code kept importable.
**Fix:** Remove the dead write; leave the rest to D-screener.

### IN-09: `test_order.py` has an unreachable/unbound assertion in an except branch

**File:** `tests/unit/order/test_order.py:233-239`
**Issue:** In `test_order_comparison_and_sorting`, the `except TypeError:` branch
executes `pass` then `assert sorted_orders[0]...` — if the except is ever taken,
`sorted_orders` is unbound (`NameError`), and the indentation suggests the assert was
meant for the try branch. Latent test bug.
**Fix:** Move the assertion into the `try` block after `sorted(...)`.

### IN-10: Cancel acknowledgements are stamped with the order's creation time

**File:** `itrader/execution_handler/exchanges/simulated.py:267-276` (with `events_handler/events/fill.py:129-130`)
**Issue:** The CANCEL-command acknowledgement `FillEvent.new_fill('CANCELLED', event, ...)`
omits `time`, so it defaults to `order.time` — the order's original decision/creation
time. A cancel issued bars later is back-dated in the audit trail. (OCO cancels in
`on_market_data` correctly pass `bar.time`.)
**Fix:** The exchange does not know "now" without a clock; either thread the injected
clock into the exchange or document that admission-time outcomes inherit the
instruction's event time. For CANCEL commands, the CANCEL OrderEvent could carry the
cancel-decision time instead of the entity's creation time
(`OrderEvent.new_order_event` uses `order.time`).

### IN-11: `reporting/statistics.py` pulls SQLAlchemy onto the backtest import path

**File:** `itrader/reporting/statistics.py:16-18` (imported by `backtest_trading_system.py:20`)
**Issue:** The phase deliberately quarantined heavy/optional deps (sql_store, providers)
out of run-path imports, but `statistics.py` imports `sqlalchemy` at module level and is
imported unconditionally by both trading systems — so every backtest import still drags
sqlalchemy (and would break if it became optional).
**Fix:** Move the sqlalchemy imports inside `_to_sql` (which is broken anyway, WR-08), or
quarantine the module like the others.

### IN-12: No coordination between a strategy exit SELL and resting SL/TP children — double-exit can open a short

**File:** `itrader/order_handler/order_manager.py:553-629`
**Issue:** A SELL exit is sized to the position's full `net_quantity`, but any resting
SL/TP children from the entry bracket are left in the exchange book; if price later
crosses them after the exit settles, they fill against a flat portfolio and open a
short. Not reachable in the golden run (`sl=0, tp=0`) and position-exit coordination is
explicitly M5b risk-layer scope — recorded so it is not lost.
**Fix:** Defer to Phase 7 (M5b): cancel a position's bracket children when an exit order
for that position is admitted/filled.

---

_Reviewed: 2026-06-06 (re-review of 4 gap-closure files: same date)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
