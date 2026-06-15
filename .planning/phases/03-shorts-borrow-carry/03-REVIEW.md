---
phase: 03-shorts-borrow-carry
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - itrader/core/enums/portfolio.py
  - itrader/core/instrument.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/position/position.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase 3 shorts + borrow-carry seam across the order-admission, portfolio
settlement, cash, and carry-accrual paths. The money-Decimal discipline is strong: the
carry path enters the Decimal domain via `Decimal(str(total_seconds()))` (no `Decimal(float)`
artifact), the `/Decimal("365")` divisor is correct, and the default-off byte-exact gate
(`borrow_rate=0` / `allow_short_selling=False` / `enable_margin=False`) is well guarded — the
spot arm never divides and the `available_balance` subtraction stays byte-exact. The
sign-convention fix (unsigned `net_quantity` magnitude + `side` discriminator) is applied
consistently across the direction gate, position gate, and exit-sizing predicate.

The principal correctness defect is in the borrow-carry accrual loop: the magnitude/price
operands are read from the position's *marked* state, but a short whose ticker is absent from
the current tick's price data carries forward a **stale `current_price`** while the accrual
clock still advances the full elapsed gap — and the carry op is timestamped with that bar's
business time, so the equity curve silently absorbs carry computed on a wrong mark. This is a
determinism-safe but numerically-wrong result on any sparse/gap bar with an open short.

Several lock/release symmetry residuals and one short-scale-in admission gap are flagged as
warnings.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Borrow carry accrues on a stale `current_price` for a short absent from the tick's prices

**File:** `itrader/portfolio_handler/portfolio.py:633-696`
**Issue:**
`update_market_value_of_portfolio` marks positions via
`position_manager.update_position_market_values(prices, mark_time)`, which **only updates a
position whose ticker appears in `price_data`** (`position_manager.py:260` — `if ticker in
price_data`). It then calls `_accrue_short_carry(bar_time, universe)` for *every* open short
unconditionally.

For a short whose ticker is absent from `prices` on a given bar (sparse universe, data gap,
or simply a bar event that does not carry that ticker), the carry magnitude is computed from
`position.current_price` (line 685) — which is **the close from a previous bar**, not the
current one — while `days = (bar_time - last_accrual)` (line 678) still spans the full elapsed
interval, and `_last_accrual_time` is advanced to `bar_time` (line 696). The financing cost
is therefore booked against a wrong mark and the clock is consumed, so the correct mark never
gets a second chance to re-price that interval. Because the result is deterministic (no wall
clock), the determinism double-run gate will not catch it — but the equity curve and the P4
liquidation trigger (which the docstring at lines 364-372 of `cash_manager.py` says must see
carry-eroded equity) consume a silently-wrong number. In a project whose core value is
"numbers you can trust", carry on a stale price is a data-integrity defect, not a rounding
nuance.

Note this is the same class of hazard `update_portfolios_market_value` already treats as
fail-fast for marking (`portfolio_handler.py:464-477` re-raises a failed mark) — but here the
gap is silent because the absent ticker is simply skipped, not an exception.

**Fix:** Only accrue carry for shorts that were actually re-marked this tick (price present),
or carry the accrual forward without advancing `_last_accrual_time` when the ticker is absent,
so the next priced bar re-prices the full interval. Minimal version: skip the accrual (and do
NOT advance the clock) when the ticker is not in the marked set.
```python
def _accrue_short_carry(self, bar_time, universe, marked_tickers):
    positions = self.position_manager.get_all_positions()
    for ticker, position in positions.items():
        if position.side != PositionSide.SHORT or not position.is_open:
            continue
        if ticker not in marked_tickers:
            # No fresh mark this tick — defer carry; do NOT advance the clock,
            # so the next priced bar accrues the full elapsed interval on a
            # correct price.
            continue
        ...
```
(`marked_tickers` = the set of tickers actually present in `prices`; thread it down from
`update_market_value_of_portfolio`.)

## Warnings

### WR-01: SHORT_ONLY scale-in (unsized SELL while short) falls through to entry sizing instead of being gated

**File:** `itrader/order_handler/admission/admission_manager.py:485-588`, `665-766`
**Issue:**
`_enforce_position_admission` documents (lines 511-513) that "short increases are out of v1
scope with the margin model (D-09)", but the gate only polices `Side.BUY` (line 532 returns
`None` for any non-BUY). A `SHORT_ONLY` strategy that emits a second **unsized SELL** while
already short therefore passes the direction gate (only `SHORT_ONLY+BUY` is checked at
471-482), passes the position gate (SELLs exempt), and in `_resolve_signal_quantity`
`is_reduction` is `False` (SELL vs an open SHORT is not a reduction, lines 750-753), so it
routes into **entry sizing** (`resolve_entry`, line 778) — opening a fresh entry-sized lot and
scaling the short. This silently admits the very "short increase" the comment says is out of
scope, and it does so with entry-fraction-of-cash sizing on top of an existing short. It is
oracle-dark (golden path is LONG_ONLY), but it is reachable the moment shorts are enabled —
which is exactly this phase.
**Fix:** Either explicitly gate an unsized same-side add to a short (audited rejection,
mirroring the long INCREASE gate) or route it through scale-in sizing with the same
allow_increase contract the long side uses. Do not let it fall into first-entry sizing.

### WR-02: Carry KeyError on an open short whose ticker is not a Universe member aborts the run

**File:** `itrader/portfolio_handler/portfolio.py:669`
**Issue:**
`universe.instrument(ticker).borrow_rate` raises `KeyError` for a ticker not in
`Universe._instruments` (`universe/universe.py:62-80`). Unlike `maintenance_margin`
(`portfolio_handler.py:326-332`), which fails loud with a context-rich `StateError` when the
universe is unwired, the carry site has no guard for the *member-missing* case: an open short
on a ticker the universe does not carry an Instrument for raises a bare `KeyError` that
propagates through `update_portfolios_market_value` and aborts the backtest with an opaque
message. This is reachable whenever the position set and the instrument map diverge (a ticker
that left the universe while a short stayed open).
**Fix:** Either resolve a missing instrument to a deterministic default (`borrow_rate = 0`,
i.e. no carry) or raise a context-rich typed error naming the ticker/position, mirroring the
`maintenance_margin` StateError pattern.

### WR-03: `current_price`-staleness check missing before carry uses it as a money operand

**File:** `itrader/portfolio_handler/portfolio.py:683-689`
**Issue:**
Closely related to CR-01 but distinct: `_accrue_short_carry` reads `position.current_price`
with no assertion that it was set at or after the position's entry. On the very first carry
bar after a short opens, `current_price` was last written by the opening fill
(`Position.open_position` -> `to_money(transaction.price)`), which is the fill price, not a
mark — acceptable — but there is no defense if a position somehow reaches carry before any
mark (e.g. a future reorder of the route list). Given the carry op erodes real cash, a
pre-condition guard (`position.current_price > 0`) would make the money operand's validity
explicit rather than implicit on route ordering.
**Fix:** Add an explicit `if position.current_price <= Decimal("0"): continue` (or raise)
guard before computing `carry`, so a zero/unset mark can never silently produce a zero or
wrong financing debit.

### WR-04: `assert_lock_fits_buying_power` uses `available_balance` which already nets the *new* position's prior lock only — scale-in re-lock can still under-account a concurrent reservation

**File:** `itrader/portfolio_handler/cash/cash_manager.py:437-469`; `itrader/portfolio_handler/portfolio.py:430-436`
**Issue:**
On a scale-in the sequence is `release_margin(pos)` then `assert_lock_fits_buying_power(new_lock, pos)`
then `lock_margin(pos, new_lock)`. `assert_lock_fits_buying_power` computes
`buying_power = available_balance + own_prior_lock`, but `release_margin` has *already*
removed the prior lock from storage before the assertion runs (`portfolio.py:430` releases,
then `:435` asserts). So at assertion time `available_balance` no longer contains the prior
lock, and the code adds `own_prior_lock` back via `get_locked_margin_for(position_id)` — which
now returns `Decimal("0")` because the lock was just popped. The add-back is therefore a no-op
on the scale-in path, making the solvency assertion *stricter* than intended (it omits the
prior lock it claims to credit back). This is conservative (fails loud rather than over-locks),
so it is not a leak, but the documented invariant ("the position's own prior lock is about to
be released and re-locked, so it is added back") does not hold given the call order — the
add-back reads 0.
**Fix:** Either call `assert_lock_fits_buying_power` BEFORE `release_margin`, or pass the
released amount explicitly into the assertion rather than re-reading it from storage after it
has been popped.

### WR-05: `borrow_rate == 0` branch advances the accrual clock for an immutable-rate Instrument — dead rationale, masks future non-zero accrual

**File:** `itrader/portfolio_handler/portfolio.py:670-674`
**Issue:**
The `borrow_rate == Decimal("0")` branch advances `position._last_accrual_time = bar_time` so
"a later non-zero rate measures from here" (line 671-672). But `Instrument` is frozen and the
`borrow_rate` is documented as "static-over-time" (`core/instrument.py:74-79`), so the rate can
never transition 0 -> non-zero for a given symbol within a run. The clock-advance is dead
rationale. Worse, if a future change ever does make `borrow_rate` dynamic, advancing the clock
on the zero-rate bars would *suppress* carry for the interval that straddles the transition
(the elapsed days are consumed at rate 0). Today it is harmless but the comment asserts a
behavior the type system forbids.
**Fix:** Drop the clock-advance in the zero-rate branch (a plain `continue`), or document that
rate transitions are out of scope and the advance is intentional no-op bookkeeping. Aligns the
code with the frozen-Instrument contract.

## Info

### IN-01: `Portfolio.update_market_value` (line 494) is dead on the run path

**File:** `itrader/portfolio_handler/portfolio.py:494-506`
**Issue:** `PortfolioHandler.update_portfolios_market_value` calls
`update_market_value_of_portfolio` (the carry-bearing method), never `update_market_value`. A
grep across `itrader/` and `tests/` finds no caller of `update_market_value`. It marks
positions but never accrues carry, so a stray future caller would silently skip financing.
**Fix:** Remove the dead method, or fold it into `update_market_value_of_portfolio` so there is
one mark entry point.

### IN-02: `_validate_position_consistency` has an unreachable `net_quantity < 0` branch

**File:** `itrader/portfolio_handler/position/position.py:123-127` (consumed by `position_manager.py:228`)
**Issue:** `Position.net_quantity` returns `abs(buy_quantity - sell_quantity)`, so it is always
`>= 0`. The downstream guard `if position.net_quantity < 0 ...` (position_manager.py:228) is
structurally dead. Not in this phase's changed surface but directly relevant to the
"`net_quantity` is an unsigned magnitude" sign-convention discipline this phase relies on —
the dead branch is a latent trap for anyone who later reintroduces a signed read.
**Fix:** Remove the unreachable branch or convert it to an assertion documenting the unsigned
invariant.

### IN-03: Carry over a multi-day gap uses the single current close for the whole interval

**File:** `itrader/portfolio_handler/portfolio.py:678-689`
**Issue:** When `days > 1` (a gap since the last accrual), the entire interval is charged at
the *current* bar's close and current `net_quantity`, not a per-day mark. This is the
documented static approximation, but combined with CR-01's stale-price path it compounds: a
multi-day gap with a stale price charges several days of carry on an old mark.
**Fix:** Acceptable as a documented approximation; revisit if per-day carry fidelity is
required.

### IN-04: `get_reserved_cash` seeds the sum with `Decimal("0.00")` while `get_locked_margin` seeds `Decimal("0")` — inconsistent zero exponents

**File:** `itrader/portfolio_handler/storage/in_memory_storage.py:82,96`
**Issue:** The two working-state aggregates use different zero seeds (`Decimal("0.00")` vs
`Decimal("0")`). Verified byte-exact for `available_balance` because the balance carries more
decimal places than either zero (subtracting either preserves the balance's exponent). It is
not a defect today, but the inconsistency is a readability/maintenance trap — a future
consumer that reports `reserved_cash` and `locked_margin` side by side gets `0.00` vs `0`.
**Fix:** Pick one zero-exponent convention for both aggregates (`Decimal("0")` is the cleaner
full-precision seed).

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
