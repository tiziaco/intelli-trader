---
phase: 04-liquidation-cross-validation-re-baseline
reviewed: 2026-06-16T00:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - itrader/config/portfolio.py
  - itrader/core/enums/order.py
  - itrader/core/instrument.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
  - scripts/cross_validate_accounting.py
  - scripts/crossval/levered_run.py
  - scripts/crossval/liquidation_run.py
  - scripts/crossval/short_run.py
  - scripts/determinism_liquidation_double_run.py
  - tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
  - tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
  - tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
  - tests/e2e/levered_long/test_levered_long_scenario.py
  - tests/e2e/partial_cover/test_partial_cover_scenario.py
  - tests/e2e/short_carry/test_short_carry_scenario.py
  - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
  - tests/unit/order/test_liquidation_reconcile.py
  - tests/unit/portfolio/test_liquidation.py
  - tests/unit/portfolio/test_wr04_lock_fits_buying_power.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
  resolved:
    - "CR-01 (was critical) — resolved by fix b461db0 via /gsd:debug liq-loss-cap-dead-code; owner chose option (a) fill-at-liq-price."
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-16
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

This phase ships the isolated-margin liquidation engine (LIQ-01/02/03) plus the
owner-gated accounting-core cross-validation (XVAL-01). The Decimal money discipline is
clean throughout the new liquidation math, the deterministic breach sort is correct, the
order-storage write-seam is wired symmetrically in both `compose.py` and
`live_trading_system.py`, and the unit/e2e coverage is thorough and hand-computed.

The dominant finding is a **correctness/integrity gap around the DEF-01-C loss-cap
claim**: the `_capped_realized_loss` clamp that the code, the module docstrings, and the
e2e "GUARANTEES equity never drops below -WB" comments all advertise as the mechanism
that closes DEF-01-C is **never invoked on any production path**. The actual loss-bounding
behaviour comes from a *different* mechanism (filling at the maintenance liq price rather
than the bar close), which silently overstates recovery on a gap-through and leaves the
advertised guarantee unenforced. This is the kind of "trust the numbers" defect this
project exists to eliminate, so it is a BLOCKER.

The remaining findings are robustness/maintainability concerns: a dead duplicate breach
collector, a dead/misleading determinism-gate branch, an unguarded `_storage` private
reach-through, and a few quality items.

## Critical Issues

### CR-01: The DEF-01-C loss-cap (`_capped_realized_loss`) is dead code — the advertised "equity never below -WB" guarantee is never enforced

> **✅ RESOLVED — fix `b461db0` (via `/gsd:debug liq-loss-cap-dead-code`, owner decision 2026-06-16).**
> Investigation confirmed the finding and falsified the "gap-through books uncapped loss" concern as a description of *current* behavior: the engine deliberately fills the forced close at the maintenance liq price, so the loss is bounded by construction (not by the clamp). The clamp was also structurally unreachable (binds only when `fee_rate > MMR`). Owner chose **option (a)**: fill-at-liq-price is the deliberate bound. The dead `_capped_realized_loss` helper + its test-only arm were removed, the false attribution corrected across docstrings / 04-03-SUMMARY / 04-03-PLAN truth / threat T-04-03-NEG / e2e comments, and a gap-through regression (`test_liquidation_fills_at_liq_price_on_gap_through`) now pins the fill-at-liq-price guarantee. Zero numerical change — oracle byte-exact, no golden re-freeze, 1146 passed, mypy --strict clean. Original finding retained below as the audit record.

**File:** `itrader/portfolio_handler/portfolio_handler.py:444-456` (definition); liquidation path `:517-624`

**Issue:**
`_capped_realized_loss` implements the EXPLICIT `min(realized_loss + penalty, WB)` clamp
that the prompt, the docstrings ("closes DEF-01-C"), and every liquidation e2e
("the EXPLICIT D-07 clamp ... GUARANTEES equity never drops below -WB (DEF-01-C closed)")
present as the load-bearing safety mechanism. A grep of the entire `itrader/` + `scripts/`
tree shows it is called from **nowhere except the unit test** `test_liquidation.py`:

```
$ grep -rn "_capped_realized_loss" itrader/ scripts/ | grep -v test
itrader/portfolio_handler/portfolio_handler.py:445:    def _capped_realized_loss(...)
```

`_liquidate_position` computes the penalty, mints the forced-close order, and emits a
`FillEvent(EXECUTED)` at the liq price. Settlement then flows through the ordinary
`portfolio.on_fill -> transact_shares -> process_transaction -> _process_transaction_margin`
path, which realizes the **full, uncapped** PnL (`position.realised_pnl - prior_realised`)
plus the open-commission re-credit. No code in that path consults WB or applies any
`min(..., WB)` floor.

The e2e tests pass only because the engine fills the forced close **at the computed
maintenance liq price** (e.g. 80.81), not at the actual breaching bar close. With the
maintenance-price fill, the loss is bounded near WB *by construction*, so the clamp never
needs to fire — which is exactly why the dead code is invisible. But that means:

1. The DEF-01-C guarantee the code claims to provide is provided by a *different*
   mechanism than the one documented, and that mechanism is never tested for the case it
   is supposed to cover (loss exceeding WB).
2. On a genuine gap-through (the `scripts/crossval/liquidation_run.py` scenario gaps to 10
   against an 80.808 liq floor), filling at the liq price instead of the realistic gap
   price **overstates recovery** and books a loss far smaller than the wallet actually
   suffered. If a future change ever fills at the breach close (the honest gap fill), the
   loss would be ~18,080 against WB=4,000 (verified by hand) and there is no clamp to
   floor it — equity would drift to roughly -8,080, the precise DEF-01-C defect the phase
   claims to have closed.

**Fix:** Wire the clamp into the actual settlement, or remove the false guarantee.
Concretely, apply the cap where the forced-close PnL is realized so the total realized
loss for a liquidation fill is floored at WB regardless of fill price:

```python
# in _liquidate_position, after computing penalty and the close PnL magnitude:
raw_loss = ...  # |realized close loss| for the forced close
capped = self._capped_realized_loss(raw_loss, penalty, wb)
# emit/settle so the booked loss == capped, not raw_loss + penalty
```

If the intended design is genuinely "always fill at the maintenance liq price so the
clamp can never bite", then `_capped_realized_loss` must be deleted and every docstring /
e2e comment that calls the clamp the DEF-01-C mechanism must be rewritten to state that
the fill-at-liq-price IS the mechanism — otherwise the codebase asserts a guarantee it
does not implement.

## Warnings

### WR-01: `_collect_breaches` (single-close) is dead in production — only `_collect_breaches_over_prices` runs

**File:** `itrader/portfolio_handler/portfolio_handler.py:476-515`

**Issue:** `_run_liquidation_pass` calls `_collect_breaches_over_prices` (the per-ticker
close-map variant). The single-`close` `_collect_breaches` is referenced only by
`test_liquidation.py::test_multi_breach_deterministic`. Two near-identical breach
collectors with the same sort key and the same skip rules invite drift: a future fix to
the breach predicate (e.g. the `wb <= 0` / non-positive-mark guards) applied to one but
not the other would make the unit test green while the production path silently diverges.

**Fix:** Have `_collect_breaches` build a `{ticker: close}` map and delegate to
`_collect_breaches_over_prices`, so there is a single breach predicate. Then point the
unit test at the production collector.

### WR-02: Determinism gate has a dead/misleading `final_balance` branch and a fragile hard-coded magic number

**File:** `scripts/determinism_liquidation_double_run.py:99-108`

**Issue:** The guard reads:

```python
if run_a["closed_count"] != 1 or run_a["final_balance"] != str(Decimal("6081.191919191919191919191919")):
    if run_a["closed_count"] != 1:
        ... return 1
```

The outer `or` includes a `final_balance` comparison, but the inner block only acts on
`closed_count`. So if `final_balance` diverges from the literal while `closed_count == 1`,
the script enters the block, does nothing, and prints "DETERMINISM OK". The
`final_balance` half of the condition is therefore dead — the sanity check it appears to
provide does not exist. The hard-coded `6081.191919...` literal is also a 28-digit
balance the gate neither asserts nor documents the derivation of inline (the comment says
`10000 - 3918.808...` but the tail digits are unchecked).

**Fix:** Either assert the balance hard (`if run_a["final_balance"] != EXPECTED: return 1`)
or drop it from the condition entirely. If kept, derive it from named constants rather
than a bare 28-digit literal.

### WR-03: `_liq_inputs` reaches through `cash_manager._storage` private API

**File:** `itrader/portfolio_handler/portfolio_handler.py:470`

**Issue:** `wb = portfolio.cash_manager._storage.get_locked_margin_for(str(position.id))`
reaches across two layers into a private attribute (`_storage`) of `CashManager`. The
public surface already exposes locked-margin reads (`CashManager.locked_margin_total`,
and `assert_lock_fits_buying_power` internally uses `_storage.get_locked_margin_for`). A
private reach-through from a sibling handler couples the liquidation engine to
`CashManager`'s storage internals; a refactor of the storage seam (explicitly flagged as
a "pluggable backend swap" in the cash-manager docstring) silently breaks liquidation
with an `AttributeError` rather than a typed contract error.

**Fix:** Add a public `CashManager.get_locked_margin_for(position_id) -> Decimal`
delegator and call that from `_liq_inputs`.

### WR-04: Forced-close fill is emitted before the breach pass finishes — relies on fill-price-not-close, undocumented at the call site

**File:** `itrader/portfolio_handler/portfolio_handler.py:601-624`

**Issue:** `_run_liquidation_pass` collects all breaches against the tick closes, then
liquidates each by emitting a `FillEvent` at `liq_price` (not at the breaching `close`).
The breach is *detected* on `close <= liq_price` (long), but the position is *settled* at
`liq_price`, which on any adverse bar is strictly better than `close`. For a daily-OHLC
"breach on close" proxy this is a documented modeling choice in the e2e leaves — but it is
the entire reason the loss is bounded (see CR-01), and nothing at this call site states
that filling at `liq_price` rather than `close` is load-bearing. A maintainer "fixing"
the fill to use the realistic close would silently re-open DEF-01-C with no clamp behind
it (CR-01).

**Fix:** Add an explicit comment at the fill site recording that filling at `liq_price`
(not the breach close) is what bounds the loss in the no-clamp design, and cross-reference
CR-01. Better: make the loss floor explicit (CR-01 fix) so the fill-price choice is no
longer the silent safety net.

### WR-05: `update_portfolios_market_value` runs the liquidation pass even when a per-portfolio mark raised and was re-raised

**File:** `itrader/portfolio_handler/portfolio_handler.py:753-780`

**Issue:** The per-portfolio mark loop re-raises on failure (WR-08 fail-fast, correct).
But `_run_liquidation_pass(bar_events, bar_time)` is unconditionally called *after* the
loop. In the backtest fail-fast path the re-raise aborts before reaching it, so this is
benign today. In the **live** path (`_publish_and_continue` swallows handler errors at the
dispatch boundary), a portfolio whose mark failed mid-loop would still have the
liquidation pass run against its **stale** marks for the portfolios that did mark — the
liquidation breach check would evaluate carry-eroded equity that is partially stale. The
"breach sees carry-eroded equity (D-02 placement)" invariant is only sound if every active
portfolio marked successfully this tick.

**Fix:** Track whether the mark loop completed cleanly and skip / guard the liquidation
pass for any portfolio that did not re-mark this tick, or document that liquidation in
live mode is deferred (D-live) and gate it off the live path explicitly.

## Info

### IN-01: `_run_liquidation_pass` accepts `bar_events` but only re-derives closes already computed by the caller

**File:** `itrader/portfolio_handler/portfolio_handler.py:601-619`

**Issue:** `update_portfolios_market_value` already built a `prices` dict from the same
`bar_events`. `_run_liquidation_pass` rebuilds an identical `closes` dict by iterating the
bar events again. Minor duplication; passing the already-built `prices` map would avoid
the second pass and remove a place where the mark price and the breach price could
diverge.

### IN-02: `_liquidate_position` does a function-local `from itrader.core.money import quantize`

**File:** `itrader/portfolio_handler/portfolio_handler.py:554`

**Issue:** The `quantize` import is inside the method body. `to_money` is already imported
at module scope (line 31); there is no import-cycle rationale for deferring `quantize`
(same module). Move it to the module-level imports for consistency with the file's import
style.

### IN-03: Cross-val scenario qty mismatch between iTrader sizing and the reference runner is only correct by coincidence of the flat-100 entry

**File:** `scripts/crossval/levered_run.py:38-40`, `scripts/crossval/liquidation_run.py:40-41`

**Issue:** The runners hard-code `QTY = 200` with the comment "iTrader sizes notional =
f x equity = 2 x 10_000 = 20_000 -> 200 units @ 100". This is only correct because the
entry price is exactly 100; if the synthetic frame's entry close changes, the reference
qty and the iTrader-sized qty diverge silently and the trade-level reconcile would compare
mismatched sizes. Derive `QTY` from `notional / entry_price` so it tracks the frame.

### IN-04: `cross_validate_accounting.py` unused import

**File:** `scripts/cross_validate_accounting.py:42`

**Issue:** `from decimal import Decimal` is imported but `Decimal` is not referenced in the
module. Remove the dead import. (Script-only module, not under `mypy --strict`, hence Info.)

---

_Reviewed: 2026-06-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
