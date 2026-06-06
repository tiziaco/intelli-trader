---
phase: 05-m4-money-transaction-correctness
reviewed: 2026-06-06T00:00:00Z
depth: standard
files_reviewed: 50
files_reviewed_list:
  - itrader/core/enums/__init__.py
  - itrader/core/enums/execution.py
  - itrader/core/enums/portfolio.py
  - itrader/core/portfolio_read_model.py
  - itrader/events_handler/events/fill.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/signal.py
  - itrader/execution_handler/base.py
  - itrader/execution_handler/exchanges/base.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/matching_engine.py
  - itrader/execution_handler/result_objects.py
  - itrader/order_handler/base.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/order_handler/storage/postgresql_storage.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/transaction/transaction_manager.py
  - itrader/portfolio_handler/transaction/transaction.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/position_sizer/variable_sizer.py
  - itrader/strategy_handler/risk_manager/advanced_risk_manager.py
  - itrader/strategy_handler/sltp_models/sltp_models.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/live_trading_system.py
  - tests/integration/test_reservation_inertness.py
  - tests/unit/core/test_portfolio_read_model.py
  - tests/unit/events/test_events.py
  - tests/unit/events/test_fill_event_schema.py
  - tests/unit/events/test_order_event_schema.py
  - tests/unit/execution/exchanges/test_simulated_exchange.py
  - tests/unit/execution/test_execution_handler.py
  - tests/unit/execution/test_matching_engine.py
  - tests/unit/order/test_on_signal.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/order/test_order_validator.py
  - tests/unit/portfolio/test_cash_manager.py
  - tests/unit/portfolio/test_portfolio_handler.py
  - tests/unit/portfolio/test_portfolio.py
  - tests/unit/portfolio/test_state_storage.py
  - tests/unit/portfolio/test_transaction_manager.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 2
  warning: 12
  info: 10
  total: 24
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-06-06
**Depth:** standard
**Files Reviewed:** 50
**Status:** issues_found

## Summary

Reviewed the M4 money-and-transaction-correctness implementation: PortfolioReadModel Protocol boundary, cash reservation lifecycle, atomic validate-first settlement, ExecutionResult deletion (events-only output), D-19 lock deletion, and the Decimal retype of Signal/Order/Fill event money. The core money path is solid: Decimal enters once at construction boundaries (`to_money`), the matching engine stays float with single, well-tested conversion boundaries, and the settlement sequence (validate → invariant → position → cash → record) is correctly ordered with the invariant checking balance, not buying power.

Two Critical findings: a `TypeError` in `validate_order_modification` that makes quantity-only order modification always fail, and `LiveTradingSystem` calling a method (`record_metrics`) that does not exist on `PortfolioHandler` — an `AttributeError` on every TIME event in live mode, silently swallowed by the loop's catch-all. The Warnings cluster around reservation-lifecycle leak paths (release skipped on `add_fill` rejection, no release on post-reserve assembly failure, no release on local cancel without exchange acknowledgement), the order mirror ignoring `fill_event.quantity`, orphaned bracket children after parent rejection, and concurrency tests that now race against the deliberately lock-free D-19 managers.

## Critical Issues

### CR-01: Quantity-only order modification always fails with TypeError

**File:** `itrader/order_handler/order_validator.py:529-538` (triggered via `itrader/order_handler/order_manager.py:591-593`)
**Issue:** `OrderManager.modify_order` always passes both kwargs — `validate_order_modification(order, new_price=new_price, new_quantity=new_quantity)` — including `None` values. Inside the validator, `'new_price' in modifications` is therefore always true, and when `new_price` is `None` the check `if new_price <= 0:` raises `TypeError: '<=' not supported between instances of 'NoneType' and 'int'`. The exception is caught by `modify_order`'s blanket `except` and converted into a generic failure result, so **any modification that supplies only a new quantity (no price) always fails**. Symmetrically, `new_quantity=None` raises `TypeError` at `new_quantity < order.filled_quantity` whenever the order is partially filled (`filled_quantity` truthy). The existing test (`test_modify_emits_modify_command`) only exercises price-only modification on an unfilled order, so neither broken path is covered.
**Fix:**
```python
# order_validator.py — guard None before comparing
if 'new_quantity' in modifications and modifications['new_quantity'] is not None:
    new_quantity = modifications['new_quantity']
    if order.filled_quantity and new_quantity < order.filled_quantity:
        ...
if 'new_price' in modifications and modifications['new_price'] is not None:
    new_price = modifications['new_price']
    if new_price <= 0:
        ...
```
Add a regression test for `modify_order(order_id, new_quantity=...)` with no price, and for price-only modify on a partially filled order.

### CR-02: LiveTradingSystem calls nonexistent `PortfolioHandler.record_metrics` — AttributeError every TIME event

**File:** `itrader/trading_system/live_trading_system.py:246`
**Issue:** `self.portfolio_handler.record_metrics(event.time)` — `record_metrics` is defined only on `Portfolio` (`itrader/portfolio_handler/portfolio.py:342`), not on `PortfolioHandler` (verified by grep: the only definition is on `Portfolio`). In live mode every TIME event raises `AttributeError`, which is swallowed by the loop's `except Exception` at line 261-266 — metrics are silently never recorded and `errors_count` inflates on every tick. The backtest path does this correctly (`for portfolio in ...get_active_portfolios(): portfolio.record_metrics(...)`, `backtest_trading_system.py:149-150`).
**Fix:**
```python
if hasattr(event, 'type') and event.type == EventType.TIME:
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)
```

## Warnings

### WR-01: Order-mirror reconciliation ignores `fill_event.quantity`

**File:** `itrader/order_handler/order_manager.py:118`
**Issue:** On `FillStatus.EXECUTED` the mirror applies `order.add_fill(order.remaining_quantity, ...)` — the fill event's own `quantity` field is never read. The exchange explicitly anticipates partial fills (`simulated.py:_emit_fill` docstring: "the matched fill quantity ... may differ from event.quantity for partial fills"), and the portfolio ledger settles `fill_event.quantity`. The moment any partial fill is emitted, the mirror will mark the FULL remaining quantity filled while the portfolio settles only the partial — mirror and ledger diverge silently. Also note the fill quantity on the event is float-roundtripped at the exchange boundary (locked D-22 decision), so it can legitimately differ from `remaining_quantity` at full Decimal precision.
**Fix:** Reconcile with the exchange-truth quantity: `order.add_fill(to_money(fill_event.quantity), to_money(fill_event.price), ...)`, treating a fill quantity exceeding `remaining_quantity` as the clamp/warn case.

### WR-02: Reservation release skipped when `add_fill` is rejected — stuck buying power

**File:** `itrader/order_handler/order_manager.py:118-121, 142-144`
**Issue:** In `on_fill`, when `order.add_fill(...)` returns `False` (invalid transition — e.g., an EXECUTED fill arriving for an order already locally CANCELLED, or any future quantity-mismatch rejection) the method early-returns BEFORE the uniform terminal release at line 142. The portfolio has already settled the fill (FILL dispatches portfolio-first), but the BUY's reservation is never released — exactly the stuck-reservation state T-05-17 is meant to prevent, and it persists for the rest of the run, shrinking `available_cash` for every subsequent sizing/validation read.
**Fix:** Perform the idempotent release in a `finally`-style path for every fill that references a known order, regardless of whether the mirror transition applied:
```python
finally-equivalent: if self.portfolio_handler is not None:
    self.portfolio_handler.release(cast(PortfolioId, order.portfolio_id), order.id)
```
(only skipping release when you intentionally want the reservation held, which no current branch does).

### WR-03: Reservation leaks when bracket assembly/storage fails after reserve

**File:** `itrader/order_handler/order_manager.py:228-251` and `469-475`
**Issue:** `process_signal` reserves cash (step 2b) BEFORE `_assemble_bracket_and_emit` (step 3). `_assemble_bracket_and_emit` catches its own exceptions and returns a failure result — but nothing releases the reservation taken for `primary`. Since no OrderEvent was emitted, no fill will ever arrive to trigger the terminal release in `on_fill`. The reservation is orphaned forever. Same for the outer `except` in `process_signal` (line 256) if anything between reserve and emit raises.
**Fix:** Wrap step 3 so a failed assembly releases the reservation:
```python
try:
    results.extend(self._assemble_bracket_and_emit(...))
except/on-failure:
    self.portfolio_handler.release(cast(PortfolioId, primary.portfolio_id), primary.id)
```
and have `_assemble_bracket_and_emit` signal failure distinguishably (it currently returns a mixed list).

### WR-04: Local cancel path never releases the reservation when the exchange does not acknowledge

**File:** `itrader/order_handler/order_manager.py:635-689`; `itrader/execution_handler/exchanges/simulated.py:235-244`
**Issue:** `OrderManager.cancel_order` marks the order CANCELLED locally (terminal) and emits an `OrderCommand.CANCEL`, relying on the exchange's `FillEvent(CANCELLED)` to drive the release in `on_fill`. But the exchange only emits CANCELLED for an order actually resting in the matching engine ("a cancel for an unknown/already-filled order emits no spurious fill"). A cancelled BUY that was never resting (e.g., immediate-market order rejected before resting, or a race with an in-flight fill) reaches terminal state locally with its reservation permanently held. The "reserver owns the release on terminal reconciliation" contract (D-01/OQ2) is only honored on the fill-event path, not on the API cancel path.
**Fix:** Release in `cancel_order` after a successful local terminal transition (the release is idempotent, so a later exchange CANCELLED fill re-releasing is a no-op).

### WR-05: Bracket children orphaned when the parent is REFUSED — protective orders with no position

**File:** `itrader/order_handler/order_manager.py:366-477`; `itrader/execution_handler/exchanges/simulated.py:226-255`
**Issue:** `_assemble_bracket_and_emit` emits parent + SL + TP unconditionally; the simulated exchange rests STOP/LIMIT children immediately on receipt — there is no "activate children only after parent fill" gating, and no OCO/cancel path triggered by the parent's terminal failure. If the parent market BUY is REFUSED (validation failure, simulated failure, disconnect), the SL SELL and TP SELL remain resting in the book. When price later crosses them they fill, producing SELL transactions against a flat portfolio — opening an unintended SHORT position. `on_fill`'s REFUSED branch reconciles only the parent; `child_order_ids` are never used to cancel siblings.
**Fix:** In `on_fill`, when a parent order (non-empty `child_order_ids`) reconciles to REJECTED/CANCELLED without any fill, issue CANCEL OrderEvents for its children (or have the exchange cancel resting orders whose `parent_order_id` matches a refused parent's id).

### WR-06: DynamicSizer divides by zero when open positions reach `max_positions`

**File:** `itrader/strategy_handler/position_sizer/variable_sizer.py:65-66`
**Issue:** `available_pos = (max_positions - open_count)` then `quantity = (cash * (max_allocation * (1 / available_pos))) / last_price`. With `max_positions=1` (the strategy default) and one open position in a DIFFERENT ticker (so `open_position is None` for this ticker but `open_count == 1`), `available_pos == 0` → `ZeroDivisionError`. With `open_count > max_positions` the quantity goes negative. The sizer is part of the D-17 admission path and was retyped to the Protocol this phase.
**Fix:**
```python
available_pos = max_positions - open_count
if available_pos <= 0:
    return 0.0  # or raise a typed sizing error the caller maps to a rejection
```

### WR-07: `Portfolio.to_dict` reports total cash as `available_cash` — reservations ignored

**File:** `itrader/portfolio_handler/portfolio.py:457`
**Issue:** `'available_cash': self.cash,  # Keep backward compatibility`. Before this phase available == total held; now that the reservation gate is live (Plan 05-06), `available_cash` is a real, distinct figure (`cash_manager.available_balance`). Every consumer of `portfolios_to_dict()` / `PortfolioUpdateEvent` sees buying power inflated by the sum of outstanding reservations — directly contradicting D-14's "single trading-decision figure" intent on the serialization surface.
**Fix:** `'available_cash': self.cash_manager.available_balance` (and add `'reserved_cash': self.cash_manager.reserved_balance` for auditability).

### WR-08: `max_portfolios` bound to the per-portfolio position limit

**File:** `itrader/portfolio_handler/portfolio_handler.py:65`
**Issue:** `self.max_portfolios = self.config_data.limits.max_positions` — the cap on how many PORTFOLIOS the handler may hold is sourced from `limits.max_positions`, which everywhere else (Portfolio health check, `update_config` mapping, tests) means "max open positions per portfolio". Tightening the position limit silently caps portfolio creation, and vice versa.
**Fix:** Add an explicit `max_portfolios` field to the system/portfolio config (or a named constant) instead of reusing `limits.max_positions`.

### WR-09: Live event loop get-then-put-back breaks FIFO ordering and `task_done` accounting

**File:** `itrader/trading_system/live_trading_system.py:234-248`
**Issue:** The loop does `event = queue.get(...)`, then `queue.put(event)  # Put it back for processing` before calling `process_events()`. If the queue holds `[A, B]`, the loop takes A and re-appends it, yielding `[B, A]` — `process_events()` then drains B before A, violating the single-FIFO-queue ordering contract the entire architecture depends on (e.g., a BAR processed before the PING that preceded it). Additionally, `task_done()` is called once per outer get while the extra `put` and `process_events`'s internal gets leave `unfinished_tasks` permanently drifting — any future `queue.join()` would hang or raise.
**Fix:** Process the dequeued event directly (dispatch it through the event handler's routing) instead of re-enqueueing it, and drop the `task_done()` bookkeeping or apply it consistently.

### WR-10: Hardcoded database credentials in source

**File:** `itrader/trading_system/live_trading_system.py:29-31`
**Issue:** `_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "postgresql+psycopg2://postgres:1234@localhost:5432/.......")` — a default connection string with embedded username/password committed to the repository. Even as a dev-only fallback, hardcoded credentials in source are a security anti-pattern and normalize the password into VCS history.
**Fix:** Default to `None` and fail loudly (or fall back to in-memory storage, which the code already does on `NotImplementedError`) when `SYSTEM_DB_URL` is unset:
```python
_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")
```

### WR-11: Concurrency tests race against the now lock-free CashManager (D-19)

**File:** `tests/unit/portfolio/test_cash_manager.py:276-349`
**Issue:** `test_concurrent_operations` runs 10 threads doing `deposit`/`withdraw` against a `CashManager` whose locks this phase deliberately deleted (D-19 single-writer contract — "lock removed" at `cash_manager.py:59`). `deposit`/`withdraw` are read-modify-write (`old_balance = self._balance; ...; self._balance = new_balance`), so concurrent threads can interleave and lose updates; the final assertion `cm.balance == Decimal("100250.00")` is a race that will fail intermittently. The test now asserts a thread-safety property the code intentionally no longer provides — it is both flaky and misleading documentation of the contract.
**Fix:** Delete or rewrite these tests as sequential single-writer tests (mirroring `test_update_config_sequential_single_writer` in the exchange suite), e.g. run the 10 operations sequentially and assert the same final balance.

### WR-12: `Strategy._generate_signal` crashes on a ticker missing from the last bar

**File:** `itrader/strategy_handler/base.py:79-104`
**Issue:** `last_close = self.last_event.get_last_close(ticker)` is not None-guarded. If the ticker is absent from the bar (sparse universe, data gap), `to_money(None)` raises (`Decimal(str(None))` → `InvalidOperation`) — or `round(last_close, 4)` raises `TypeError` — inside the strategy callback. The matching engine guards exactly this Optional (`matching_engine.py:109-112`); the signal path does not.
**Fix:**
```python
last_close = self.last_event.get_last_close(ticker)
if last_close is None:
    return
```

## Info

### IN-01: Dead imports and dead constant

**File:** `itrader/portfolio_handler/portfolio.py:1,25`; `itrader/portfolio_handler/position/position_manager.py:10`; `itrader/order_handler/order_handler.py:11`
**Issue:** `import numpy as np` is unused in both `portfolio.py` and `position_manager.py`; module-level `TOLERANCE = 1e-3` in `portfolio.py` is unused (superseded by `PositionManager.tolerance` Decimal); `PortfolioUpdateEvent` is imported but unused in `order_handler.py`.
**Fix:** Remove them (`mypy --strict`/lint hygiene for the program-level definition of done).

### IN-02: OrderHandler constructs a second, unused EnhancedOrderValidator

**File:** `itrader/order_handler/order_handler.py:78`
**Issue:** `self.order_validator = EnhancedOrderValidator(portfolio_handler)` is never referenced again — `OrderManager` builds and uses its own instance (`order_manager.py:85`). Duplicate construction implies a second validation surface that does not exist.
**Fix:** Delete the handler-level instance (or delegate to `self.order_manager.order_validator` if external access is needed).

### IN-03: `on_fill` docstring/comments omit the REFUSED branch

**File:** `itrader/order_handler/order_manager.py:100-105, 131`
**Issue:** The docstring describes only "EXECUTED -> FILLED; CANCELLED -> CANCELLED" and the comment at line 131 says "Only reached for an applied EXECUTED or CANCELLED reconciliation", but the code also handles `REFUSED -> REJECTED` and reaches line 134 for it. Comment drift on the reconciliation contract.
**Fix:** Update both to enumerate the three terminal mappings.

### IN-04: Metrics cache values are never pruned

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:173-174`
**Issue:** `record_snapshot` clears `_cache_timestamp` but not `_metrics_cache`; `_is_cache_valid` keys off `_cache_timestamp`, so correctness holds, but stale `PerformanceMetrics` objects accumulate unboundedly in `_metrics_cache` over a long run.
**Fix:** Clear both dicts together.

### IN-05: Stale "until plan 05-06 wires reservations" comments now that 05-06 landed

**File:** `itrader/strategy_handler/position_sizer/variable_sizer.py:60`; `itrader/strategy_handler/risk_manager/advanced_risk_manager.py:71-72`; `itrader/order_handler/order_validator.py:445`
**Issue:** Multiple comments still claim "available == total until plan 05-06 wires reservations". The reservation gate is live in this phase, so available can be strictly less than total at these read sites — the comments now describe behavior that no longer holds.
**Fix:** Update the comments to reflect that `available_cash` is reservation-adjusted.

### IN-06: Type-annotation drift on id and Optional parameters

**File:** `itrader/order_handler/order_handler.py:113,150,214`; `itrader/order_handler/order_manager.py:557,635,695`; `itrader/trading_system/live_trading_system.py:154,178`
**Issue:** `order_id: int` annotations persist throughout the order API while runtime ids are UUIDv7 (`OrderId`); `modify_order(new_price: Optional[float])` while entity money is Decimal; `_update_status(..., error_msg: str = None)` and `_update_stats(event_type: str = None)` use implicit Optional. All will fail the `mypy --strict` definition of done.
**Fix:** Retype to `OrderId`/`Decimal | None`/`Optional[str]` respectively.

### IN-07: Assertion-free / disjunctive test cases

**File:** `tests/unit/order/test_order_validator.py:102-109, 218-233`
**Issue:** `test_edge_case_validations` runs three validations with no assertion on the first two outcomes; `test_financial_risk_validation` asserts `result.success is False or result.has_warnings` — a disjunction that passes for nearly any outcome. These tests cannot fail meaningfully.
**Fix:** Pin the expected verdict for each case (e.g., 10M order value must be an `ORDER_VALUE_TOO_HIGH` ERROR).

### IN-08: Tests construct Decimal-typed event money fields with floats

**File:** `tests/unit/events/test_fill_event_schema.py:14-19,72-73`; `tests/unit/execution/test_matching_engine.py:12-19`; `tests/unit/order/test_on_signal.py:32-44`
**Issue:** `OrderEvent`/`SignalEvent` declare `price: Decimal` (D-22) but the frozen dataclasses do not coerce, and several test factories pass raw floats (`price=40.0, quantity=1.0`), then assert float equality (`order.price == 40.0`). The tests therefore exercise and implicitly bless float-money events that violate the schema the phase just locked. Production constructors all enter via `to_money`, so this is test-side only.
**Fix:** Construct event money as `Decimal("...")` in test factories (the D-22 boundary tests that intentionally pass floats through `new_fill`'s `to_money` are fine as-is).

### IN-09: Simulated failure scenario discards its error code and mislabels one scenario

**File:** `itrader/execution_handler/exchanges/simulated.py:138-147`
**Issue:** `_error_code, error_msg = self._rng.choice(error_scenarios)` — the chosen `ExecutionErrorCode` is discarded; the REFUSED FillEvent carries no error code, so the failure taxonomy built in `ExecutionErrorCode` is unreachable from the events-only output. Also `(ExecutionErrorCode.EXCHANGE_MAINTENANCE, "Simulated execution timeout")` pairs a maintenance code with a timeout message.
**Fix:** Either thread the code into the rejection reason string or drop the unused codes; fix the mismatched pair.

### IN-10: Hardcoded $1M order/transaction-value caps will silently reject trades in long compounding runs

**File:** `itrader/order_handler/order_validator.py:84`; `itrader/portfolio_handler/transaction/transaction_manager.py:60`; `itrader/portfolio_handler/position/position_manager.py:80`
**Issue:** `max_order_value = 1000000.0`, `max_transaction_amount = Decimal('1000000.00')` and `max_position_value = Decimal('1000000.00')` are hardcoded. The validator's `max_price` was already raised to 10M for the golden BTCUSD feed (DEF-01-B), but the VALUE caps were not: once portfolio equity compounds past ~$1.05M, every 0.95-sized entry order exceeds $1M and is rejected (`ORDER_VALUE_TOO_HIGH`), silently truncating the strategy. Worse, if an order slipped past the validator, the same cap fires at SETTLEMENT (`TransactionManager.validate` / `_create_new_position`) where a fill is already a fact — crashing the run.
**Fix:** Source these caps from config (per-portfolio limits already exist in `PortfolioConfig`) or raise them consistently with the DEF-01-B price-ceiling adjustment.

---

_Reviewed: 2026-06-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
