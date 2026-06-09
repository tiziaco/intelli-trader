---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 04
subsystem: execution
tags: [decimal, matching-engine, fee-model, slippage-model, maker-taker, limit-or-better, d-23-refreeze, m5-04, m5-01]
requires: ["06-01"]
provides:
  - "MatchingEngine Decimal-native: FillDecision.fill_price is Decimal, no float()/quantize, limit-or-better gap fills (D-03)"
  - "Unified fee/slippage ABCs on the raise-contract: validate_inputs raises typed exceptions, Decimal->Decimal math (D-12)"
  - "_emit_fill Decimal end-to-end with real order context: maker/taker from OrderEvent, slippage only on MARKET/STOP (D-11/D-03)"
  - "tests/golden/ re-frozen at the ULP level per owner-approved D-23 (REFREEZE-06-04.md)"
affects: [06-06]
tech-stack:
  added: []
  patterns:
    - "Raise-contract validation (no bool returns, no silent neutral factors) across fee + slippage models"
    - "Full-quantity fill contract: FillDecision carries no quantity; partial-fill plumbing deleted (D-06)"
    - "Seeded-RNG float jitter enters Decimal exactly once via to_money (Phase 2 D-11 seam preserved)"
key-files:
  created:
    - tests/unit/execution/test_fee_models.py
    - tests/unit/execution/test_slippage_models.py
    - tests/golden/REFREEZE-06-04.md
  modified:
    - itrader/execution_handler/matching_engine.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/fee_model/base.py
    - itrader/execution_handler/fee_model/zero_fee_model.py
    - itrader/execution_handler/fee_model/percent_fee_model.py
    - itrader/execution_handler/fee_model/maker_taker_fee_model.py
    - itrader/execution_handler/fee_model/__init__.py
    - itrader/execution_handler/slippage_model/base.py
    - itrader/execution_handler/slippage_model/fixed_slippage_model.py
    - itrader/execution_handler/slippage_model/linear_slippage_model.py
    - itrader/execution_handler/slippage_model/zero_slippage_model.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order.py
    - tests/golden/trades.csv
    - tests/golden/equity.csv
    - tests/golden/summary.json
    - tests/unit/execution/test_matching_engine.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/order/test_order.py
    - tests/unit/order/test_order_manager.py
  deleted:
    - itrader/execution_handler/fee_model/tiered_fee_model.py
decisions:
  - "Plan 06-04 (D-23, owner-approved): ULP-level golden re-freeze — deleting the float(fill_quantity) truncation in _emit_fill shifts 87/134 trade rows and 148/3076 equity rows by <=4.2e-16 relative; final_equity moves 1 ULP (53229.68512642488 -> ...489); 3 stale 4e-17 net_quantity residuals become exactly 0; behavioral identity untouched. Documented in tests/golden/REFREEZE-06-04.md, committed in the SAME commit as code + goldens (D-21 shape)."
  - "Plan 06-04: REFREEZE-M5A.md remains reserved for the 06-06 result-changing fill-timing re-freeze; this ULP re-freeze gets its own note REFREEZE-06-04.md to keep the two D-23 events distinct"
  - "Plan 06-04: order.add_fill collapsed to the full-quantity contract — rejects any quantity != remaining instead of clamping (D-06)"
metrics:
  duration: "~2.5 h (incl. A3 escalation pause)"
  tasks: 2
  files: 25
  completed: 2026-06-06
---

# Phase 6 Plan 04: Decimal-Native Matching + Honest Fee/Slippage Layer Summary

Execution internals are Decimal end-to-end: MatchingEngine fills limit-or-better with no float casts, fee/slippage models share a typed raise-contract with live maker/taker classification, slippage never touches limit fills, and the goldens are re-frozen one float ULP per owner-approved D-23 after the engineered float-truncation boundary was deleted.

## What Was Built

### Task 1 — MatchingEngine Decimal-native + limit-or-better + partial-fill deletion (commit 9bb0516)
- `matching_engine.py`: `trigger = float(order.price)` and the three `float(bar_struct.*)` casts deleted — trigger comparisons and gap min/max run pure-Decimal, no `quantize` anywhere (D-12/D-14).
- LIMIT branch is now limit-or-better (D-03): SELL limit gap-up fills at the better open, BUY limit gap-down fills at the better open; in-bar touches fill at the limit exactly. STOP gap pessimism and the MARKET branch are untouched.
- `FillDecision.fill_price`: float → Decimal; `fill_quantity` field deleted — full-quantity fills are the contract (D-06). DEF-01-C (no margin/liquidation model; routed to Phase 7 risk layer per D-07) documented in the module docstring.
- `order_manager.py`: the float-roundtrip partial-fill clamp block deleted; reconciliation passes fill quantity straight through. `order.add_fill` collapsed to the full-quantity contract (rejects quantity != remaining), audit state-change shape preserved.
- Tests: limit-or-better gap-through cases (both sides), Decimal fill-price type assertions, no-`fill_quantity` guard, stop-gap pessimism unchanged; partial-fill tests rewritten to the new contract.
- Verified: oracle byte-exact after Task 1 (the float boundary in `_emit_fill` still stood), suite green.

### Task 2 — Fee/slippage ABC unification + Decimal `_emit_fill` + maker/taker + deletions (commit 58e38c1)
- `fee_model/base.py` + `slippage_model/base.py` unified on the raise-contract (D-12): `validate_inputs(quantity, price, side, order_type)` raises typed `ValidationError`-family exceptions and returns None; the slippage bool-and-silently-return-1.0 contract is dead (T-06-13).
- All fee models (`zero`, `percent`, `maker_taker`) and slippage models (`zero`, `fixed`, `linear`) retyped Decimal→Decimal; constructor float rates converted once via `to_money`; the seeded `rng.uniform` jitter enters Decimal exactly once (Phase 2 D-11 seam preserved — deterministic given the seed).
- `maker_taker_fee_model`: the `is_maker` parameter is authoritative when provided (D-11); the order_type-string fallback survives for direct callers.
- `simulated.py::_emit_fill`: `price_f`/`quantity_f` float casts deleted — Decimal end-to-end. Callers hand `_emit_fill` the OrderEvent they hold; `order_type=event.order_type.value` and `is_maker=(event.order_type is OrderType.LIMIT)` derived from real context (T-06-15). Slippage factor computed and applied ONLY for MARKET/STOP fills; LIMIT fills take `fill_price` unmodified (D-03, T-06-12). `executed_price = fill_price * slippage_factor` in Decimal.
- DELETED: `tiered_fee_model.py` (D-10 — its only construction path crashed with TypeError), its import/factory branch/`__init__` export, and the `time.sleep(0.1)` connect latency (PERF1).
- New model-level tests (`test_fee_models.py`, `test_slippage_models.py`): Decimal return types, exact percent math, maker/taker rate selection via `is_maker` regardless of order_type string, `pytest.raises` typed-exception assertions, no silent 1.0, seeded-jitter determinism. `test_simulated_exchange.py`: limit fills carry NO slippage while market fills do; stub fee model captures `is_maker=True` for a resting limit fill.

### Checkpoint — A3 escalation and the D-23 re-freeze (owner-approved)
- The plan classified this work inert-defensive (D-21): the golden run pins zero fee/zero slippage with market orders only, so the oracle was expected byte-exact. It was NOT: deleting the `quantity_f = float(fill_quantity)` truncation let full-precision Decimal quantities reach the portfolio, shifting serialized floats at the last ULP.
- Per the plan's never-silently-re-freeze rule, the executor STOPPED, preserved Task 2 as a pending patch artifact (commit 4009857), and escalated to the owner with a full expected-diff analysis.
- Owner approved Option 1 (D-23 re-freeze). The continuation agent verified the working tree matched the patch byte-exact (`git apply --reverse --check`), regenerated `tests/golden/` via `scripts/run_backtest.py` (134 trades, 3076 equity points, final_equity 53229.68512642489), wrote `tests/golden/REFREEZE-06-04.md`, and committed code + goldens + note in ONE commit per the D-21 shape. The patch artifact was removed in the same commit.
- Behavioral identity fully preserved: same 134 trades with identical entry/exit dates, sides, and pairs; identical equity timestamp grid; `test_oracle_behavioral_identity` passes against both old and new goldens.

## Deviations from Plan

### Escalated (A3 / D-23)

**1. [A3 escalation → D-23 re-freeze] Oracle not byte-exact after Task 2**
- **Found during:** Task 2 verification (previous executor)
- **Issue:** The plan's inertness assumption (A3) held only while the `float(fill_quantity)` truncation stood; deleting it (mandated by D-12) shifted serialized numbers at the float-ULP level (max 4.2e-16 relative on trades, 2.2e-14 on equity, 1 ULP on final_equity).
- **Resolution:** STOP-and-escalate per plan; owner approved the re-freeze (Option 1). New goldens are strictly more correct — 3 stale 4e-17 `net_quantity` residuals now net to exactly 0.
- **Files modified:** tests/golden/{trades.csv, equity.csv, summary.json}, tests/golden/REFREEZE-06-04.md
- **Commit:** 58e38c1

### Auto-fixed Issues

**2. [Rule 1 - Gate compliance] `time.sleep` grep gate tripped by a comment**
- **Found during:** Task 2 acceptance gates (continuation agent)
- **Issue:** The PERF1 explanatory comment in `simulated.py` contained the literal string `time.sleep`, violating the plan's `grep -n "time.sleep"` zero-match gate even though the call itself was deleted.
- **Fix:** Reworded the comment to "the artificial connect-latency sleep is gone".
- **Files modified:** itrader/execution_handler/exchanges/simulated.py
- **Commit:** 58e38c1

## Verification

- Full suite: **565 passed** (PYTHONPATH pinned to the worktree root so worktree code is exercised), including both previously-failing golden-comparison tests (`test_backtest_oracle.py::test_oracle_numeric_values`, `test_reservation_inertness.py::test_trade_log_identical_to_golden`).
- `mypy --strict`: clean (139 source files).
- Grep gates: no `tiered_fee_model.py` / `TieredFeeModel` in `itrader/`; no `time.sleep` in `simulated.py`; no hardcoded `order_type="market"` in `_emit_fill`; `slippage_model/base.py` raises; no `return 1.0` validation fallback; no `float(`/`quantize` in `matching_engine.py`.
- Oracle regeneration provenance: `scripts/run_backtest.py` on the pinned config (zero fee/zero slippage, D-09), itrader import path confirmed resolving to the worktree.

## Requirements

- **M5-04: COMPLETE** — maker fees live via real order context, tiered model deleted, validation unified on typed raises, slippage never on limit fills, connect latency removed. Marked in REQUIREMENTS.md.
- **M5-01: partial** — the limit-fill bound half (limit fills never slip past the limit, gap-throughs tested) is delivered; the timing/resampling half lands in 06-05/06-06. Left Pending in REQUIREMENTS.md.

## Known Stubs

None — no placeholder values or unwired components introduced.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary surface beyond the plan's threat model. T-06-12/13/14/15 mitigations all landed as planned (T-06-14 resolved through the sanctioned escalation path rather than silent re-freeze).

## Self-Check: PASSED

- tests/golden/REFREEZE-06-04.md — FOUND
- tests/unit/execution/test_fee_models.py — FOUND
- tests/unit/execution/test_slippage_models.py — FOUND
- itrader/execution_handler/fee_model/tiered_fee_model.py — DELETED (confirmed absent)
- Commit 9bb0516 (Task 1) — FOUND
- Commit 58e38c1 (Task 2 + re-freeze) — FOUND
