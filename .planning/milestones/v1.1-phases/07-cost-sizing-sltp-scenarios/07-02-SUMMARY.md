---
phase: 07-cost-sizing-sltp-scenarios
plan: 02
subsystem: e2e-cost-scenarios
tags: [e2e, fee-model, slippage, maker-taker, golden-master, cost]
requires:
  - "Plan 07-01 scaffolding (commission column, D-14 exchange seam, percent_fee canary template)"
  - "itrader MakerTakerFeeModel / PercentFeeModel / FixedSlippageModel / LinearSlippageModel"
provides:
  - "COST-02 maker_taker leaf (two rates in one scenario, frozen commission contrast)"
  - "COST-03 fixed_slippage leaf (deterministic directional rate, RNG zeroed)"
  - "COST-04 linear_slippage leaf (size-impact only, base noise zeroed)"
  - "COST-05 limit_no_slip leaf (LIMIT fill forces slippage_factor=1)"
  - "COST-06 combined_roundtrip leaf (fee+slippage cash to the cent)"
  - "engine fix: _init_fee_model/_init_slippage_model honor configured-zero knobs"
affects:
  - "completes the COST cluster (5 of 5 remaining); SIZE (07-03) and SLTP (07-04) are sibling Wave-2 clusters"
tech-stack:
  added: []
  patterns:
    - "two ScriptedEmitter instances (LIMIT=maker / MARKET=taker) on non-overlapping date windows for a maker-vs-taker contrast in one leaf"
    - "deterministic slippage via random_variation=False (fixed) and base_slippage_pct=0 (linear)"
    - "percent fee is charged on the BASE (un-slipped) notional, position settles at the slipped price"
key-files:
  created:
    - "tests/e2e/cost/maker_taker/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/cost/limit_no_slip/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/cost/fixed_slippage/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/cost/linear_slippage/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/cost/combined_roundtrip/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
  modified:
    - "itrader/execution_handler/exchanges/simulated.py (is-not-None fee/slippage knob fix)"
decisions:
  - "D-11: COST-02 = two sequential round-trips in one leaf via two emitter instances (LIMIT=maker / MARKET=taker), non-overlapping dates so allow_increase=False never blocks"
  - "07-02 engine fix: _init_fee_model/_init_slippage_model use 'is not None' not 'or' so a configured Decimal(0) (falsy) is honored (T-07-06) — required for COST-04 hand-derivability; oracle-safe (oracle runs Zero* models)"
  - "Engine truth (COST-06): percent fee is charged on the BASE/un-slipped notional (fee_model called before executed_price = price*slippage_factor), not the slipped notional"
metrics:
  duration: "~15 min"
  completed: "2026-06-10"
  tasks: 3
  files: 35
---

# Phase 7 Plan 02: COST Scenario Leaves (COST-02..06) Summary

Authored, hand-verified to the cent, and froze the 5 remaining COST scenario leaves
on the Plan 07-01 scaffolding, giving the maker/taker fee model, the fixed and linear
slippage models, the limit-no-slip guarantee, and the combined fee+slippage cash math
their first end-to-end golden coverage. One oracle-safe engine fix was required so a
configured-zero determinism knob (COST-04's `base_slippage_pct=0`) is honored rather
than silently overridden.

## What Was Built

**Task 1 — COST-02 maker_taker + COST-05 limit_no_slip:**
- `maker_taker` (COST-02, D-11): TWO sequential round-trips in ONE leaf using two
  `ScriptedEmitter` instances on the same ticker/portfolio — one `order_type=LIMIT`
  (maker, fires the early date window) and one `order_type=MARKET` (taker, later
  window). Non-overlapping windows so the maker position is flat before the taker
  round-trip opens (`allow_increase=False` would otherwise refuse). With
  `maker_rate=0.001` / `taker_rate=0.002` and NO slippage, the frozen `commission`
  column shows the two distinct rates side by side: maker row **21.375** (rate
  0.001), taker row **70.4156625** (rate 0.002). final_cash 24019.1530875, trade_count 2.
- `limit_no_slip` (COST-05): a FIXED 2% slippage model is CONFIGURED, but a LIMIT
  entry+exit forces `slippage_factor=1` (simulated.py:206-208), so both legs fill AT
  the limit/trigger price (120, 150) with zero impact; commission 0.00, final_cash 12375.

**Task 2 — COST-03 fixed_slippage + COST-04 linear_slippage:**
- `fixed_slippage` (COST-03): FIXED 2% slippage, `random_variation=False` (Pitfall 1)
  → deterministic directional fill: BUY 100×1.02=102, SELL 200×0.98=196; realised_pnl
  8930, final_cash 18930. No RNG digits in the frozen golden.
- `linear_slippage` (COST-04): LINEAR slippage with `base_slippage_pct=Decimal("0")`
  zeroing the RNG base-noise, leaving the size-impact term only:
  size_impact = order_value × 0.0001/100 → BUY 100×1.0095=100.95, SELL 200×0.981=196.20;
  realised_pnl 9048.75, final_cash 19048.75. Clean (no seed-dependent digits) only
  because of the engine fix below.

**Task 3 — COST-06 combined_roundtrip:**
- One MARKET BUY→SELL with BOTH a PERCENT fee (1%) AND a deterministic FIXED slippage
  (2%, `random_variation=False`). Captured the engine truth that the percent fee is
  charged on the BASE (un-slipped) notional while the position settles at the slipped
  price (the two costs are independent, not compounded). Cash to the cent: commission
  285.00, realised_pnl 8645.00, final_cash 18645.00 — reconciled via both the ledger
  identity and `starting_cash + realised_pnl`.

## Verification Results

- `poetry run pytest tests/e2e/cost -q` → 6 passed (canary + the 5 new leaves).
- `poetry run pytest tests/e2e -q` → 21 passed (no regression in the 15 pre-existing
  leaves or the canary).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed
  (byte-exact; the engine fix is oracle-safe).
- `mypy itrader` (`--strict`) → no issues in 160 source files.
- Acceptance greps: `random_variation=False` present in fixed_slippage/scenario.py;
  `base_slippage_pct=Decimal("0")` present in linear_slippage/scenario.py; no
  `Decimal(<float>)` literals in any new scenario.

## TDD Gate Compliance (tdd="true" tasks)

Each leaf followed the E2E freeze discipline as its RED/GREEN cycle: author bars +
scenario + VERIFY note (the hand-derivation is the correctness proof), freeze ONE leaf
at a time via `--freeze` (the harness mechanically refuses >1 selected test), then
re-run WITHOUT `--freeze` and diff green against the hand-verified golden. The freeze
proves stability; the VERIFY note proves correctness (T-07-05/T-07-06 mitigation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_init_fee_model`/`_init_slippage_model` silently overrode a configured zero**
- **Found during:** Task 2 setup (COST-04 needs `base_slippage_pct=0` to zero the RNG noise).
- **Issue:** Both used `float(config.x or <default>)`. A legitimate `Decimal("0")` is
  falsy, so `config.base_slippage_pct or 0.01` returned the 0.01 default — meaning
  COST-04's `base_slippage_pct=Decimal("0")` would NOT zero the noise; the model would
  draw seed-dependent RNG jitter and the fill would be non-hand-derivable (T-07-06).
- **Fix:** Switched all fee/slippage param fallbacks to `... if config.x is not None
  else <default>` so a configured 0 is honored verbatim.
- **Why oracle-safe:** the BTCUSD oracle runs `exchange="csv"` (ZeroFeeModel /
  ZeroSlippageModel) and never reaches the percent/maker_taker/fixed/linear branches.
  Oracle re-run is byte-exact; mypy `--strict` clean.
- **Files modified:** itrader/execution_handler/exchanges/simulated.py
- **Commit:** 7815130

**2. [Rule 1 - Bug] Corrected two VERIFY-note hand-derivations to match the engine truth**
- **Found during:** the freeze-vs-VERIFY cross-check (Task 1 maker_taker, Task 3 combined).
- **maker_taker:** the note initially claimed the taker `slippage_exit = 100.0`; the
  frozen golden showed 0.0 — `attach_slippage` indexes the STORE close series (the
  bar BEFORE the fill bar = 2020-01-08 close 200), not the decision bar, so 200−200=0.0.
- **combined_roundtrip:** the note initially charged the percent fee on the slipped
  notional (283.10); the engine charges it on the BASE notional (285.00) because the
  fee model is called with the base fill price BEFORE `executed_price = price *
  slippage_factor`. realised_pnl/final_cash corrected to 8645.00/18645.00.
- **Fix:** corrected the VERIFY notes to match the engine's actual (and correct)
  behavior. No golden change — the frozen goldens were correct; only the hand-notes
  were wrong.
- **Files modified:** tests/e2e/cost/maker_taker/scenario.py,
  tests/e2e/cost/combined_roundtrip/scenario.py (VERIFY notes only)
- **Commits:** 4462ed6, 46147ba

## Known Stubs

None. Every leaf runs a real fill end-to-end with a real configured fee/slippage
model; commission and fill prices are sourced from real engine state, not placeholders.

## Threat Flags

None — pure in-repo test scaffolding plus one oracle-dark engine fix in an
already-exercised code path. No new network/auth/schema surface; no package installs
(T-07-SC accepted).

## Self-Check: PASSED

All created leaf files verified present on disk (5 leaves × {`__init__`, `scenario`,
`test_scenario`, `bars.csv`, `golden/trades.csv`, `golden/summary.json`}); all 4 task
commits verified in git log:
- 7815130 fix(07-02): honor configured-zero fee/slippage knobs (is-not-None not or)
- 4462ed6 test(07-02): COST-02 maker_taker + COST-05 limit_no_slip
- b170e20 test(07-02): COST-03 fixed_slippage + COST-04 linear_slippage
- 46147ba test(07-02): COST-06 combined_roundtrip
