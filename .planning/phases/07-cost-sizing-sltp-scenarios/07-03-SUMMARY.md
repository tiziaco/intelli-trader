---
phase: 07-cost-sizing-sltp-scenarios
plan: 03
subsystem: e2e-sizing-scenarios
tags: [e2e, sizing, fixed-quantity, risk-percent, over-cash-reject, golden-master]
requires:
  - "Plan 07-01 scaffolding (commission column, D-14 exchange seam, ScriptedEmitter sizing_policy/sltp_policy kwargs)"
  - "itrader SizingResolver (FixedQuantity / RiskPercent arms) + the admission cash-reservation gate"
provides:
  - "SIZE-01 fixed_quantity leaf (FixedQuantity flat fill, hand-verified qty=10)"
  - "SIZE-02 risk_percent leaf (RiskPercent off a DECISION-TIME stop, D-13, closed trade)"
  - "SIZE-03 over_cash_reject leaf (audited insufficient-funds REJECTED via the opt-in orders-snapshot, D-15)"
affects:
  - "completes the SIZE cluster (3 of 3); COST (07-02 done) and SLTP (07-04) are sibling Wave-2 clusters"
tech-stack:
  added: []
  patterns:
    - "RiskPercent qty = (total_equity * risk_pct) / |decision_price - stop|, where the SAME explicit sl both sizes the entry AND becomes the resting STOP-loss child that closes the trade"
    - "over-cash rejection via the opt-in orders.csv golden — an EMPTY placeholder opts the leaf into the snapshot freeze (same vehicle as matching/never_fill)"
    - "exchange=None on every SIZE leaf — sizing is the only moving part, so every number traces to the declared policy + bar prices"
key-files:
  created:
    - "tests/e2e/sizing/__init__.py"
    - "tests/e2e/sizing/fixed_quantity/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sizing/risk_percent/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sizing/over_cash_reject/{__init__,scenario,test_scenario}.py + bars.csv + golden/{orders.csv,summary.json}"
  modified: []
decisions:
  - "D-09a: each SIZE leaf carries fresh, contrived per-leaf bars (no shared fixture)"
  - "D-10: one leaf per SIZE requirement (SIZE-01/02/03)"
  - "D-13: SIZE-02 RiskPercent sizes off a DECISION-TIME stop distance (explicit script sl distinct from the decision-bar close), NOT PercentFromFill (circular)"
  - "D-15: SIZE-03 over-cash REJECTED surfaced via the opt-in orders-snapshot (no new serializer); the reused empty-orders.csv-placeholder opt-in vehicle"
  - "SIZE-02 stop-as-exit design: the explicit sl both sizes the RiskPercent entry AND becomes the bracket STOP child that closes the trade (in-bar touch fill at the trigger 80), so realised_pnl = -200 = exactly the 2% risk — a CLOSED TRADE, not a REJECTED order (T-07-09)"
metrics:
  duration: "~6 min"
  completed: "2026-06-10"
  tasks: 2
  files: 19
---

# Phase 7 Plan 03: SIZE Scenario Leaves (SIZE-01..03) Summary

Authored, hand-verified to the cent, and froze the 3 SIZE scenario leaves on the
Plan 07-01 scaffolding, giving `FixedQuantity` and `RiskPercent` (off a decision-time
stop distance) their first hand-verified fills, and proving over-cash sizing produces
the audited insufficient-funds REJECTED outcome (Phase 7 Success Criterion 3). No
engine change was required — the SizingResolver and the admission cash-reservation
gate are already wired into `_resolve_signal_quantity` (PR #12 / Plan 05-06); this
plan is pure in-repo test data + VERIFY notes.

## What Was Built

**Task 1 — SIZE-01 fixed_quantity + SIZE-02 risk_percent:**
- `fixed_quantity` (SIZE-01, D-02): a MARKET BUY -> MARKET SELL round-trip with
  `sizing_policy=FixedQuantity(qty=Decimal("10"))`. The resolver FixedQuantity arm
  is a pass-through (`sizing_resolver.py:113-114`), so the frozen trade quantity is
  a FLAT 10 units independent of cash. Entry @100, exit @200, realised_pnl 1000,
  final_cash 11000, commission 0.00 (exchange=None) — every number traces straight
  to the declared qty + bar prices.
- `risk_percent` (SIZE-02, D-13): a MARKET BUY with `RiskPercent(risk_pct=Decimal("0.02"))`
  AND an explicit script `sl=Decimal("80")` DISTINCT from the decision-bar close (100).
  The resolver RiskPercent arm sizes off the stop distance:
  `qty = (total_equity * risk_pct) / |price - stop| = (10000 * 0.02) / |100-80| = 10`.
  The SAME explicit sl both sizes the entry AND becomes the resting STOP(SELL @80)
  bracket child; it triggers on bar3 (low 79 <= 80) and fills at the trigger 80
  (`matching_engine.py:160-161`, in-bar touch). realised_pnl = (80-100)*10 = -200 =
  exactly the 2% risk; final_cash 9800; max_drawdown -0.02. This is a CLOSED TRADE
  (LONG, net_quantity 0), NOT a REJECTED order — confirming the decision-time stop
  wired correctly (T-07-09 mitigation; the Pitfall-3 warning sign would be a
  REJECTED order in the mirror).

**Task 2 — SIZE-03 over_cash_reject (orders-snapshot REJECTED, D-15):**
- A single MARKET BUY with `sizing_policy=FixedQuantity(qty=Decimal("1000"))`. The
  FixedQuantity sizing itself succeeds (no cash check — that is the admission gate's
  job), producing a primary BUY sized 1000 @ 100 = 100_000 notional, 10x the 10_000
  cash. The admission cash-reservation gate (`order_manager.py:393-414`) computes
  `cost = price*qty + estimated_commission = 100_000`, `reserve()` raises
  `InsufficientFundsError`, and the primary is transitioned PENDING->REJECTED
  (`triggered_by="cash_reservation"`) and persisted; nothing is emitted to the
  exchange. The leaf freezes the OPT-IN `golden/orders.csv` (an empty placeholder
  opts it into the snapshot, the same vehicle `matching/never_fill` uses): exactly
  ONE row — STANDALONE, MARKET, BUY, REJECTED, price 100, quantity 1000,
  filled_quantity 0. `trades.csv` is EMPTY; `summary.json` `trade_count=0`,
  `final_cash=10000` (untouched — the reserve that would have debited cash raised
  instead).

## Verification Results

- `poetry run pytest tests/e2e/sizing -x` -> 3 passed (all SIZE leaves green).
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` -> 3 passed
  (byte-exact — no engine change, oracle untouched).
- `poetry run pytest tests/e2e` -> 24 passed (21 prior + 3 new SIZE leaves, no regression).
- `mypy itrader` (`--strict`) -> no issues in 160 source files (no `itrader/` source changed).
- Acceptance greps: `RiskPercent` present in risk_percent/scenario.py; `FixedQuantity`
  present in fixed_quantity/scenario.py; `grep -q REJECTED over_cash_reject/golden/orders.csv` OK;
  risk_percent produces a CLOSED TRADE row (LONG) in golden/trades.csv.

## TDD Gate Compliance (tdd="true" tasks)

Each leaf followed the E2E freeze discipline as its RED/GREEN cycle: author bars +
scenario + VERIFY note (the hand-derivation is the correctness proof), freeze ONE
leaf at a time via `--freeze` (the harness mechanically refuses >1 selected test),
then re-run WITHOUT `--freeze` and diff green against the hand-verified golden. The
freeze proves stability; the VERIFY note proves correctness (T-07-08/T-07-09/T-07-10
mitigation). For SIZE-02 the closed-trade check is the explicit anti-T-07-09 gate:
a REJECTED order in the mirror would mean the decision-time stop was mis-wired.

## Deviations from Plan

None — the three leaves executed exactly as planned. Every frozen golden matched its
VERIFY-note hand-derivation to the cent on the first freeze; no VERIFY-note corrections
and no engine fixes were required (the SizingResolver + admission gate were already
correct and wired). The plan's `files_modified` frontmatter listed
`risk_percent/golden/orders.csv` as a possible artifact, but SIZE-02 correctly
produces a CLOSED TRADE (trades.csv + summary.json), so no orders.csv is frozen for
that leaf — only SIZE-03 freezes orders.csv, as the plan's Task 2 specifies.

## Known Stubs

None. Every leaf runs a real fill (or a real audited rejection) end-to-end through
the real SizingResolver + admission gate; all quantities, prices, and the REJECTED
status are sourced from real engine state, not placeholders.

## Threat Flags

None — pure in-repo test scaffolding (data leaves + VERIFY notes). No `itrader/`
source changed; no new network/auth/schema surface; no package installs (T-07-SC accepted).

## Self-Check: PASSED

All created leaf files verified present on disk (3 leaves × {`__init__`, `scenario`,
`test_scenario`, `bars.csv`, golden artifacts}); both task commits verified in git log:
- e776f3a test(07-03): author + hand-verify + freeze SIZE-01 fixed_quantity + SIZE-02 risk_percent
- 45362ed test(07-03): author + hand-verify + freeze SIZE-03 over_cash_reject
