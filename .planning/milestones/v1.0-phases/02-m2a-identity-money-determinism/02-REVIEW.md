---
phase: 02-m2a-identity-money-determinism
reviewed: 2026-06-04T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - itrader/core/clock.py
  - itrader/core/ids.py
  - itrader/core/money.py
  - itrader/outils/id_generator.py
  - itrader/events_handler/event.py
  - itrader/events_handler/full_event_handler.py
  - itrader/order_handler/order.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/cash_manager.py
  - itrader/portfolio_handler/transaction.py
  - itrader/portfolio_handler/transaction_manager.py
  - itrader/portfolio_handler/position.py
  - itrader/portfolio_handler/position_manager.py
  - itrader/portfolio_handler/metrics_manager.py
  - itrader/execution_handler/execution_handler.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/exchanges/base.py
  - itrader/execution_handler/matching_engine.py
  - itrader/execution_handler/slippage_model/fixed_slippage_model.py
  - itrader/execution_handler/slippage_model/linear_slippage_model.py
  - itrader/trading_system/backtest_trading_system.py
findings:
  critical: 3
  warning: 7
  info: 5
  total: 15
status: issues_found
---

# Phase 02 (M2a): Code Review Report

**Reviewed:** 2026-06-04
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

Adversarial review of the M2a identity/money/determinism refactor. The Decimal
money entry policy (`to_money`/`quantize`), the UUIDv7 id scheme, the frozen
hot-path events, and the seeded-RNG slippage wiring are largely well-built and
test-locked. However, three correctness defects break the milestone's own
guarantees:

1. The injected `BacktestClock` is constructed and advanced every bar but **read
   by zero consumers** — the "clock wired onto the backtest engine path" claim is
   not realized; every domain `now()` is still wall-clock (CR-01).
2. `BacktestClock.now()` guards with a bare `assert`, which `python -O` strips —
   the determinism guard silently becomes a `None`-returning wall-clock leak
   (CR-02).
3. The cash setter (`Portfolio.cash +=`) routes the BUY/SELL cost through
   `deposit`/`withdraw`, which quantize to a 2-dp *cash* scale and then run a
   `min_balance`/`max_balance` gate — this both silently drops sub-cent precision
   on every fractional-BTC transaction and can raise on a path the transaction
   layer does not expect (CR-03).

Several mixed Decimal/float seams remain (`_should_close_position`,
`_validate_position_consistency`, position-manager `Decimal(str(...))` round-trips
on already-Decimal values) that are tolerated today only because Decimal-vs-float
*comparison* happens to work in CPython — they are fragile and defeat the
end-to-end-Decimal intent.

## Critical Issues

### CR-01: Injected BacktestClock has no consumers — determinism seam is inert

**File:** `itrader/trading_system/backtest_trading_system.py:53,117` (and `itrader/core/clock.py`)
**Issue:** `self.clock = BacktestClock()` is created and `self.clock.set_time(ping_event.time)` is called on every ping, but a repo-wide search shows `clock.now()` is invoked nowhere outside `core/clock.py`'s own definition. Every engine-path consumer of "current time" still calls `datetime.now()` directly: `metrics_manager.record_snapshot` default, `cash_manager._create_operation` (timestamp + `operation_id`), `transaction_manager` (`correlation_id` + all `context` timestamps), `order.py` audit timestamps, and `Portfolio.set_state`/`_last_activity`. The clock docstring asserts "any engine-path consumer of 'now' reads deterministic time (D-09/D-10)" and the phase focus states M2a "wires the clock onto the backtest engine path" — neither is true. The seam is dead wiring. Backtest *results* stay deterministic only because the result-bearing path (`record_metrics`) is fed `ping_event.time` explicitly, not via the clock — so the clock provides no actual determinism and any future caller wiring `clock.now()` is untested.
**Fix:** Either (a) inject `self.clock` into the consumers that M2a claims to cover and route their `datetime.now()` through it, or (b) if order/transaction/cash audit timestamps are genuinely deferred to M2b, correct `clock.py`'s docstring and the engine comment to state the clock currently has no domain consumer and is advanced only to be ready for M2b. Do not ship a guarantee comment that the code does not implement.
```python
# Minimal real wiring example for a covered consumer:
portfolio.record_metrics(self.clock.now())   # instead of ping_event.time, proving the seam is live
```

### CR-02: BacktestClock determinism guard uses `assert` — stripped under `python -O`

**File:** `itrader/core/clock.py:44-46`
**Issue:** `now()` enforces "clock was advanced" via `assert self._t is not None, "BacktestClock not advanced"`. Python's `-O` / `PYTHONOPTIMIZE` flag removes all `assert` statements. Under optimization the guard vanishes and `now()` returns `None` (the un-advanced sentinel) instead of failing loudly — a `None` timestamp then propagates into whatever consumer is eventually wired (see CR-01), silently corrupting time rather than "surfacing loudly" as the docstring promises. A determinism guard that disappears under a standard interpreter flag is not a guard.
**Fix:** Replace the assert with an explicit raise that survives `-O`:
```python
def now(self) -> datetime:
    if self._t is None:
        raise RuntimeError("BacktestClock not advanced: call set_time() before now()")
    return self._t
```
(Update `test_core/test_clock.py::test_backtest_clock_now_before_advance_raises` to expect `RuntimeError` instead of `AssertionError`.)

### CR-03: Cash setter quantizes every transaction cost to 2 dp and runs balance gates the txn layer does not expect

**File:** `itrader/portfolio_handler/portfolio.py:203-212`, `itrader/portfolio_handler/cash_manager.py:416-433,126,186`
**Issue:** `transaction_manager._execute_transaction` does `self.portfolio.cash += transaction_cost` (a full-precision Decimal). The `cash` setter computes `difference = to_money(value) - current_balance` and routes it through `cash_manager.deposit()` / `withdraw()`. Both call `_validate_and_convert_amount`, which **quantizes the amount to the 2-dp cash precision** (`to_money(amount).quantize(self.precision, ROUND_HALF_UP)`). For fractional-BTC fills the cost has sub-cent precision (e.g. `42350.727777 * 0.123456 = 5228.451448...`), so each transaction silently loses up to ~0.005 of cash, accumulating across a multi-year backtest. Worse, `deposit` enforces `max_balance = 10_000_000` and `withdraw` enforces `min_balance = 0` / available-funds checks — so a SELL that pushes cash above 10M, or any path the funds check rejects, raises `InvalidTransactionError`/`InsufficientFundsError` from *inside the cash setter*, a place `_execute_transaction` (which already did its own funds check) does not guard. This is both a precision-correctness defect and a latent crash, and it directly threatens the D-15 numeric tolerance the oracle test leans on.
**Fix:** Have the transaction cash path call a precision-preserving ledger primitive that does not re-quantize to 2 dp and does not re-run deposit/withdraw policy gates, or make the cash scale match the instrument's resolution at this boundary. At minimum, route transaction cash flow through `cash_manager.process_transaction_cash_flow(...)` (which already exists and is the intended seam) instead of the `cash +=` setter, and decide explicitly whether the cash ledger is 2-dp (then quantize once, documented) or full-precision:
```python
# transaction_manager._execute_transaction, instead of self.portfolio.cash += transaction_cost:
self.portfolio.cash_manager.process_transaction_cash_flow(
    amount=transaction_cost, is_debit=transaction_cost < 0,
    description="transaction", transaction_id=str(transaction.id),
)
```

## Warnings

### WR-01: Mixed Decimal/float comparison in position-close threshold

**File:** `itrader/portfolio_handler/position_manager.py:184`
**Issue:** `_should_close_position` returns `abs(position.net_quantity) <= float(self.tolerance)`. `net_quantity` is `Decimal`; `self.tolerance` is `Decimal('0.00001')` coerced to `float`. CPython tolerates `Decimal <= float` comparison, so it does not crash today, but coercing a Decimal tolerance back to float defeats the end-to-end-Decimal intent and reintroduces binary-float imprecision into the position-closure decision — the exact class of bug M2a exists to remove. A position that should net to exactly zero can be misjudged on the float boundary.
**Fix:** Compare Decimal-to-Decimal: `return abs(position.net_quantity) <= self.tolerance`.

### WR-02: `_validate_position_consistency` mixes float literal with Decimal net_quantity

**File:** `itrader/portfolio_handler/position_manager.py:208`
**Issue:** `if position.net_quantity < 0 and abs(position.net_quantity) > 1e-6:` compares Decimal `net_quantity` against the float literal `1e-6`. Same fragility as WR-01 — relies on CPython's Decimal/float comparison and undermines the Decimal contract. Note `net_quantity` is `abs(buy-sell)` and can never be negative, so the first clause is also effectively dead.
**Fix:** Use a Decimal literal (`Decimal("0.000001")`) and reconsider the unreachable `< 0` branch.

### WR-03: Redundant `Decimal(str(...))` round-trips on values that are already Decimal

**File:** `itrader/portfolio_handler/transaction_manager.py:253-255`; `itrader/portfolio_handler/position_manager.py:126,278,289,301,336,392,394`
**Issue:** `_calculate_transaction_cost` does `Decimal(str(transaction.price))` etc., and `position_manager` repeatedly does `Decimal(str(position.market_value))`, `Decimal(str(transaction.price * transaction.quantity))`. These fields are already `Decimal` (Transaction/Position normalize in `__post_init__`/`to_money`). Round-tripping a Decimal through `str()` is wasteful and, for `Decimal(str(a*b))`, forces the product through a string repr that can re-quantize precision. The transaction_manager comment even claims the round-trip was removed ("no `Decimal(str(...))` round-trip needed") while the code three lines later still does it. Inconsistent with the stated M2a money policy.
**Fix:** Drop the `Decimal(str(...))` wrappers where the operand is already Decimal; operate on the Decimal values directly.

### WR-04: Commission computed on pre-slippage price, not executed price

**File:** `itrader/execution_handler/exchanges/simulated.py:224-230`
**Issue:** `_emit_fill` computes `commission = fee_model.calculate_fee(quantity, price=fill_price, ...)` using the *pre-slippage* `fill_price`, then computes `executed_price = fill_price * slippage_factor` and emits the fill at `executed_price`. A percent fee model therefore charges commission on a notional the trade did not actually execute at. Whether this is intended is undocumented; for a realistic exchange the taker fee is assessed on the executed notional. This silently biases realized PnL.
**Fix:** Decide and document the policy. If fees should track the executed price, compute slippage first and pass `executed_price` into `calculate_fee`. If pre-slippage is intentional, add a comment stating so.

### WR-05: `_resolve_signal_quantity` sizes fraction-of-cash in float, defeating Decimal cash ledger

**File:** `itrader/order_handler/order_manager.py:274,279`
**Issue:** Entry sizing does `signal_event.quantity = (0.95 * float(portfolio.cash)) / price` and exit sizing does `float(open_position.net_quantity)`. Both coerce Decimal money back to float at the sizing boundary. The 0.95 buffer comment admits this is to stop "float/rounding" overshoot — i.e. the code is papering over the float seam it just (re)introduced. On the SELL-exit path, `float(net_quantity)` can fail to exactly equal the Decimal position quantity, so the exit may not net the long to precisely zero (the `_should_close_position` tolerance in WR-01 then has to absorb it). This is a determinism/precision smell on the result-bearing path.
**Fix:** Keep sizing in Decimal end-to-end (size against `portfolio.cash` and `net_quantity` as Decimal, quantize quantity to the instrument's 8-dp scale via `quantize(..., "quantity")`), coercing to the float SignalEvent only at the final assignment if the event type still requires float.

### WR-06: Engine swallows all exchange exceptions, can silently drop fills/cancels

**File:** `itrader/execution_handler/execution_handler.py:80-82,94-98`; `itrader/execution_handler/exchanges/simulated.py:246-252`
**Issue:** `ExecutionHandler.on_order` and `on_market_data` wrap exchange calls in broad `except Exception` that only logs. `SimulatedExchange.on_market_data` iterates `fills`/`cancels` with no inner guard, so a raise mid-loop (e.g. a malformed resting order surviving the matching-engine guard) aborts the remaining fills/cancels for that bar — and the outer handler logs and moves on, permanently losing those fills with no reconciliation. In a money engine a dropped fill is a silent position/cash divergence, not a recoverable warning.
**Fix:** Narrow the caught exception set, and/or process each fill/cancel in its own try so one bad decision cannot drop the rest of the bar. Consider emitting a `PortfolioErrorEvent` (the type already exists) when a fill is dropped so the divergence is observable rather than log-only.

### WR-07: `process_transaction` may reference `context` before assignment on early failure

**File:** `itrader/portfolio_handler/transaction_manager.py:87-137`
**Issue:** `context` is created inside the `try`. If `TransactionContext(...)` construction itself raises (e.g. a future field validation), the `except Exception as e:` branch calls `self._handle_transaction_error(transaction, context, e)` with `context` unbound, producing an `UnboundLocalError` that masks the original exception. The `finally` also does `self._pending_transactions.pop(transaction.id, None)` which is safe, but the error handler is not.
**Fix:** Initialize `context = None` before the `try` and have `_handle_transaction_error` tolerate `context is None`, or construct the context before entering the guarded region.

## Info

### IN-01: `event_type_map` / `fill_status_map` missing entries silently

**File:** `itrader/events_handler/event.py:14-21`
**Issue:** `event_type_map` omits `SCREENER` (present in the `EventType` enum) and there is no entry for `UPDATE`-reuse clarity. Any string-keyed lookup of `"SCREENER"` returns `None`. Low impact today (no caller uses it for SCREENER) but it is an inconsistent map.
**Fix:** Add the missing `"SCREENER": EventType.SCREENER` entry or document why it is excluded.

### IN-02: Stale int-id type hints contradict the UUIDv7 migration

**File:** `itrader/events_handler/event.py:219,235,302,305,306,383,384`; `itrader/order_handler/order_manager.py:449,456,527`
**Issue:** `OrderEvent.order_id`/`parent_order_id`, `FillEvent.order_id`/`portfolio_id`, and `SignalEvent.portfolio_id` are still typed `Optional[int]` / `int`, and `OrderManager.modify_order`/`cancel_order` accept `order_id: int`, while ids are now UUIDv7 `uuid.UUID`. The code passes UUIDs through these fields at runtime (the matching engine's `_resting: Dict[int, OrderEvent]` is keyed by what is actually a UUID). It works because dict keys are duck-typed, but the annotations are now lies and would mislead `mypy --strict` consumers and future maintainers.
**Fix:** Retype to the appropriate `OrderId | None` / `PortfolioId` aliases (or `uuid.UUID`) as part of closing the migration; at minimum add a carry-over comment like the ones already on `Transaction.portfolio_id`.

### IN-03: `MatchingEngine` book typed `Dict[int, OrderEvent]` but keyed by UUID

**File:** `itrader/execution_handler/matching_engine.py:40,50,54,66,69,189`
**Issue:** `_resting: Dict[int, OrderEvent]` and every `order_id: int` signature here are nominally int but hold/accept UUIDs at runtime. Consistent with IN-02; flagged separately because the matching engine is the resting-order source of truth and its types should be exact.
**Fix:** Retype to `Dict[OrderId, OrderEvent]` / `OrderId` once the OrderEvent id field migrates.

### IN-04: Backtest `print()` for run duration instead of structured logger

**File:** `itrader/trading_system/backtest_trading_system.py:125`
**Issue:** `print("Backtest duration:", duration)` uses bare `print` in an engine that otherwise uses the structured `self.logger`. Inconsistent with the logging convention in CLAUDE.md and not capturable by log handlers.
**Fix:** `self.logger.info("Backtest duration: %s", duration)`.

### IN-05: Unused imports / dead locals across reviewed modules

**File:** `itrader/portfolio_handler/cash_manager.py:9-11` (`Tuple`, `dataclass` used; `Enum` used — OK), `itrader/portfolio_handler/transaction_manager.py:11,23` (`TransactionId` used; `idgen` imported but `Transaction.new_transaction` owns id gen — verify `idgen` usage here), `itrader/portfolio_handler/portfolio.py:1` (`numpy as np` imported, unused in this module)
**Issue:** Minor unused-import / unused-import-surface noise; `import numpy as np` in `portfolio.py` is not referenced. Under the strict warning config these are harmless but add clutter.
**Fix:** Remove genuinely unused imports (confirm with a linter pass); `portfolio.py`'s `numpy` import can be dropped.

---

_Reviewed: 2026-06-04_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
