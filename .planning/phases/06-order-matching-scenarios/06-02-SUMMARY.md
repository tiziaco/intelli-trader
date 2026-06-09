---
phase: 06-order-matching-scenarios
plan: 02
subsystem: testing
tags: [e2e, golden-master, matching-engine, limit, stop, gap-fill, pure-fill]

# Dependency graph
requires:
  - phase: 06-order-matching-scenarios
    plan: 01
    provides: shared ScenarioSpec/PortfolioSpec, date-keyed ScriptedEmitter (order_type per-instance), run_scenario harness + --freeze discipline, MATCH-01 canonical leaf template
provides:
  - MATCH-02 limit_touch leaf (BUY LIMIT in-bar touch -> fill AT trigger)
  - MATCH-02 limit_gap_through leaf (BUY LIMIT favorable gap -> fill at better OPEN)
  - MATCH-03 stop_gap_up leaf (BUY STOP gap-up -> fill at MAX(open,trigger))
  - MATCH-03 stop_gap_down leaf (SELL STOP gap-down -> fill at MIN(open,trigger), authored as a long's stop-loss EXIT under the LONG-ONLY guard)
affects: [06-order-matching-scenarios, e2e-coverage-matrix]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Contrived-bar entry pricing (D-02): decision-bar close == LIMIT/STOP trigger; following bars author touch/gap-through/gap-up/gap-down"
    - "Pessimistic vs limit-or-better gap fills exercised with round, hand-derivable fill prices"
    - "SELL STOP gap-down exercised as a long's stop-loss EXIT (v1.1 LONG-ONLY fallback) instead of a standalone short entry"

key-files:
  created:
    - tests/e2e/matching/entries/limit_touch/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json}
    - tests/e2e/matching/entries/limit_gap_through/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json}
    - tests/e2e/matching/entries/stop_gap_up/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json}
    - tests/e2e/matching/entries/stop_gap_down/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json}
  modified: []

key-decisions:
  - "stop_gap_down authored via the PLAN's documented fallback: v1.1 StrategiesHandler.add_strategy hard-rejects any non-LONG_ONLY direction (strategies_handler.py:225), so a standalone short SELL-STOP entry is structurally impossible. The SELL STOP gap-down formula is exercised as the stop-loss EXIT leg of a MARKET-entry long (sl=110 bracket child) instead — MIN(open,trigger) is identical and hand-derived."
  - "limit/stop EXITS inherit the per-instance order_type from the emitter (Pitfall 3), so leaves authored the exit fill-bar to land a clean round-trip through that same order type (SELL LIMIT gap-through for limit leaves, SELL STOP for stop_gap_up)."
  - "Sizing anchors on the DECISION-bar close, not the gapped fill price — so a favorable/pessimistic gap changes the fill but not the quantity (475/6 units for the 0.95*10000/120 leaves)."

patterns-established:
  - "Freeze-then-verify loop: derive expected fills/PnL by hand in the VERIFY note, --freeze one leaf at a time, confirm the frozen real-engine golden matches the derivation (re-author bars or correct the note on any mismatch)."

requirements-completed: [MATCH-02, MATCH-03]

# Metrics
duration: ~30min
completed: 2026-06-10
---

# Phase 6 Plan 02: LIMIT/STOP Entry Fill-Shape Leaves Summary

**Authored the four MATCH-02/MATCH-03 LIMIT/STOP entry fill-shape E2E goldens (limit_touch, limit_gap_through, stop_gap_up, stop_gap_down) as self-contained pure-fill leaves on the Plan 01 shared infra — each hand-derived in a VERIFY note, frozen one-at-a-time against the real matching engine, and green vs its frozen golden, touching ONLY its own leaf folder (parallel-safe with Plans 03/04/05).**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 / 2
- **Files created:** 24 (4 leaves x 6 files: __init__ + bars.csv + scenario.py + test + golden/trades.csv + golden/summary.json)
- **Files modified:** 0 (no shared-infra file touched)

## Accomplishments

### Task 1 — MATCH-02 LIMIT entry leaves (commit 9ed52cd)
- `limit_touch`: BUY LIMIT, decision-bar close = trigger 120; following bar opens 124 (> T) with low 118 (<= T) -> in-bar TOUCH arm fills AT the trigger 120. SELL LIMIT exit gaps through at open 150. One LONG round-trip: avg_bought 120, avg_sold 150, realised_pnl 2_375, final_equity 12_375, slippage 0.0/10.0.
- `limit_gap_through`: BUY LIMIT, trigger 120; following bar OPENS 116 (<= T) -> favorable gap-through arm fills at the better OPEN 116. SELL LIMIT exit at 150. avg_bought 116, avg_sold 150, realised_pnl 2_691.6666..., final_equity 12_691.6666..., slippage -4.0/10.0.
- Both pure-fill (D-09): trades.csv + summary.json only, NO orders.csv. Ticker BTCUSD, order_type=OrderType.LIMIT, exchange=None.

### Task 2 — MATCH-03 STOP entry leaves (commit 6188fef)
- `stop_gap_up`: BUY STOP, trigger 120; following bar opens 126 (> T) with high 130 (>= T) -> pessimistic gap-up arm fills at MAX(126,120)=126. SELL STOP exit gaps down to MIN(146,150)=146. avg_bought 126, avg_sold 146, realised_pnl 1_583.3333..., final_equity 11_583.3333..., slippage 6.0/-4.0.
- `stop_gap_down`: SELL STOP gap-down formula exercised as the stop-loss EXIT of a MARKET-entry long (see Deviations). MARKET BUY fills @124; the attached sl=110 SELL STOP child gaps down (bar3 open 104 < trigger 110, low 100 <= 110) -> MIN(104,110)=104. One LONG round-trip stop-out: avg_bought 124, avg_sold 104, realised_pnl -1_583.3333..., final_equity 8_416.6666..., slippage 4.0/-22.0.
- Both pure-fill (D-09): trades.csv + summary.json only, NO orders.csv.

## Deviations from Plan

### [Rule 3 - Blocking issue, anticipated by PLAN NOTE] stop_gap_down authored as a long's stop-loss exit, not a standalone short entry

- **Found during:** Task 2.
- **Issue:** The plan's primary suggestion was a standalone SELL STOP *short entry* (`direction=LONG_SHORT`). `StrategiesHandler.add_strategy` (itrader/strategy_handler/strategies_handler.py:225) **hard-rejects any non-LONG_ONLY direction** with `ValueError("Only LONG_ONLY is admissible until the margin/liquidation milestone")` — shorting is gated to v1.2. A `LONG_SHORT` emitter cannot even be registered, so a standalone short SELL-STOP entry is structurally impossible in v1.1.
- **Fix:** Used the plan's OWN documented fallback (PLAN action NOTE + Open Q1): author the SELL STOP as the stop-LOSS EXIT leg of an open long. A MARKET BUY entry opens a long with an attached `sl=110`; the bracket assembler builds that `sl` as a SELL STOP child (order_manager.py:641, action inverted to SELL, carrying the entry quantity). The following bars gap the price DOWN through the stop so the SELL STOP fills pessimistically at MIN(open, trigger) within LONG-ONLY — the exact MATCH-03 gap-down formula, hand-derived in the VERIFY note.
- **Files modified:** tests/e2e/matching/entries/stop_gap_down/{bars.csv,scenario.py} (own leaf only).
- **Commit:** 6188fef.

### Note: VERIFY-note arithmetic corrected against the frozen real-engine golden (not a plan deviation)
- For `limit_gap_through`, the initial hand-derivation mis-stated realised_pnl (a stale intermediate); for `stop_gap_down`, the exit_date timing (a resting child fills on its trigger bar, no next-bar delay). Both VERIFY notes were corrected to match the frozen real-engine golden BEFORE the freeze was committed. This is the freeze-then-verify discipline working as intended — the goldens are the real engine's output, the notes track them exactly.

## Verification Evidence

All run with `PYTHONPATH="$PWD"` per the worktree .venv-shadowing note in MEMORY.md:
- `pytest tests/e2e/matching/entries -k "limit or stop" -v` — 4 passed, 1 deselected (the MATCH-01 market leaf). All four entry leaves green vs frozen goldens.
- `pytest ... -W error` — 4 passed, zero warnings (warning-clean under filterwarnings=["error"]).
- Each leaf's `golden/` contains exactly `trades.csv` + `summary.json` — NO `orders.csv` (D-09 pure-fill confirmed).
- `git diff --name-only 385f17f HEAD` — touches ONLY the four own leaf folders; zero shared-infra files modified (parallel-safe with Plans 03/04/05).
- Each leaf's frozen fill prices match its VERIFY-note hand-derivation: limit_touch avg_bought 120 (touch); limit_gap_through avg_bought 116 (gap-through); stop_gap_up avg_bought 126 (MAX gap-up); stop_gap_down avg_sold 104 (MIN gap-down).

## Self-Check: PASSED

All 20 created leaf files exist on disk; both per-task commits (9ed52cd, 6188fef) are present in git log.
