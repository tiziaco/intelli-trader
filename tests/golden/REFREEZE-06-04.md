# Golden Re-Freeze: Plan 06-04 (D-23 owner-approved)

**Date:** 2026-06-06
**Plan:** 06-04 Task 2 — Fee/slippage ABC unification + Decimal `_emit_fill`
**Decision:** D-23 blocking owner sign-off — **Option 1 (approve re-freeze) chosen by owner**
**Escalation path:** A3 assumption ("Decimal retype is numerically inert under zero costs")
violated at the last float ULP → executor STOPPED per the plan's never-silently-re-freeze
rule, preserved Task 2 as a pending patch (commit 4009857), and escalated to the owner.

## WHAT changed

Task 2 deletes the `quantity_f = float(fill_quantity)` cast in
`itrader/execution_handler/exchanges/simulated.py::_emit_fill` (D-12 Decimal end-to-end).
The old cast truncated 28-digit Decimal fill quantities to float53 at the exchange
boundary; that truncation was frozen into the previous golden (M2b re-freeze, plan 03-09,
commit b146af4). With the cast gone, full-precision Decimal quantities flow into the
portfolio, and the serialized floats differ at the last representable ULP.

## WHY the new numbers are MORE correct

- The float truncation was an artifact of the engineered-inert D-22 boundary, not an
  economic rule. Removing it is the sanctioned M5a purpose (D-12).
- 3 stale `net_quantity` residuals in the old golden (3e-17 / 4e-17 on trades closed
  2022-04-22, 2024-11-01, 2025-05-23) now net to **exactly 0.0** — closed positions
  genuinely hold zero quantity.

## Behavioral identity — fully preserved (the LAW is untouched)

| Invariant | Old golden | New golden |
|---|---|---|
| Trade count | 134 | 134 |
| Trade identity (entry_date, exit_date, side, pair) | — | identical, all 134 |
| Equity timestamp grid | 3076 points | identical, 3076 points |

`test_oracle_behavioral_identity` passes against BOTH goldens — this re-freeze changes
numeric magnitudes only.

## Expected numeric diff (old golden → new golden)

| Surface | Rows differing | Max abs diff | Max rel diff |
|---|---|---|---|
| trades.csv (134 rows) | 87 | 2.2e-11 (`total_sold`) | 4.2e-16 (`realised_pnl`) |
| equity.csv (3076 rows) | 148 | 1.0e-10 (`total_equity`) | 2.2e-14 |
| summary.json `final_equity`/`final_cash` | 1 ULP | 53229.68512642488 → 53229.68512642489 | 1.9e-16 |
| trades.csv `net_quantity` | 3 | 4e-17 → exactly 0.0 | stale residuals eliminated |

Per-column trade diffs: `avg_price` 8 rows, `avg_sold` 7, `total_bought` 39,
`total_sold` 44, `realised_pnl` 49 — all at or below 4.2e-16 relative (1–2 float ULPs).
`total_realised_pnl` in summary.json is unchanged (43229.68512642489).

## Run provenance

- Generator: `poetry run python scripts/run_backtest.py` (pinned config — D-09:
  zero fee, zero slippage, market orders only, `sl=0, tp=0`)
- Dataset: `data/BTCUSD_1d_ohlcv_2018_2026.csv`, window 2018-01-01 → 2026-06-03
- Code state: plan 06-04 Tasks 1+2 applied (Decimal-native matching + fee/slippage +
  `_emit_fill`)

## Scope note

This is a ULP-level numerical re-freeze under D-23, distinct from the result-changing
fill-timing re-freeze planned in 06-06 (which will be documented in `REFREEZE-M5A.md`).
The behavioral oracle is untouched.
