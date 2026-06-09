---
phase: 04-m3-event-dispatch-core
reviewed: 2026-06-05T12:00:00Z
depth: standard
files_reviewed: 57
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/core/enums/__init__.py
  - itrader/core/enums/event.py
  - itrader/core/enums/order.py
  - itrader/core/exceptions/__init__.py
  - itrader/core/exceptions/base.py
  - itrader/core/exceptions/data.py
  - itrader/core/exceptions/order.py
  - itrader/core/exceptions/portfolio.py
  - itrader/core/ids.py
  - itrader/events_handler/events/__init__.py
  - itrader/events_handler/events/base.py
  - itrader/events_handler/events/error.py
  - itrader/events_handler/events/fill.py
  - itrader/events_handler/events/market.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/signal.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/matching_engine.py
  - itrader/logger.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/order.py
  - itrader/order_handler/storage/storage_factory.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/transaction/transaction_manager.py
  - itrader/portfolio_handler/transaction/transaction.py
  - itrader/price_handler/data_provider.py
  - itrader/price_handler/live_streaming/BINANCE_Live.py
  - itrader/reporting/plots.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/position_sizer/variable_sizer.py
  - itrader/strategy_handler/risk_manager/advanced_risk_manager.py
  - itrader/strategy_handler/sltp_models/sltp_models.py
  - itrader/strategy_handler/SMA_MACD_strategy.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/simulation/time_generator.py
  - itrader/trading_system/trading_interface.py
  - itrader/universe/dynamic.py
  - itrader/universe/universe.py
  - tests/unit/core/test_exceptions.py
  - tests/unit/core/test_logger_config.py
  - tests/unit/events/test_dispatch_registry.py
  - tests/unit/events/test_error_flow.py
  - tests/unit/events/test_event_immutability.py
  - tests/unit/events/test_events.py
  - tests/unit/events/test_fill_event_schema.py
  - tests/unit/execution/test_matching_engine.py
  - tests/unit/order/test_on_signal.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/order/test_order_validator.py
  - tests/unit/order/test_order.py
  - tests/unit/portfolio/test_transaction_manager.py
  - tests/unit/portfolio/transaction/test_transaction_init.py
findings:
  critical: 4
  warning: 13
  info: 11
  total: 28
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-05T12:00:00Z
**Depth:** standard
**Files Reviewed:** 57
**Status:** issues_found

## Summary

Standard-depth adversarial review of the M3 event/dispatch core rebuild: frozen event dataclasses, routing-registry dispatcher, exception hierarchy, UUIDv7 IDs, env-driven structlog, plus the surrounding handler/manager files touched at the cutover. The core event package, dispatcher, matching engine, and exception hierarchy are solid — the dispatch registry, drain semantics, fail-fast seam, and OCO matching all hold up under tracing, and the new test suites lock the contracts well.

The defects cluster at the edges of the cutover: the live-mode files were touched for event-API conformance but contain four outright crashes/correctness breaks (an `ImportError` module, a `TypeError` on every `TradingInterface` construction, FIFO-order corruption in the live event loop, and an `AttributeError` swallowed every TIME event). On the backtest path, fill-reconciliation ignores the fill's own quantity, `BarEvent.get_last_close` is API-inconsistent with its siblings, and the universe can emit `None` bars that crash downstream consumers.

## Narrative Findings (AI reviewer)

### Critical Issues

#### CR-01: TradingInterface crashes at construction — get_itrader_logger() takes no arguments

**File:** `itrader/trading_system/trading_interface.py:39`
**Issue:** `self.logger = get_itrader_logger(__name__)` — `get_itrader_logger()` (itrader/logger.py:230) takes zero arguments. Every `TradingInterface(...)` instantiation raises `TypeError: get_itrader_logger() takes 0 positional arguments but 1 was given`. The class is unusable; nothing in this file can ever run. No test covers this file, so the break is silent.
**Fix:**
```python
self.logger = get_itrader_logger().bind(component="TradingInterface")
```

#### CR-02: BINANCE_Live.py cannot be imported — `PriceHandler` does not exist in `price_handler/base.py`

**File:** `itrader/price_handler/live_streaming/BINANCE_Live.py:9`
**Issue:** `from ..base import PriceHandler` — `itrader/price_handler/base.py` defines only `AbstractPriceHandler` (a `Protocol`). Importing this module raises `ImportError` unconditionally. Even if the import were fixed, the module is broken throughout: it subclasses a Protocol and reads class-level state that does not exist (`PriceHandler.prices` at line 180, `PriceHandler.symbols`/`PriceHandler.timeframe` at lines 200-202), references `self.symbols` (line 92) which is never initialized, and the `TimeEvent(time=self.time)` path (line 109) reads `self.time`, which is only set after `_store_bar` has run at least once — `AttributeError` if the ping path fires first. This file was updated this phase (the `TimeEvent` keyword-form construction) without ever being import-checked.
**Fix:** Either fix the base import to `AbstractPriceHandler` and rework the class-attribute access to instance state, or explicitly quarantine/delete the module until D-live. At minimum:
```python
from ..base import AbstractPriceHandler

class BINANCELiveStreamer(AbstractPriceHandler):
    def __init__(self, global_queue=None):
        ...
        self.symbols: list[str] = []
        self.prices: dict[str, pd.DataFrame] = {}
        self.time = None
```
and add an import smoke test (`importlib.import_module`) so dead modules cannot silently rot.

#### CR-03: Live event loop destroys FIFO ordering and leaks queue task accounting

**File:** `itrader/trading_system/live_trading_system.py:216-230`
**Issue:** The loop does `event = self.global_queue.get(timeout=...)` then `self.global_queue.put(event)  # Put it back for processing` before calling `process_events()`. If any other events arrived between the original enqueue and this re-put (normal under load — the producer is the websocket thread), the dequeued event is re-enqueued *behind* them: a BAR can be processed after a FILL that causally followed it, violating the single-FIFO-causality invariant the whole architecture is built on. Separately, the re-put inflates `Queue.unfinished_tasks` by one per cycle (one `put` from the producer + one re-`put` here, but only one `task_done()` at line 230, and `process_events()` drains via `get_nowait()` with no `task_done()` calls) — any future `queue.join()` will hang forever.
**Fix:** Drop the get/re-put dance entirely; the drain already handles everything:
```python
try:
    event = self.global_queue.get(timeout=self.queue_timeout)
except queue.Empty:
    ...idle handling...
    continue
self.event_handler._dispatch(event)      # process THIS event first
self.event_handler.process_events()      # then drain whatever it produced
self.global_queue.task_done()
```

#### CR-04: Live TIME-event metrics call a method that does not exist — AttributeError swallowed every tick

**File:** `itrader/trading_system/live_trading_system.py:228`
**Issue:** `self.portfolio_handler.record_metrics(event.time)` — `PortfolioHandler` has no `record_metrics` method; it lives on `Portfolio` (itrader/portfolio_handler/portfolio.py:324). Every TIME event in live mode raises `AttributeError`, which the blanket `except Exception` at line 243 catches and counts, then continues. Result: portfolio metrics are never recorded in live mode and `errors_count` climbs silently — a defect class the fail-fast seam (D-16) was specifically designed to kill. Compare the backtest loop, which correctly iterates portfolios (`backtest_trading_system.py:127-128`).
**Fix:**
```python
if hasattr(event, 'type') and event.type == EventType.TIME:
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)
```

### Warnings

#### WR-01: Fill reconciliation ignores the fill's own quantity — partial fills corrupt the order mirror

**File:** `itrader/order_handler/order_manager.py:84-87`
**Issue:** `on_fill` EXECUTED branch calls `order.add_fill(order.remaining_quantity, ...)` — the `FillEvent.quantity` field (the exchange's execution truth, D-12) is never read. `SimulatedExchange._emit_fill` explicitly documents that the matched fill quantity "may differ from event.quantity for partial fills driven by the matching engine". The moment any partial fill is emitted, the mirror marks the order fully FILLED and deactivates it, desynchronizing mirror from exchange truth.
**Fix:**
```python
if not order.add_fill(to_money(fill_event.quantity), to_money(fill_event.price),
                      fill_event.time, "exchange fill"):
```
and only `deactivate_order` when `order.is_fully_filled`.

#### WR-02: `_resolve_signal_quantity` dereferences a possibly-None portfolio_handler

**File:** `itrader/order_handler/order_manager.py:441`
**Issue:** `portfolio = self.portfolio_handler.get_portfolio(...)` with no None guard. The constructor explicitly allows `portfolio_handler=None` (line 42), and the sibling `_get_signal_exchange` (line 236) does guard it. Any unsized signal processed by an OrderManager built without a portfolio handler raises `AttributeError` instead of a clean failure result.
**Fix:** Guard before sizing:
```python
if self.portfolio_handler is None:
    return OperationResult.failure_result(
        "Cannot size order: no portfolio handler configured",
        operation_type="create_primary_order")
```

#### WR-03: on_fill applies storage updates even when the state transition was rejected

**File:** `itrader/order_handler/order_manager.py:89-100`
**Issue:** The CANCELLED branch ignores `order.cancel_order(...)`'s bool return and the REFUSED branch ignores `order.reject_order(...)`'s return. When the transition is invalid (e.g. order already terminal — `add_state_change` returns False), the code still runs `update_order` + `deactivate_order`, and `reject_order` has already mutated `rejection_reason` on an order it failed to transition. The trailing comment ("Only reached for an applied EXECUTED or CANCELLED reconciliation") is also wrong — REFUSED reaches it too.
**Fix:** Check the returns the same way the EXECUTED branch checks `add_fill`; warn and return without touching storage when the transition is rejected. Fix the stale comment.

#### WR-04: BarEvent.get_last_close lacks the missing-ticker guard its siblings have

**File:** `itrader/events_handler/events/market.py:58-59`
**Issue:** `get_last_open/high/low` all start with `if ticker not in self.bars: return None`; `get_last_close` goes straight to `self.bars[ticker]['close']` and raises `KeyError`. Callers include `Strategy._generate_signal` (strategy_handler/base.py:78) and `PortfolioHandler.update_portfolios_market_value` — the strategy path crashes if a subscribed ticker is absent from a bar. Inconsistent API on the same class.
**Fix:** Add the same guard (returning `Optional[float]`) or make all four raise consistently — pick one contract.

#### WR-05: DynamicUniverse stores None bars into BarEvent — downstream `None['close']` crash

**File:** `itrader/universe/dynamic.py:71-73`
**Issue:** `self.price_handler.get_bar(ticker, time)` returns `None` when the timestamp is missing (data_provider.py:273), but the result is unconditionally stored: `bars[ticker] = bar`. Every consumer that indexes `bars[ticker]['close']` (get_last_close, matching engine via get_last_open) then hits `TypeError: 'NoneType' object is not subscriptable`. A single missing bar for one ticker crashes the run (fail-fast dispatcher) with a misleading TypeError instead of a clean skip or a domain error.
**Fix:**
```python
bar = self.price_handler.get_bar(ticker, time_event.time)
if bar is None:
    self.logger.warning('No bar for %s at %s — skipped', ticker, time_event.time)
    continue
bars[ticker] = bar
```

#### WR-06: PortfolioHandler.max_portfolios is wired to limits.max_positions — wrong config knob

**File:** `itrader/portfolio_handler/portfolio_handler.py:58` (also 417, 441)
**Issue:** `self.max_portfolios = self.config_data.limits.max_positions` — `max_positions` is the per-portfolio open-position limit, not a portfolio-count limit. The portfolio-creation gate (`add_portfolio`, line 155) then enforces "max open positions per portfolio" as "max number of portfolios". The same conflation is repeated in `update_config` and `rollback_config`.
**Fix:** Add a dedicated `max_portfolios` config field (or a sane constant) and stop reading `limits.max_positions` for collection sizing.

#### WR-07: SimulatedExchange.update_config silently fails to rebuild models for several keys

**File:** `itrader/execution_handler/exchanges/simulated.py:583-586`
**Issue:** Model re-initialization triggers on `k.startswith('fee_')` / `k.startswith('slippage_')`. `maker_rate` and `taker_rate` do not start with `fee_`, and `base_slippage_pct` does not start with `slippage_`, yet all three are accepted config keys (lines 563-566). Updating them mutates `self.config` but leaves the live fee/slippage model running with stale parameters — config and behavior silently diverge.
**Fix:** Trigger rebuilds from the explicit key sets already in `config_mapping`:
```python
fee_keys = {'fee_model_type', 'fee_rate', 'maker_rate', 'taker_rate'}
slip_keys = {'slippage_model_type', 'base_slippage_pct', 'slippage_pct'}
if fee_keys & kwargs.keys():
    self.fee_model = self._init_fee_model()
if slip_keys & kwargs.keys():
    self.slippage_model = self._init_slippage_model()
```

#### WR-08: Invalid ITRADER_LOG_LEVEL crashes `import itrader` with a raw ValueError

**File:** `itrader/logger.py:136` (via `_env_log_level`, line 34)
**Issue:** `root_logger.setLevel(log_level.upper())` — `_env_log_level()` returns the env value unvalidated, and `init_logger()` runs at `import itrader` time. `ITRADER_LOG_LEVEL=verbose` (or any typo) makes every import of the package die with `ValueError: Unknown level: 'VERBOSE'`. Unvalidated external input crashing at import time contradicts the file's own careful import-safety design (Pitfall 8 handling).
**Fix:** Validate and fall back:
```python
level = log_level.upper()
if level not in logging.getLevelNamesMapping():
    level = "INFO"
root_logger.setLevel(level)
```

#### WR-09: Hardcoded database credentials in the live DB URL fallback

**File:** `itrader/trading_system/live_trading_system.py:27-29`
**Issue:** `_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "postgresql+psycopg2://postgres:1234@localhost:5432/.......")` — a hardcoded username/password fallback in source. Even as a dev placeholder, it's a credentials-in-code pattern, and the silent fallback means a misconfigured deployment connects (or fails confusingly) against a bogus default instead of failing loudly.
**Fix:** No default — fail loudly when live storage is requested without `SYSTEM_DB_URL` set:
```python
_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL")  # None -> ConfigurationError at factory
```

#### WR-10: process_transaction's documented `False` return path is unreachable dead code

**File:** `itrader/portfolio_handler/transaction/transaction_manager.py:136-138, 292-308`
**Issue:** The `except` block calls `self._handle_transaction_error(...)`, which ends with a bare `raise` — it always re-raises. The subsequent `return False` is unreachable, so `process_transaction` never returns False despite its docstring contract ("True if successful, False otherwise"); every failure propagates as an exception. Callers written against the bool contract are wrong by construction. Additionally, if `TransactionContext(...)` construction itself ever raised, `context` would be unbound and the handler call would raise `NameError`, masking the original error.
**Fix:** Decide the contract: either remove the re-raise from `_handle_transaction_error` (return False as documented) or delete the dead `return False` and fix the docstring to "raises on failure". Initialize `context = None` before the `try` and guard the error handler.

#### WR-11: TradingInterface market orders carry price=0.0 and are refused by exchange validation

**File:** `itrader/trading_system/trading_interface.py:79`
**Issue:** `price=0.0,  # Market order - price will be determined by execution` — but `SimulatedExchange.validate_order` rejects `event.price <= 0` ("Order price must be positive", simulated.py:393), so every market order created through this interface is REFUSED at the exchange. The 0-price sentinel contradicts the execution layer's validation contract; the same sentinel pattern (0 meaning "unset") was deliberately killed for quantity in D-10.
**Fix:** Either resolve a reference price (last close) at creation, or make the exchange's price validation conditional on `order_type != OrderType.MARKET` — and align the two layers explicitly.

#### WR-12: DynamicSizer divides by zero / sizes negative when positions are at or above max

**File:** `itrader/strategy_handler/position_sizer/variable_sizer.py:52-53`
**Issue:** `available_pos = (max_positions - len(open_tickers))` then `1 / available_pos`. When the portfolio already holds `max_positions` open tickers, this is `ZeroDivisionError`; above it, the computed quantity is negative and is returned as a valid size. No guard exists.
**Fix:**
```python
available_pos = max_positions - len(open_tickers)
if available_pos <= 0:
    self.logger.warning('No position slots available for %s', ticker)
    return 0.0
```

#### WR-13: Bare `except:` clauses swallow everything in PriceHandler accessors

**File:** `itrader/price_handler/data_provider.py:245, 271`
**Issue:** `get_last_close` and `get_bar` use bare `except:` — catching `KeyboardInterrupt`, `SystemExit`, and masking genuine programming errors as "Price data not found". `get_last_close` also falls off the end (implicit `None` return) when the ticker is missing, while logging an error — three different failure shapes for one method.
**Fix:** Catch `(KeyError, IndexError)` explicitly and return `None` consistently in both branches.

### Info

#### IN-01: FillId NewType is exported but never used; FillEvent.fill_id typed as plain uuid.UUID

**File:** `itrader/core/ids.py:23`, `itrader/events_handler/events/fill.py:61`
**Issue:** `FillId` exists for exactly this field, yet `fill_id: uuid.UUID` bypasses it — the nominal-typing benefit (D-12) is lost for fills, and the export is dead.
**Fix:** Type the field `fill_id: FillId` and wrap generation: `fill_id=FillId(uuid_compat.uuid7())`.

#### IN-02: Mutable default argument in SMA_MACD_strategy

**File:** `itrader/strategy_handler/SMA_MACD_strategy.py:21`
**Issue:** `tickers: list[str] = []` — the classic shared-mutable-default; all default-constructed instances share one list (`self.tickers = tickers` aliases it in the base).
**Fix:** `tickers: Optional[list[str]] = None` then `tickers or []`.

#### IN-03: Broken assertion inside an except branch in test_order.py

**File:** `tests/unit/order/test_order.py:237-241`
**Issue:** The `except TypeError:` block has `pass` followed by `assert sorted_orders[0].time <= sorted_orders[1].time` — if the except ever triggers, `sorted_orders` is unbound and the test dies with `NameError` instead of the intended tolerance. Currently dead (UUIDs sort fine) but it's a trap.
**Fix:** Delete the stray assert (or move it into the try).

#### IN-04: Wall-clock timestamps remain on engine-adjacent paths

**File:** `itrader/portfolio_handler/cash/cash_manager.py:504,510`; `itrader/portfolio_handler/transaction/transaction_manager.py:90,98-99`; `itrader/execution_handler/exchanges/simulated.py:112`
**Issue:** Cash-operation IDs/timestamps, transaction correlation IDs/contexts, and `execute_order`'s `execution_time` all use `datetime.now()`. Result-bearing values are event-derived (good), but the audit trail itself is non-reproducible run-to-run — at odds with the determinism constraint's spirit and the D-09/D-10 clock seam staged in the backtest system.
**Fix:** Thread the injected clock (or the transaction/fill event time) into these audit stamps when the clock consumer wiring lands.

#### IN-05: FixedPercentage rounds SL but not TP

**File:** `itrader/strategy_handler/sltp_models/sltp_models.py:43,71`
**Issue:** `calculate_sl` returns `round(..., 5)`; `calculate_tp` returns the raw float. Asymmetric precision for two halves of the same bracket.
**Fix:** Apply the same rounding (or none) to both.

#### IN-06: Order.modify_order returns False for a no-op modification, reported as failure

**File:** `itrader/order_handler/order.py:502`, `itrader/order_handler/order_manager.py:529-533`
**Issue:** Modifying an order with values equal to current ones returns `False`, which `OrderManager.modify_order` translates into "Failed to modify order" — an idempotent no-change request is indistinguishable from a real failure.
**Fix:** Distinguish "no change" (success, no event) from "invalid modification" in the return contract.

#### IN-07: Bare `Event` is instantiable but has no `type` attribute — dispatch AttributeError

**File:** `itrader/events_handler/events/base.py:38`
**Issue:** `type: EventType = field(init=False)` with no default: `Event(time=...)` constructs fine (the immutability tests do exactly this) but `event.type` raises `AttributeError` — if one ever reaches `_dispatch`, the failure is an AttributeError rather than the intended NotImplementedError contract.
**Fix:** Document Event as abstract-by-convention, or add a `__post_init__` guard raising a clear error when `type` is unset.

#### IN-08: OrderManager.modify_order/cancel_order signatures still say `order_id: int`

**File:** `itrader/order_handler/order_manager.py:463, 541`
**Issue:** Type hints and docstrings declare `int` order/portfolio ids, but the system is UUIDv7 end-to-end since M2. Misleading under `mypy --strict` goals.
**Fix:** Retype to `OrderId` / `PortfolioId | int`.

#### IN-09: CSV window end-slice correctness depends on the configured timezone offset

**File:** `itrader/price_handler/data_provider.py:170-173`
**Issue:** `end = Timestamp(CSV_END_DATE, tz=TIMEZONE) + 1 day` with an inclusive `.loc[start:end]`. With TIMEZONE='Europe/Paris' the UTC-midnight kline for the day after CSV_END_DATE falls outside the bound only because of the +1/+2h offset; with TIMEZONE='UTC' the same code would include one extra bar past the pinned window.
**Fix:** Use an exclusive end: `data.loc[start:end - pd.Timedelta(nanoseconds=1)]` or boolean-mask `index < end`.

#### IN-10: TOCTOU between the max-portfolios check and the insert in add_portfolio

**File:** `itrader/portfolio_handler/portfolio_handler.py:154-170`
**Issue:** The limit check runs under `gen_rlock()` and the insert under a separate `gen_wlock()` — two concurrent `add_portfolio` calls can both pass the check and exceed the limit. Harmless single-threaded (backtest), real in live mode.
**Fix:** Perform check + insert under one write lock.

#### IN-11: `symbols=['all']` on the csv path dereferences a None exchange

**File:** `itrader/price_handler/data_provider.py:78, 407-408`
**Issue:** On the csv branch `self.exchange = None`, but `_init_symbols` still does `self.exchange.get_tradable_symbols()` when 'all' is requested — `AttributeError`. Same in `set_symbols` (line 384).
**Fix:** Raise a clear `ConfigurationError`/`ValueError` ("'all' is not supported on the csv feed") on the csv branch.

---

_Reviewed: 2026-06-05T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
