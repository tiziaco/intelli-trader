---
phase: 06-order-matching-scenarios
plan: 04
subsystem: testing
tags: [e2e, golden-master, matching-engine, gap-fill, oco, orders-snapshot]

# Dependency graph
requires:
  - phase: 06-order-matching-scenarios
    plan: 01
    provides: shared ScenarioSpec/Action, date-keyed ScriptedEmitter, oracle-inert on_tick hook, build_orders_snapshot serializer + opt-in conftest orders.csv freeze/diff branch
provides:
  - MATCH-06 clean_through_stop leaf (gap clean through a resting STOP — pessimistic gapped fill, frozen)
  - MATCH-06 clean_through_limit leaf (gap clean through a resting LIMIT — better-open gapped fill, frozen)
  - MATCH-06 gap_past_both_legs leaf (bracket bar gaps past BOTH legs — STOP wins, one leg fills, TP OCO-cancelled, frozen)
affects: [06-order-matching-scenarios, e2e-coverage-matrix]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Contrived-bar gap authoring (D-02): decision-bar close == trigger T, next bar gaps clean past T so the OPEN is the fill"
    - "Opt-in orders.csv golden seeded as a header-only placeholder so the conftest freeze branch refreshes it"
    - "Per-instance order_type + custom FractionOfCash on ScriptedEmitter to make STOP/LIMIT entries and leave gap-up cash headroom"

key-files:
  created:
    - tests/e2e/matching/gaps/__init__.py
    - tests/e2e/matching/gaps/clean_through_stop/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/gaps/clean_through_limit/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/gaps/gap_past_both_legs/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
  modified: []

key-decisions:
  - "clean_through_stop uses FractionOfCash(0.5) so the gap-UP BUY-STOP entry fill (130 > the 120 reservation trigger) clears the debit-side funds invariant — a 0.95 entry reserved at 120 would fill at 130 and exceed the 10k balance, aborting the fail-fast run"
  - "clean_through_limit keeps the 0.95 default because a BUY LIMIT fills at-or-below its trigger (no headroom issue)"
  - "gap_past_both_legs authored so the entry-fill bar (bar2) does NOT fire either child (low 118 > SL 110, high 122 < TP 130), so the children rest into bar3; bar3 opens at 108 (below SL 110) AND highs to 135 (above TP 130) — both candidates, STOP wins, TP OCO-cancelled"
  - "Each leaf seeds golden/orders.csv as a header-only placeholder first so the conftest opt-in freeze branch (only refreshes orders.csv if one already exists) writes the real snapshot"

requirements-completed: [MATCH-06]

# Metrics
duration: ~30min
completed: 2026-06-10
---

# Phase 6 Plan 04: MATCH-06 Gap Clean-Through Leaves Summary

**Authored the three MATCH-06 gap fill-shape leaves — gap clean through a resting STOP (pessimistic gapped fill), gap clean through a resting LIMIT (better-open gapped fill), and gap past BOTH bracket legs (STOP wins, exactly one leg fills, TP OCO-cancelled) — each hand-verified and `--freeze`-locked on the Plan 01 shared infra, freezing the opt-in orders.csv (statuses PENDING/FILLED/CANCELLED, never ACTIVE, no UUIDs) plus trades.csv + summary.json, touching no shared-infra file.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 / 2
- **Files created:** 24 (3 leaf folders x 8 files: `__init__.py`, `bars.csv`, `scenario.py`, `test_scenario.py`, 3 goldens + the `gaps/__init__.py`)
- **Files modified:** 0 (no shared-infra file edited — parallel-safe)

## Accomplishments

### Task 1 — clean_through_stop + clean_through_limit (commit 628c9f6)
- **clean_through_stop** (`order_type=STOP`, `FractionOfCash(0.5)`): BUY-STOP gap-up entry — decision close 120 = trigger, next bar opens 130 clean past it, fills at the pessimistic `max(open 130, T 120) = 130`; SELL-STOP gap-down exit — trigger 115, next bar opens 108 clean below, fills at `min(open 108, T 115) = 108`. Round-trip LOSS `realised_pnl = -916.666...`, `final_equity 9_083.333...`, slippage `10.0 / -7.0`. orders.csv: two STANDALONE FILLED.
- **clean_through_limit** (`order_type=LIMIT`, default `0.95`): BUY-LIMIT gap-down entry — trigger 120, next bar opens 108 clean below, fills at the BETTER `open = 108`; SELL-LIMIT gap-up exit — trigger 140, next bar opens 150 clean above, fills at the BETTER `open = 150`. Round-trip GAIN `realised_pnl = 3_325.0`, `final_equity 13_325.0`, slippage `-12.0 / 10.0`. orders.csv: two STANDALONE FILLED.
- Both hand-derived in the VERIFY note from the exact `_evaluate` formulas; frozen one-at-a-time; green against the frozen goldens.

### Task 2 — gap_past_both_legs (commit a259230)
- MARKET-entry bracket with explicit `sl=110`, `tp=130` (D-15). Parent fills at bar2 open 120; the same-bar child evaluation fires NEITHER leg (low 118 > SL 110, high 122 < TP 130), so the SL/TP children rest into bar3.
- bar3 GAPS past BOTH legs AND the open itself is past a leg (open 108 < SL 110; high 135 >= TP 130) — distinguishing it from MATCH-05's in-bar double trigger. Both legs are candidates; `_pick_bracket_winner` prefers the STOP -> SL fills at the pessimistic gapped `min(open 108, T 110) = 108`; the TP is OCO-CANCELLED.
- orders.csv freezes role ENTRY FILLED, role SL FILLED, role TP CANCELLED (`filled_quantity 0` on the cancelled TP). trades.csv: `realised_pnl = -950.0`, `final_equity 9_050.0`, slippage `0.0 / -12.0`.

## Deviations from Plan

None - plan executed exactly as written. The only authoring choice (Rule-2-adjacent correctness, not a deviation) was using `FractionOfCash(0.5)` for clean_through_stop so the gap-UP entry fill stays within the cash balance and the fail-fast backtest does not abort on the debit-side funds invariant; documented in the leaf's module note and key-decisions.

## Verification Evidence

All runs use `PYTHONPATH="$PWD"` per the worktree .venv-shadowing note in MEMORY.md.
- `pytest tests/e2e/matching/gaps/clean_through_stop tests/e2e/matching/gaps/clean_through_limit -v` — 2 passed (Task 1 acceptance command).
- `pytest tests/e2e/matching/gaps/gap_past_both_legs -v` — 1 passed (Task 2 acceptance command).
- `pytest tests/e2e/matching/gaps -k "gap or clean" -v` — 3 passed (plan verification command); all warning-clean under `filterwarnings=["error"]`.
- Every frozen number cross-checked against the per-leaf VERIFY hand-derivation before the freeze was locked.
- `git diff --name-only 385f17f HEAD` lists ONLY the three gap leaf folders — no shared-infra file (conftest.py, scenario_spec.py, scripted_emitter.py, orders.py, run loop) modified (parallel-safe with Plans 02/03/05).

## Self-Check: PASSED
