---
phase: 04-liquidation-cross-validation-re-baseline
reviewed: 2026-06-16T15:30:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/cash/cash_manager.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
  - scripts/crossval/levered_run.py
  - scripts/crossval/liquidation_run.py
  - scripts/crossval/short_run.py
  - scripts/determinism_liquidation_double_run.py
  - tests/unit/portfolio/test_liquidation.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-16 (auto-iteration 3, final cap)
**Depth:** standard
**Files Reviewed:** 10
**Status:** clean

## Summary

Auto-iteration 3 (final, cap) re-review of the Phase 04 liquidation /
cross-validation / re-baseline source set. Iteration 2 closed three findings
(commits `22764c9` delete dead `_collect_breaches`; `c0e09e3` correct the WR-05
gating docstring to a defensive guardrail; `f97c91f` clarify the IN-01
`liq_price` log comment) — all dead-code-removal / comment-truthfulness only,
no control-flow or value changes. This pass re-read the current state of all ten
listed files at standard depth.

All three iteration-2 fixes are confirmed clean and no new defects were
surfaced. The review is **clean** with zero remaining findings.

## Narrative Findings (AI reviewer)

No Critical, Warning, or Info findings. The adversarial re-review confirmed the
iteration-2 fixes and surfaced no new bug, security gap, or quality defect.

### Confirmation of iteration-2 fixes

1. **`_collect_breaches` fully removed (WR-01).** An exact-word grep across the
   tree returns no reference to the deleted adapter. The only surviving symbol
   is `_collect_breaches_over_prices` — the single live collector — referenced
   at `portfolio_handler.py:597` (call site in `_run_liquidation_pass`), defined
   at `:613`, and exercised by `test_liquidation.py:171`. No dangling reference.
   Commit `22764c9` verified in history.

2. **WR-05 `marked_portfolio_ids` gating docstrings are truthful.** The
   `_run_liquidation_pass` docstring (`portfolio_handler.py:574-589`) and the
   inline comment in `update_portfolios_market_value` (`:751-764`) both now
   accurately describe a defensive-only guardrail. The narrative matches the
   real control flow: the `except` at `:776-789` re-raises (does not `continue`
   the per-portfolio loop), so `marked_portfolio_ids` is always the full active
   set whenever the pass runs, and the `not in` skip at `:594-596` is never taken
   in production. The "kept for a future per-portfolio continue-on-mark-failure
   policy" justification matches the live `_publish_and_continue` handler-call
   granularity. Commit `c0e09e3` verified.

3. **IN-01 `liq_price` log comment corrected.** The comment at
   `portfolio_handler.py:540-546` accurately states the logged `liq_price` is the
   quantized `fill_price` (matching the emitted `FillEvent.price`) while
   `penalty` rides full precision. Verified against `quantize`'s signature
   (`core/money.py:69`) and the price-scale guard at `:502-504`. The
   `_StubInstrument` in the unit test has no `price_precision`, so the
   `getattr(..., None)` skip leaves the fill at full-precision `_LONG_LIQ` —
   consistent with the test assertion `fill.price == _LONG_LIQ`. Commit `f97c91f`
   verified.

### Additional cross-checks (no defects)

- `_liq_inputs` docstring's "TradingRules config fallback" caveat is accurate —
  the method resolves Instrument-first and the Instrument always carries a
  `Decimal("0")` default, so no dead/missing branch.
- Live/backtest wiring parity: `compose.py:222` and `live_trading_system.py:181`
  both inject the same `order_storage` into `set_order_storage` (LIQ-03 seam).
- Cross-val scripts use synthetic frames (LEVUSD/LIQUSD/SHORTUSD), never BTCUSD —
  the SMA_MACD oracle (134 / 46189.87730727451, D-11) is not perturbed.
- The determinism double-run script asserts both halves hard
  (`determinism_liquidation_double_run.py:108-121`).
- Money is Decimal end-to-end; `float()` appears only at logging / exception-
  message edges (the documented serialization carve-out).

All reviewed files meet quality standards. No issues found.

---

_Reviewed: 2026-06-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
