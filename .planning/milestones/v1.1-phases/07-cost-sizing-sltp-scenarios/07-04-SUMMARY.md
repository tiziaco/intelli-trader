---
phase: 07-cost-sizing-sltp-scenarios
plan: 04
subsystem: e2e-sltp-scenarios
tags: [e2e, sltp, percent-from-decision, percent-from-fill, brackets, golden-master]
requires:
  - "Plan 07-01 scaffolding (commission column, D-14 exchange seam, ScriptedEmitter sltp_policy kwarg)"
  - "itrader PercentFromDecision / PercentFromFill (core/sizing.py) + OrderManager bracket assembly / fill-anchored children"
provides:
  - "SLTP-01 PercentFromDecision: SL-hit / TP-hit / held-to-end (decision-close anchor)"
  - "SLTP-02 PercentFromFill: SL-hit / TP-hit / held-to-end (next-bar-open fill anchor)"
  - "SLTP-03 held-to-end coverage via the opt-in orders.csv (SL+TP children PENDING) + summary trade_count=0"
affects:
  - "completes the SLTP cluster (3rd of 3 Wave-2 clusters); COST (07-02) and SIZE (07-03) are siblings"
tech-stack:
  added: []
  patterns:
    - "PercentFromDecision children priced at the DECISION-bar close via _bracket_levels(to_money(signal.price), action)"
    - "PercentFromFill children priced at the ACTUAL next-bar-open fill via on_fill _create_fill_anchored_children"
    - "Decision vs Fill anchor made visibly distinct: bars authored so decision close (100) != next-bar open (90)"
    - "PercentFromFill fill anchored BELOW the decision close so entry notional stays within the decision-priced cash reservation"
    - "held-to-end via the opt-in orders.csv (SL+TP children PENDING) + summary trade_count=0 / non-flat final_equity (Pitfall 4)"
key-files:
  created:
    - "tests/e2e/sltp/__init__.py"
    - "tests/e2e/sltp/from_decision_sl_hit/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sltp/from_decision_tp_hit/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sltp/from_decision_held/{__init__,scenario,test_scenario}.py + bars.csv + golden/{orders.csv,summary.json}"
    - "tests/e2e/sltp/from_fill_sl_hit/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sltp/from_fill_tp_hit/{__init__,scenario,test_scenario}.py + bars.csv + golden/{trades.csv,summary.json}"
    - "tests/e2e/sltp/from_fill_held/{__init__,scenario,test_scenario}.py + bars.csv + golden/{orders.csv,summary.json}"
  modified: []
decisions:
  - "D-09a: each SLTP leaf carries fresh, contrived per-leaf bars (no shared fixture)"
  - "D-10: one leaf per SLTP outcome — the full 2x3 matrix of {PercentFromDecision, PercentFromFill} x {SL-hit, TP-hit, held-to-end}"
  - "D-12: sltp_policy declared via the extended ScriptedEmitter kwarg (no explicit script sl/tp, so the policy is consulted)"
  - "D-13: PercentFromDecision anchors at the decision close (sl=anchor*(1-pct), tp=anchor*(1+pct) for a BUY); PercentFromFill anchors at the actual fill price"
  - "PercentFromFill cash-reservation contract: the admission gate sizes/reserves off the DECISION close, so the fill anchor must keep entry notional within that reservation — authored the next-bar open BELOW the decision close (90 < 100) to satisfy both the distinct-anchor requirement and the funds invariant"
metrics:
  duration: "~12 min"
  completed: "2026-06-10"
  tasks: 2
  files: 39
---

# Phase 7 Plan 04: SLTP Scenario Leaves (SLTP-01..03) Summary

Authored, hand-verified to the cent, and froze the 6 SLTP scenario leaves — the
full 2x3 matrix of `PercentFromDecision` x {SL-hit, TP-hit, held-to-end} and
`PercentFromFill` x {SL-hit, TP-hit, held-to-end} — on the Plan 07-01 scaffolding.
This gives the two SLTP percent policies their first end-to-end golden coverage and
proves the Decision and Fill anchors produce DIFFERENT SL/TP levels for the same
percentages (Phase 7 Success Criterion 4; SLTP-01/02/03). No engine change was
required — `PercentFromDecision` / `PercentFromFill` and the bracket-assembly /
fill-anchored-child paths are already wired in `order_manager.py`; this plan is pure
in-repo test data + VERIFY notes.

## What Was Built

**Task 1 — PercentFromDecision x {SL-hit, TP-hit, held-to-end} (3 leaves):**
All three pass `sltp_policy=PercentFromDecision(sl_pct=Decimal("0.10"),
tp_pct=Decimal("0.20"))` with a plain `{"2020-01-02": {"side": "BUY"}}` script (NO
explicit `sl`/`tp`, so the policy is consulted, order_manager.py:613). The children
are priced at the DECISION-bar close (anchor = bar1 close = 100): SL = 100*(1-0.10)
= 90, TP = 100*(1+0.20) = 120.
- `from_decision_sl_hit`: bar3 low 88 <= SL 90 -> STOP fills at min(open 95, 90) = 90;
  avg_bought 100, avg_sold 90, realised_pnl -950, final_cash 9050.
- `from_decision_tp_hit`: bar3 high 125 >= TP 120 -> LIMIT in-bar touch fills @120;
  avg_bought 100, avg_sold 120, realised_pnl +1900, final_cash 11900.
- `from_decision_held`: bars stay strictly between 90 and 120 -> position held;
  orders.csv shows ENTRY FILLED @100 + SL STOP SELL PENDING @90 + TP LIMIT SELL
  PENDING @120; summary trade_count 0, final_equity 10760 (open 95 @ last close 108
  + cash 500), non-flat.

**Task 2 — PercentFromFill x {SL-hit, TP-hit, held-to-end} (3 leaves):**
All three pass `sltp_policy=PercentFromFill(sl_pct=Decimal("0.10"),
tp_pct=Decimal("0.20"))`. The children are priced at the ACTUAL next-bar-open fill
via `_create_fill_anchored_children` (order_manager.py:743). Bars are authored so
the decision close (bar1 = 100) and the next-bar open (bar2 = 90) DIFFER — making
the fill anchor (90) visibly distinct from a decision anchor (100): fill-anchored
SL = 90*(1-0.10) = 81, TP = 90*(1+0.20) = 108 (vs the decision-anchored 90 / 120).
- `from_fill_sl_hit`: bar3 low 79 <= SL 81 -> STOP fills @81; avg_bought 90, avg_sold
  81, realised_pnl -855, final_cash 9145.
- `from_fill_tp_hit`: bar3 high 110 >= TP 108 -> LIMIT touch fills @108; avg_bought
  90, avg_sold 108, realised_pnl +1710, final_cash 11710.
- `from_fill_held`: bars stay strictly between 81 and 108 -> position held; orders.csv
  shows ENTRY FILLED (price 100 = the decision price stamped on the parent) + SL STOP
  SELL PENDING @81 + TP LIMIT SELL PENDING @108; summary trade_count 0, final_equity
  10760 (open 95 @ last close 98 + cash 1450), non-flat.

Each leaf was frozen ONE AT A TIME (`--freeze`), re-run WITHOUT `--freeze` green, and
its frozen SL/TP levels cross-checked against the VERIFY-note hand-derivation before
the freeze was locked.

## Verification Results

- `poetry run pytest tests/e2e/sltp -x` -> 6 passed (all SLTP leaves green).
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` -> 3 passed
  (byte-exact — no engine change, oracle untouched).
- `poetry run pytest tests/e2e` -> 30 passed (24 prior + 6 new SLTP leaves, no regression).
- Acceptance greps: `PercentFromDecision` present in all 3 `from_decision_*/scenario.py`;
  `PercentFromFill` present in all 3 `from_fill_*/scenario.py`; `grep -q PENDING` OK on
  both `*_held/golden/orders.csv`.
- No `itrader/` source changed (`git status --short` shows only test-leaf folders), so
  `mypy --strict` is unaffected.

## TDD Gate Compliance (tdd="true" tasks)

Each leaf followed the E2E freeze discipline as its RED/GREEN cycle: author bars +
scenario + VERIFY note (the hand-derivation is the correctness proof), freeze ONE leaf
at a time via `--freeze` (the harness mechanically refuses >1 selected test), then
re-run WITHOUT `--freeze` and diff green against the hand-verified golden. The freeze
proves stability; the VERIFY note proves correctness (T-07-11/T-07-12/T-07-13
mitigation). For the held leaves the anti-Pitfall-4 gate is the opt-in orders.csv
(SL+TP children PENDING) + summary trade_count=0 — never an empty trades.csv alone.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Re-authored from_fill bars to satisfy the cash-reservation invariant**
- **Found during:** Task 2 (first `--freeze` of `from_fill_sl_hit`)
- **Issue:** The initial Task-2 bars put the next-bar open ABOVE the decision close
  (open 110 > close 100) to make the fill anchor distinct. But the admission cash-
  reservation gate sizes/reserves off the DECISION close (qty 95 @ 100 = 9_500
  reserved), while the fill at 110 cost 95*110 = 10_450 > the 10_000 balance — the
  portfolio `assert_funds_invariant` re-raised (the backtest fail-fast seam fired).
- **Fix:** Re-authored all three `from_fill_*` bars so the next-bar open is BELOW the
  decision close (open 90 < close 100). The fill anchor (90) is still demonstrably
  distinct from a decision anchor (100) — fill SL/TP = 81/108 vs decision 90/120 —
  AND the entry notional (95*90 = 8_550) now stays within the decision-priced
  reservation. No engine change; the invariant correctly caught an under-reserved fill.
- **Files modified:** tests/e2e/sltp/from_fill_{sl_hit,tp_hit,held}/{bars.csv,scenario.py}
- **Commit:** e0c8cf5

**2. [Rule 1 - Bug] Corrected the from_fill_held VERIFY-note ENTRY price**
- **Found during:** Task 2 (freeze vs VERIFY cross-check of `from_fill_held`)
- **Issue:** The VERIFY-note orders-snapshot table initially wrote the ENTRY row's
  `price` as 90 (the fill price). The frozen golden shows 100 — the order entity's
  `price` column is the DECISION price stamped on the MARKET parent at assembly, NOT
  the matching-engine fill price. The fill price (90) anchors the CHILDREN (SL=81,
  TP=108); the parent's own price stays at the decision value.
- **Fix:** Corrected the VERIFY-note ENTRY row to price 100 with an explanatory note
  (the children's 81/108 are the visible SLTP-02 fill-anchor evidence). The frozen
  golden was correct; only the hand-note's ENTRY price was wrong. No code/golden change.
- **Files modified:** tests/e2e/sltp/from_fill_held/scenario.py (VERIFY note only)
- **Commit:** e0c8cf5

No other deviations — the PercentFromDecision leaves (Task 1) froze exactly as planned
on the first freeze with no VERIFY-note corrections.

## Known Stubs

None. Every leaf runs a real fill (or a real held-to-end open position) end-to-end
through the real bracket-assembly / fill-anchored-child paths; all SL/TP levels,
prices, and PENDING child statuses are sourced from real engine state, not placeholders.

## Threat Flags

None — pure in-repo test scaffolding (data leaves + VERIFY notes). No `itrader/` source
changed; no new network/auth/schema surface; no package installs (T-07-SC accepted).

## Self-Check: PASSED

All created leaf files verified present on disk (6 leaves x {`__init__`, `scenario`,
`test_scenario`, `bars.csv`, golden artifacts} + the `sltp/__init__.py`); both task
commits verified in git log:
- f47f308 test(07-04): author + hand-verify + freeze PercentFromDecision SLTP leaves
- e0c8cf5 test(07-04): author + hand-verify + freeze PercentFromFill SLTP leaves
