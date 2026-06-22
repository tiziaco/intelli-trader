---
phase: 04-liquidation-cross-validation-re-baseline
reviewed: 2026-06-16T13:05:00Z
depth: standard
files_reviewed: 23
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
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-16T13:05:00Z
**Depth:** standard
**Status:** issues_found

## Summary

Re-review (auto-iteration 2) of the Phase-04 liquidation / cross-validation / re-baseline
surface, focused on confirming the prior pass's fixes are sound and surfacing any new
defects the fixes introduced. The three control-flow-changing fixes were verified:

- **WR-02 (determinism gate, 94c7c56)** — VERIFIED byte-identical. The new
  `str(Decimal("10000") - Decimal("3918.808080808080808080808081"))` evaluates to exactly
  `"6081.191919191919191919191919"` (confirmed by direct computation), matching the prior
  literal. The `or`-collapse-into-two-hard-asserts is a real correctness improvement (the
  previous `final_balance` half was dead — a divergence printed "DETERMINISM OK").
- **WR-01 (`_collect_breaches` collapse, 56ac31a)** — Breach collection / determinism
  ordering is preserved: the single predicate `_collect_breaches_over_prices` retains the
  `(ticker, entry_date, str(id))` sort and the WR-02 unwired-Universe guard. BUT the
  collapse left the single-close adapter `_collect_breaches` with **zero call sites** (see
  WR-01 below).
- **WR-05 (liquidation-pass gating, dd1cbf4)** — The set-membership conditional is
  behavior-preserving and SAFE (it never wrongly skips a portfolio that legitimately needs
  a liquidation pass: when the pass runs, `marked_portfolio_ids` always contains every
  active portfolio). However the live-path skip semantics the docstring/comments describe
  are **unreachable** (see WR-02 below).

Verification performed against project invariants:
- SMA_MACD oracle byte-exact (`tests/integration/test_backtest_oracle.py`) — 3 passed.
- Liquidation determinism double-run gate — DETERMINISM OK, byte-identical
  (`final_balance: 6081.191919191919191919191919`).
- All 7 e2e accounting leaves + 15 liquidation/reconcile/lock unit tests — green.
- `mypy --strict` on the three changed portfolio modules — clean.
- Decimal money end-to-end preserved on all reviewed paths; `float()` only at
  serialization/logging edges. Tab/space per-file conventions respected.

No critical defects. Two warnings (dead code + a misleading rationale that contradicts the
actual control flow) and one info item remain.

## Warnings

### WR-01: `_collect_breaches` is dead code after the WR-01 collapse

**File:** `itrader/portfolio_handler/portfolio_handler.py:462-474`
**Issue:** The WR-01 fix (56ac31a) turned `_collect_breaches` (single shared close) into a
thin adapter over `_collect_breaches_over_prices`, and in the same commit migrated its only
caller — `tests/unit/portfolio/test_liquidation.py::test_multi_breach_deterministic` — to
call `_collect_breaches_over_prices` directly. The production path
(`_run_liquidation_pass`) also calls `_collect_breaches_over_prices`. A grep across
`itrader/`, `tests/`, and `scripts/` confirms `_collect_breaches` now has **zero call
sites**. It is dead code: a private adapter method that nothing invokes — exactly the
"two near-identical collectors drift apart" maintainability hazard the fix set out to
eliminate, except now one of the two is unreachable and will silently rot. (Subtle drift
is already latent: the adapter builds `{ticker: close}` and delegates, where the old body
skipped on `position.current_price <= 0` but the delegate skips on the passed-in
`close <= 0` — divergent predicates that only happen to agree because nothing exercises
the adapter.)
**Fix:** Delete `_collect_breaches` entirely (lines 462-474) — the single predicate
`_collect_breaches_over_prices` is the live path and the test target. If a single-close
convenience wrapper is wanted for future unit tests, keep it but add a test that exercises
it so it cannot become dead again.

### WR-02: WR-05 liquidation-pass gating describes an unreachable live-path scenario

**File:** `itrader/portfolio_handler/portfolio_handler.py:564-592, 746-786`
**Issue:** The `marked_portfolio_ids` gating added in dd1cbf4 is documented (docstring
lines 581-586 and the inline comment at 746-752) as protecting the LIVE
publish-and-continue path: "a portfolio whose mark raised mid-loop ... is SKIPPED by the
pass so the breach never reads its stale, partially-marked equity." That scenario cannot
occur. `update_portfolios_market_value` wraps each portfolio's mark in a try/except that
**re-raises** (line 777). The dispatch error seam (`EventHandler._dispatch` ->
`_on_handler_error`, and the live override `LiveTradingSystem._publish_and_continue`)
operates at the granularity of the WHOLE `update_portfolios_market_value` handler call, not
per-portfolio-iteration. So if any portfolio's mark raises, the re-raise propagates out of
`update_portfolios_market_value` entirely — line 786 (`_run_liquidation_pass`) is never
reached, in BOTH backtest and live modes. Consequently `marked_portfolio_ids` always equals
the full active-portfolio set whenever the pass actually runs, and the `if ... not in
marked_portfolio_ids: continue` branch (lines 591-592) is never taken in production. The
gating is harmless and defensively correct, but the rationale that justifies it is false:
the partial-set state it guards against is structurally impossible given the re-raise.
**Fix:** Either (a) correct the docstring/comments to state the gating is purely defensive
against a FUTURE per-portfolio error policy and currently never fires (and keep the code as
a guardrail), or (b) if a true per-portfolio continue-on-mark-failure policy is intended for
live mode, move the swallow INSIDE the per-portfolio loop in
`update_portfolios_market_value` (catch-log-continue per portfolio instead of re-raise) so
the partial-mark scenario the gating handles can actually arise. Do not leave the current
mismatch where the comment asserts a control-flow path the re-raise forecloses.

## Info

### IN-01: Liquidation log emits a quantized `liq_price` but reads as the formula value

**File:** `itrader/portfolio_handler/portfolio_handler.py:554-562`
**Issue:** `_liquidate_position` logs `liq_price=str(fill_price)` where `fill_price` has been
quantized to the instrument price scale (line 518). In the determinism gate run the log line
shows `liq_price=80.81` while the realized loss / penalty carry full precision
(`-3918.808080808080808080808081`, `penalty=80.80808080808080808080808081`). This is correct
behavior (the FillEvent price IS the quantized `fill_price`), but a reader cross-checking the
log against the hand-computed isolated formula (`80.808080...`) may be briefly confused by the
discrepancy between the rounded `liq_price` field and the full-precision penalty. Minor
observability nit, not a defect.
**Fix:** Optionally log both the pre-quantize liq price and the quantized fill price, or
rename the log field to `fill_price` to make the rounding explicit. No code change required
for correctness.

---

_Reviewed: 2026-06-16T13:05:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
