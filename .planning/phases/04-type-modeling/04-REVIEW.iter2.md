---
phase: 04-type-modeling
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/portfolio.py
  - itrader/config/strategy.py
  - itrader/core/enums/__init__.py
  - itrader/core/enums/order.py
  - itrader/core/enums/severity.py
  - itrader/events_handler/events/error.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/matching_engine.py
  - itrader/order_handler/operation_result.py
  - itrader/order_handler/order.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/validators.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/signal_record.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/trading_system/live_trading_system.py
  - scripts/run_backtest.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_reservation_inertness.py
  - tests/integration/test_universe_spans.py
  - tests/unit/core/test_enums.py
  - tests/unit/events/test_error_flow.py
  - tests/unit/events/test_event_immutability.py
  - tests/unit/order/test_admission_rules.py
  - tests/unit/order/test_on_signal.py
  - tests/unit/order/test_order.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_order_storage.py
  - tests/unit/strategy/test_signal_store.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/strategy/test_strategy_config.py
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

Phase 4 converts order/config/event/execution vocabularies onto canonical
class-based string enums (`OrderType`, `OrderStatus`, `OrderCommand`,
`OrderOperationType`, `OrderTriggerSource`, `MarketExecution`, `ErrorSeverity`),
introduces `assert_never` exhaustiveness on the fee/slippage dispatch, and
threads Decimal money end-to-end. The enum work is generally well-executed:
value-equal swaps are preserved (`OrderOperationType.value == "create_primary_order"`),
serialization keys on `.name` where the byte-identity contract requires it, and
the `_missing_` parsers raise clear f-string `ValueError`s consistent with the
`FillStatus` house pattern.

The adversarial pass surfaced one correctness defect that can break a code path
the type-modeling work newly exercises (the `_missing_` case-insensitive value
collision in `MarketExecution`/`OrderType` is fine, but the **`Side`-from-`str`
boundary in `OrderEvent.new_order_event` is fragile**), plus several robustness
and dead-code issues. None of the findings touch the golden numeric path
(SMA_MACD / 134 trades / 46189.87…) — they live on rejection, modify, live, and
serialization edges that the byte-exact oracle does not cover, which is exactly
why they are not caught by the existing test suite.

The most important finding (CR-01) is a latent crash in the resting-order
matching loop's exception filter that can silently drop a legitimately-priced
fill, which WOULD perturb numeric results if it ever fires.

## Critical Issues

### CR-01: MatchingEngine swallows `decimal.InvalidOperation` as a "malformed order", silently dropping a real fill

**File:** `itrader/execution_handler/matching_engine.py:217-223` (and the duplicate at `:244-247`)

**Issue:** Both matching passes wrap `self._evaluate(order, bar)` in
`except (TypeError, ValueError, KeyError): continue`. The stated intent is to
skip a single malformed resting order without dropping the whole bar. But
`_evaluate` runs Decimal comparison/`min`/`max` arithmetic on `order.price` and
the Bar OHLC (`low <= trigger`, `min(open_, trigger)`, etc.). When a Decimal
operand is a NaN/sNaN or an out-of-context value, Python raises
`decimal.InvalidOperation` — which is a subclass of `ArithmeticError`, **not**
of `ValueError`. It therefore does NOT match the `except` filter and would
propagate; conversely, the comment claims "programming errors propagate" yet a
genuinely malformed Decimal trigger is neither caught (so the bar aborts the
run via the fail-fast seam) nor handled as the intended "skip this order"
case. The asymmetry means the two documented behaviors (skip-one vs.
propagate) are both wrong for the Decimal-money domain this engine now operates
in: a single bad resting order either crashes the whole backtest or, if the
value happens to be a quiet NaN that compares False, is silently treated as
"did not trigger" — a dropped fill that WOULD change the trade log.

Because matching is the source of truth for fills and the engine is now
Decimal-end-to-end (D-12/D-14), the exception filter must cover the Decimal
arithmetic failure mode it actually faces.

**Fix:**
```python
import decimal
# ...
try:
    price = self._evaluate(order, bar)
except (TypeError, ValueError, KeyError, decimal.InvalidOperation):
    # A single malformed resting order (price=NaN, missing bar field, bad
    # Decimal) must not drop the whole bar nor be misread as "no trigger".
    continue
```
Apply to both pass-1 (`:217`) and pass-2 (`:244`) handlers. Alternatively,
reject non-finite Decimal prices at `submit()` time so they can never reach
`_evaluate`.

## Warnings

### WR-01: `OrderEvent.new_order_event` reconstructs `Side` from a raw `str` with no error context

**File:** `itrader/events_handler/events/order.py:93` (constructed from entities built in `itrader/order_handler/order_manager.py:646,660,764,779`)

**Issue:** The `Order` entity stores `action` as a `str` ("BUY"/"SELL") until
M4, and `OrderEvent.new_order_event` does `action=Side(order.action)`. The
bracket-assembly paths hand-build that string with literals
(`'BUY' if signal_event.action is Side.SELL else 'SELL'`). `Side` is a plain
`Enum` with NO `_missing_` override (unlike every other enum touched this
phase), so any casing drift or typo in those hand-built strings raises a bare
`ValueError: 'buy' is not a valid Side` with no ticker/order context, aborting
the run under the fail-fast seam. This is a stringly-typed seam the phase
explicitly set out to kill everywhere else; it survives here on the order→event
boundary.

**Fix:** Either give `Side` the same case-insensitive `_missing_` parser the
order-domain enums received this phase, or convert `Order.action` to a `Side`
field at construction so `new_order_event` reads an enum directly rather than
re-parsing a string. At minimum, normalize the hand-built literals to a single
helper that cannot drift from `Side`'s values.

### WR-02: `validate_order` short-circuits quantity checks with `elif`, hiding a price problem behind a quantity problem

**File:** `itrader/execution_handler/exchanges/simulated.py:385-396`

**Issue:** The quantity block uses `if ... elif ... elif` and the price block is
a separate `if/elif`, but `failed_checks[0]` (first failure) drives the
`error_code` mapping at `:413-422`. The `elif` chaining means an order that is
simultaneously below-minimum quantity AND has a non-positive price reports only
the quantity error and an `ORDER_SIZE_TOO_SMALL` code; the price defect is never
surfaced in `error_code`. For an audit/reconciliation system where the REFUSED
fill's error code feeds downstream classification, collapsing multiple distinct
validation failures into the first-wins code loses information. The
`error_message` does join all failed checks, but the structured `error_code`
(consumed programmatically) is lossy.

**Fix:** Map `error_code` from a priority-ordered scan of the full
`failed_checks` list rather than from `failed_checks[0]`, or document explicitly
that `error_code` is "first failure only" and that callers must read
`failed_checks` for completeness.

### WR-03: `release()` in the `finally` block dereferences `order.portfolio_id` after a possible rebind, masking the real exception

**File:** `itrader/order_handler/order_manager.py:260-275`

**Issue:** The `finally` calls `self.portfolio_handler.release(order.portfolio_id, order.id)`.
`order` is fetched at `:161` and is non-None past the early return, so the
reference itself is safe. However, the `finally` runs even when the `try` body
raised and re-raised (`:249-259`). If `release()` itself raises (e.g. the
portfolio was deleted mid-run), the `except Exception` inside the `finally`
(`:272`) catches and logs it — good — but the ORIGINAL exception from the body
is the one propagating, and a release failure here is only logged, never
surfaced to the fail-fast seam. In a "numbers you can trust" engine, a stuck or
failed reservation release is a correctness event (buying power corrupts for the
rest of the run), yet it is downgraded to a log line while the unrelated body
exception propagates. The two failure modes are conflated.

**Fix:** Distinguish "body raised" from "release raised". If the body did not
raise but the release fails, that failure should itself reach the fail-fast seam
(re-raise) rather than be swallowed, since a silently-unreleased reservation is
exactly the data-corruption class WR-04's comment says it is defending against.

### WR-04: `PortfolioValidator.validate_sufficient_funds` casts `Decimal` money to `float` to build the exception

**File:** `itrader/portfolio_handler/validators.py:94-99`

**Issue:** `InsufficientFundsError(float(required_cash), float(available_cash), ...)`
converts Decimal money to `float` to construct the exception. The project money
policy (CLAUDE.md) states float-for-money is a correctness defect and `float()`
belongs only at the serialization/logging edge. An exception payload that is
later formatted into a user/audit message is arguably a logging edge, but
`InsufficientFundsError` carries these as structured fields that could be read
programmatically; the float round-trip introduces a binary-float repr artifact
in a money figure. Given the phase's Decimal-end-to-end mandate, this is an
inconsistency the type-modeling work left behind.

**Fix:** Have `InsufficientFundsError` accept `Decimal` fields and format to
`str`/`float` only inside its `__str__`/serialization, so the structured fields
stay Decimal.

### WR-05: `_publish_and_continue` and several live-path timestamps use wall-clock `datetime.now()` without tz

**File:** `itrader/trading_system/live_trading_system.py:202-208` (and `:239,:284,:291,:316`)

**Issue:** The live error-publish path builds `ErrorEvent(time=getattr(event, 'time', datetime.now()), ...)` using a naive `datetime.now()` (no `UTC`), and the processing loop uses naive `datetime.now()` for idle tracking and stats. Elsewhere in the codebase the convention is `datetime.now(UTC)` (see `portfolio_handler.py:99,145,405,427`). Mixing naive and tz-aware datetimes risks a `TypeError: can't subtract offset-naive and offset-aware datetimes` if a naive `last_event_time` is ever compared against a tz-aware value, and the `ErrorEvent.time` fallback produces a naive timestamp inconsistent with the business-time-everywhere contract. This is live-path only (oracle-dark) but is a latent runtime defect.

**Fix:** Use `datetime.now(UTC)` consistently on the live path, matching the portfolio handler, and prefer the event's own business `time` for the `ErrorEvent.time` fallback wherever an event is in scope.

## Info

### IN-01: Dead code — `SignalProcessingResult` and `OperationResult.from_operations` are never used

**File:** `itrader/order_handler/operation_result.py:58-92`

**Issue:** A repo-wide grep finds no consumer of `SignalProcessingResult`,
`from_operations`, or `all_order_events` outside the module itself. The
`process_signal`/`create_orders_from_signal` paths return `List[OperationResult]`
directly. This is unused machinery carrying its own (debatable) `any()`-based
`overall_success` semantics that no one exercises.

**Fix:** Remove `SignalProcessingResult` and `from_operations`, or add a test
that pins the intended aggregation semantics if it is reserved for a near-term
caller.

### IN-02: `validate_order` compares Decimal money against bare `float`/`int` literals

**File:** `itrader/execution_handler/exchanges/simulated.py:395,404`

**Issue:** `event.price > 1000000` and `order_value < 1.0` compare a Decimal
against an int/float literal. Python evaluates these exactly for the
int case and via exact Decimal-vs-float comparison for `1.0`, so there is no
correctness bug today — but these magic numbers ($1M price sanity ceiling, $1
minimum order value) are warning-only thresholds with no named constant, and the
`1.0` float literal in a Decimal-end-to-end module is a readability/consistency
smell.

**Fix:** Hoist to named Decimal constants (e.g. `_PRICE_SANITY_CEILING =
Decimal("1000000")`, `_MIN_ORDER_VALUE = Decimal("1")`).

### IN-03: `PortfolioValidator` still declares `float`-typed money parameters

**File:** `itrader/portfolio_handler/validators.py:20-53,113-120`

**Issue:** `validate_transaction_data(price: float, quantity: float, commission: float, ...)`
and `to_decimal(value: Union[int, float])` / `from_decimal(...)` retain the
pre-Decimal float vocabulary. On a phase whose theme is canonical typed money,
these signatures advertise a float money contract that contradicts the
Decimal-end-to-end mandate. Whether this validator is still on the live path is
unclear (it is not referenced on the backtest run path reviewed here), so it
reads as stale.

**Fix:** Retype the money parameters to `Decimal` (or confirm the validator is
dead and remove it). If retained, the `isinstance(price, (int, float))` guards
must also accept `Decimal`.

### IN-04: Misleading comment claims the `is_connected()` guard "could never fire" — but admission still depends on connection ordering

**File:** `itrader/execution_handler/exchanges/simulated.py:122-128`

**Issue:** The `_admit_order` comment asserts the removed `is_connected()` guard
was redundant because `validate_order` appends "Exchange not connected". That is
true today, but it couples admission correctness to validation ORDERING: if a
future edit reorders `validate_order` so the connection check is gated behind an
early return (e.g. symbol-invalid short-circuit), a disconnected exchange could
admit an order. The comment presents a load-bearing invariant as a settled fact
without a guarding assertion or test.

**Fix:** Add a focused unit test asserting `_admit_order` REFUSES on a
disconnected exchange, so the invariant the comment relies on is regression-locked.

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
