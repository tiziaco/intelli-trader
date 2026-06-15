---
phase: 02-margin-accounting-leverage
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - itrader/config/portfolio.py
  - itrader/core/enums/order.py
  - itrader/core/portfolio_read_model.py
  - itrader/core/sizing.py
  - itrader/events_handler/events/fill.py
  - itrader/events_handler/events/order.py
  - itrader/events_handler/events/signal.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/order.py
  - itrader/order_handler/sizing_resolver.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/position/position.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/portfolio_handler/transaction/transaction.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

This phase plumbs an admission-clamped effective leverage scalar end-to-end
(`Order` → `OrderEvent` → `FillEvent` → `Transaction` → `Position`), adds the
position-keyed locked-margin lifecycle in `CashManager`, branches settlement on
`enable_margin` in `Portfolio`, and exposes `maintenance_margin`/`margin_ratio`
read-model accessors. The spot byte-exact discipline is generally well preserved:
the spot arms use real `if`-branches (no `/1` division), money stays Decimal via
`to_money`, and most new fields default to `Decimal("1")`/`Decimal("0")` so they
are inert on the SMA_MACD oracle path.

The dominant defect is a **leverage-threading hole on the LIMIT/STOP entry
paths**: the effective leverage is correctly computed and reserved against, but
is silently dropped from the `Order` entity for non-MARKET orders, so the
position-life locked margin will NOT equal the admission reservation for any
levered LIMIT/STOP entry — a direct violation of the phase's stated core
invariant. A second blocker is that the partial-close margin re-credit produces
an incorrect cash settlement when a single SELL fill both reduces and would flip
a position. Five warnings cover an over-broad commission-only funds invariant,
a maintenance-margin NoneType crash surface, a margin lock that never settles on
a reservation-orphan path, and a couple of correctness/robustness gaps. Note:
shorting is gated off at strategy registration (`strategies_handler.add_strategy`
rejects non-LONG_ONLY), which means several margin code paths (SHORT open,
cover) are presently unreachable through the normal run path — this masks, but
does not fix, the underlying bugs flagged below.

## Critical Issues

### CR-01: LIMIT/STOP entry orders drop effective leverage — locked margin ≠ admission reservation

**File:** `itrader/order_handler/admission/admission_manager.py:369-397`
**Issue:**
`_build_primary_order` computes `effective_leverage = self._effective_leverage(signal_event)`
(line 369) and threads it onto the MARKET order via
`Order.new_order(signal_event, exchange, quantity=quantity, leverage=effective_leverage)`
(line 374-375). But the LIMIT arm (line 376-386, `Order.new_limit_order(...)`) and
the STOP arm (line 387-397, `Order.new_stop_order(...)`) call factories that
neither accept nor set `leverage` — see `order.py:227` (`new_stop_order`) and
`order.py:260` (`new_limit_order`), which omit the kwarg entirely, so the entity
defaults to `Order.leverage = Decimal("1")`.

Meanwhile the admission cash reservation in `process_signal` (line 277-279)
reserves `notional / effective_leverage + commission` REGARDLESS of order type
(it re-derives `effective_leverage` from the same signal). So for a levered
LIMIT or STOP BUY:
- reservation locks `notional / L` (e.g. L=5 → 20% of notional),
- the resting fill carries `leverage=1` to the `Transaction` → `Position.leverage=1`,
- `_process_transaction_margin` (portfolio.py:405,411-413) locks
  `aggregate_notional / position.leverage = aggregate_notional / 1` (full notional).

This directly violates the phase invariant: *"position-life locked margin
(aggregate_notional/leverage) equals the admission reservation
(notional/effective_leverage)"*. The position will lock far more margin than was
reserved, corrupting `available_balance` accounting for every levered
limit/stop entry. (Currently masked only because SMA_MACD is MARKET-only and
margin is off on the golden path — but the feature ships broken.)

**Fix:** Thread leverage through the typed factories on all three arms. Add a
keyword-only `leverage` parameter to `new_limit_order`/`new_stop_order` mirroring
`new_order`, and pass it at the call sites:
```python
# order.py — new_limit_order / new_stop_order signatures
@classmethod
def new_limit_order(cls, time, ticker, action, price, quantity, exchange,
                    strategy_id, portfolio_id, *,
                    leverage: Decimal = Decimal("1")) -> "Order":
    order = cls(time, OrderType.LIMIT, OrderStatus.PENDING, ticker, action,
                to_money(price), to_money(quantity), exchange, strategy_id,
                portfolio_id, leverage=to_money(leverage))
    ...

# admission_manager.py:376-397 — pass effective_leverage on both arms
elif signal_event.order_type is OrderType.LIMIT:
    return Order.new_limit_order(..., leverage=effective_leverage)
elif signal_event.order_type is OrderType.STOP:
    return Order.new_stop_order(..., leverage=effective_leverage)
```

### CR-02: Partial-close margin settlement mis-credits commission when a SELL fill exceeds the open quantity

**File:** `itrader/portfolio_handler/portfolio.py:415-436`
**Issue:**
In `_process_transaction_margin`, the close branch clamps the closed quantity
(`closed_qty = min(transaction.quantity, prior_qty)`, line 417-419) and computes
`fraction = closed_qty / prior_qty` — clamped to ≤ 1. But `realised_increment`
(line 435) is read from `position.realised_pnl - prior_realised` AFTER
`process_position_update` has applied the FULL `transaction.quantity` to the
position (line 399), not the clamped quantity. If a SELL fill quantity exceeds
the open long (an over-close / flip attempt), `update_position` adds the full
sell quantity to `sell_quantity`, and `_should_close_position` only closes when
`net_quantity <= tolerance` — a quantity strictly greater than the open leaves a
non-zero residual net SHORT and the position stays open (`position.is_open` True),
so the code re-locks margin (line 425-428) on a flipped position whose
`leverage` was set for the original LONG. The realised-PnL increment and the
`fraction * prior_entry_commission` re-credit then settle a cash delta that does
not correspond to the actual closed economics.

This is latent today only because shorting/flips are gated off at registration
(`strategies_handler.py:253`), but the margin close arm is written to "handle
shorts properly" (its own comment, line 398) and silently produces a wrong
ledger entry the moment a flip fill reaches it. At minimum the over-close case
must be rejected or normalized, not silently settled.

**Fix:** Guard the close arm against `transaction.quantity > prior_qty` explicitly
(reject as an engine-bug `InvalidTransactionError`, mirroring the
`assert_funds_invariant` fail-loud seam), OR split a flip fill into a full-close
+ fresh-open before settlement. Do not let a single fill both over-close and
re-lock on an inconsistent leverage:
```python
if not is_increase and closed_qty > prior_qty:
    raise InvalidTransactionError(
        "Margin close fill exceeds open quantity (flip not supported)",
        {"closed": str(transaction.quantity), "open": str(prior_qty)},
    )
```

## Warnings

### WR-01: Margin funds invariant only guards commission — solvency of the locked margin is unchecked at settlement

**File:** `itrader/portfolio_handler/portfolio.py:390-396`
**Issue:**
The margin open/scale-in path feeds `assert_funds_invariant` only the
commission (`if is_increase and commission > 0: assert_funds_invariant(commission)`).
The comment asserts locked-margin sufficiency "was enforced pre-trade by the
admission reservation gate." But the reservation gate is keyed on the ORDER id
and is released on terminal reconciliation, while the lock is position-keyed and
applied here — there is no settlement-side check that `aggregate_notional / L`
actually fits in `available_balance` at lock time. Per CR-01, the reserved amount
and the locked amount can diverge (different leverage), so the "reservation
guaranteed it" premise does not hold across the leverage-mismatch bug. A levered
entry can lock more margin than was ever reserved with zero guard firing.
**Fix:** After computing the new lock basis, assert it against available buying
power (or assert lock == the order's released reservation) so a divergence fails
loudly at settlement instead of silently over-locking:
```python
new_lock = position.aggregate_notional / leverage
# engine-bug guard: the lock must not exceed available buying power
if new_lock > self.cash_manager.available_balance + previously_locked:
    raise InsufficientFundsError(required_cash=float(new_lock), ...)
```

### WR-02: `maintenance_margin` dereferences `self._universe` with no None guard — AttributeError if read before wiring

**File:** `itrader/portfolio_handler/portfolio_handler.py:306-325`
**Issue:**
`maintenance_margin` calls `self._universe.instrument(position.ticker)` (line 319)
unconditionally. `_universe` is initialized to `None` (line 87) and only set at
the Trap-4 wiring point via `set_universe`. The docstring claims it is
"query-only and unread on the golden path," but the accessor is public on the
`PortfolioReadModel` Protocol (`portfolio_read_model.py:235`) and `margin_ratio`
(line 338) calls it whenever there is ≥1 open position. If any consumer (UI,
test double, future live layer) calls `maintenance_margin`/`margin_ratio` on a
portfolio with open positions before `set_universe` runs — or after a partial
wiring failure — it raises a bare `AttributeError: 'NoneType' object has no
attribute 'instrument'` with no diagnostic context.
**Fix:** Fail loud with context when the universe is unwired but positions exist:
```python
if self._universe is None:
    raise StateError(portfolio_id, "universe-unwired",
        operation="maintenance_margin")
```

### WR-03: Orphaned reservation released, but a successfully-locked margin is never released on the assembly-failure path

**File:** `itrader/order_handler/admission/admission_manager.py:303-317`
**Issue:**
The WR-03 leak guard releases the CASH reservation when bracket assembly fails
after a successful reserve (`self.portfolio_handler.release(...)`). This is
correct for the order-keyed reservation. But it is incomplete reasoning for
margin mode going forward: the reservation is order-keyed and released here,
whereas the position-keyed margin lock is applied later in
`_process_transaction_margin` on the FILL. Today there is no leak (the lock only
happens on a fill, which can't occur if no OrderEvent was emitted). Flagging
because the symmetry comment ("no terminal fill will ever drive the on_fill
release") reasons only about cash reservations and silently assumes the margin
lock lifecycle is unreachable here — that assumption is undocumented at the
release site and will break if a future change locks margin at admission rather
than at fill.
**Fix:** Add an explicit assertion/comment that no margin lock can exist at this
point (no fill yet), or, if the lock lifecycle moves earlier, release it here
alongside the reservation.

### WR-04: `_effective_leverage` clamp can produce a sub-1 effective leverage from a misconfigured cap

**File:** `itrader/order_handler/admission/admission_manager.py:582-594`
**Issue:**
`capped = min(requested, instr_cap, pf_cap)` with no floor of `Decimal("1")`.
`pf_cap` comes from `TradingRules.max_leverage` (config-validated `ge=1`, so safe),
and `instr_cap` comes from `Instrument.max_leverage`. On the run path
`derive_instruments` always supplies `_DEFAULT_MAX_LEVERAGE = Decimal("1")`, but
`Instrument.max_leverage` is typed `Decimal | None` (instruments.py:90) and a
directly-declared instrument table entry or a future provider could supply a
value `< 1` (or `0`). The result would be a sub-1 effective leverage:
`cost = notional / 0.5 = 2 × notional` reserved, and a divide-by-zero if a 0 cap
ever reaches it. There is no validation that the instrument cap is `≥ 1`.
**Fix:** Floor the cap and guard zero:
```python
instr_cap = ... or Decimal("1")
capped = max(Decimal("1"), min(requested, instr_cap, pf_cap))
```
(or validate `Instrument.max_leverage >= 1` at instrument construction).

### WR-05: `_process_transaction_margin` re-credit assumes `prior_entry_commission` is fully captured at open — breaks after a scale-in

**File:** `itrader/portfolio_handler/portfolio.py:372-436`
**Issue:**
The partial/full-close re-credit uses `prior_entry_commission` = the position's
full `buy_commission` (LONG) captured before mutation (line 372-378), and credits
back `fraction * prior_entry_commission`. After one or more scale-ins,
`buy_commission` is the SUM of all entry commissions, not the per-open
commission, and `fraction` is computed against `prior_qty` (the aggregate). The
re-credit `fraction * total_entry_commission` only equals "the closed fraction's
share of pre-debited open commission" if every scale-in's commission-per-unit
was identical — which is not guaranteed (commission is a fee model output, can
vary per fill). The round-trip cash-delta == realised-PnL identity then drifts
on any close following a non-uniform-commission scale-in.
**Fix:** Track the pre-debited open commission as a separate accumulator on the
margin lock (or settle commission against the actual filled-fraction commission),
rather than re-deriving it from the position's aggregate `buy_commission` via a
quantity fraction.

## Info

### IN-01: Misleading comment — `fill.py` claims REFUSED/CANCELLED fills carry leverage, but spot fills cannot

**File:** `itrader/events_handler/events/fill.py:69-72,146-149`
**Issue:** The comment "EXECUTED and REFUSED/CANCELLED fills all carry it for the
Transaction hop" is technically true but misleading: only EXECUTED fills reach
`PortfolioHandler.on_fill` (the non-EXECUTED guard at `portfolio_handler.py:358`
returns early), so the leverage on REFUSED/CANCELLED fills is never consumed by
the Transaction hop. Minor documentation drift; not a correctness issue.
**Fix:** Trim the comment to reflect that only the EXECUTED fill's leverage is
consumed downstream.

### IN-02: `Decimal(str(...))` re-wrap of `signal_leverage` in position_manager bypasses the `to_money` house helper

**File:** `itrader/portfolio_handler/position/position_manager.py:171`
**Issue:** `Decimal(str(signal_leverage)) != position.leverage` re-implements the
`to_money` string-path normalization inline. It is correct (string path, no
`Decimal(float)`), but the codebase convention is to enter the Decimal domain via
`to_money(x)` exclusively (money.py policy). Using the raw `Decimal(str(...))`
here is an inconsistency that a future reader could mistake for a sanctioned
pattern. Behavior-correct, style-only.
**Fix:** Use `to_money(signal_leverage)` for consistency with the money policy.

### IN-03: `_DEFAULT_MAINTENANCE_MARGIN_RATE = 0.005` applied to every symbol with no per-instrument override path exercised

**File:** `itrader/universe/instruments.py:62,235-237` (cross-ref `portfolio_handler.py:306-325`)
**Issue:** `maintenance_margin` multiplies by `instrument.maintenance_margin_rate`,
which resolves to a hardcoded `Decimal("0.005")` default for every symbol
(BTCUSD does not declare an override). The figure is plausible but is a magic
default that silently governs the `margin_ratio` / liquidation-input read for
all instruments. Since the accessor is oracle-dark today this has no run-path
effect, but the single global rate is a latent correctness assumption for the
deferred liquidation milestone.
**Fix:** None required this phase; track the per-instrument rate as a declared
table entry before the liquidation milestone consumes `margin_ratio`.

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
