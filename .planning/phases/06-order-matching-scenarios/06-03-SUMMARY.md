---
phase: 06-order-matching-scenarios
plan: 03
subsystem: testing
tags: [e2e, golden-master, matching-engine, bracket, oco, stop-beats-limit, orders-snapshot]

# Dependency graph
requires:
  - phase: 06-order-matching-scenarios
    plan: 01
    provides: shared ScenarioSpec/ScriptedEmitter, oracle-inert on_tick hook, build_orders_snapshot serializer + opt-in orders.csv freeze/diff wiring, MATCH-01 canonical leaf template
provides:
  - MATCH-04 bracket OCO full-lifecycle leaf (oco_lifecycle) — frozen trades+summary+orders goldens
  - MATCH-05 same-bar STOP-beats-LIMIT priority leaf (stop_beats_limit) — frozen trades+summary+orders goldens
affects: [06-order-matching-scenarios, e2e-coverage-matrix]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bracket leaf authoring on the Plan 01 shared infra: bars.csv + date-keyed ScriptedEmitter script with explicit Decimal sl/tp, no new strategy class"
    - "Opt-in orders.csv golden seeded with a header-only placeholder so --freeze writes it (conftest opt-in: presence = assertion)"
    - "Arming-bar isolation: author the parent-fill bar so neither child triggers, then a dedicated later bar shapes the single fill-shape under test"

key-files:
  created:
    - tests/e2e/matching/brackets/__init__.py
    - tests/e2e/matching/brackets/oco_lifecycle/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/brackets/stop_beats_limit/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
  modified: []

key-decisions:
  - "Both brackets use a MARKET entry + explicit Decimal SL/TP children (D-03/D-15) — matches the resolved Open-Question 1 (no STOP-entry bracket parent)"
  - "TP touch authored as open<trigger but high>=trigger so the TP fills at the trigger 140 (clean round number) per the SELL-LIMIT in-bar-touch formula"
  - "STOP-beats-LIMIT double-trigger bar: open=120, high=132 (>=TP), low=108 (<=SL); SL fills at MIN(open,110)=110 per the SELL-STOP pessimistic formula"
  - "Each leaf seeds a header-only golden/orders.csv before --freeze so the conftest opt-in branch writes the snapshot (it only (re)writes orders.csv if one already exists)"

patterns-established:
  - "Per-bracket-leaf one-shape-per-folder: a dedicated double-/single-trigger bar isolates exactly one lifecycle assertion (D-11)"

requirements-completed: [MATCH-04, MATCH-05]

# Metrics
duration: ~20min
completed: 2026-06-10
---

# Phase 6 Plan 03: Bracket OCO Lifecycle + STOP-beats-LIMIT Priority Summary

**Authored the two bracket-lifecycle E2E goldens on the Plan 01 shared infra — MATCH-04 (OCO full lifecycle: dormant children -> arm-on-parent-fill -> sibling OCO-cancel) and MATCH-05 (same-bar STOP-beats-LIMIT priority) — each hand-verified and `--freeze`-locked with the OPT-IN orders.csv snapshot (order state is the assertion) plus trades.csv + summary.json, BTCUSD, zero-fee/zero-slippage.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2 / 2
- **Files created:** 15 (1 cluster `__init__` + 2 leaves × 7 files each)
- **Files modified:** 0 (no shared-infra file touched — parallel-safe with Plans 02/04/05)

## Accomplishments

### Task 1 — MATCH-04 bracket OCO full lifecycle leaf (commit a323e66)
- Authored `tests/e2e/matching/brackets/oco_lifecycle/` through the Plan 01 shared infra (`ScenarioSpec` + date-keyed `ScriptedEmitter`). MARKET BUY entry with explicit Decimal `sl=100`/`tp=140` (D-15).
- Lifecycle: parent fills bar2 @120 (next-bar-open); children arm in pass-2 against bar2 (neither triggers: high125<TP, low119>SL); bar3 the TP LIMIT(SELL @140) touches (open130<140, high142>=140 -> in-bar touch @140) and the SL STOP(SELL @100) is OCO-cancelled.
- Hand-derived & confirmed against the freeze: realised_pnl 1_583.333… = (140-120)*475/6, final_equity 11_583.333…, slippage 0.0/16.0; orders.csv = ENTRY FILLED @120, TP FILLED @140, SL CANCELLED @100 (statuses PENDING/FILLED/CANCELLED, no UUIDs).

### Task 2 — MATCH-05 same-bar STOP-beats-LIMIT priority leaf (commit 8c5aadc)
- Authored `tests/e2e/matching/brackets/stop_beats_limit/` mirroring Task 1. MARKET BUY entry with explicit Decimal `sl=110`/`tp=130` (D-15).
- The single double-trigger bar3 (open=120, **high=132 >= TP 130 AND low=108 <= SL 110**) reaches BOTH legs; `_pick_bracket_winner` returns the STOP -> SL fills at MIN(open,110)=110 (SELL-STOP pessimistic formula), TP OCO-cancelled.
- Hand-derived & confirmed against the freeze: realised_pnl -791.666… = (110-120)*475/6 (a loss), final_equity 9_208.333…, win_rate 0.0, slippage 0.0/-14.0; orders.csv = ENTRY FILLED @120, SL FILLED @110, TP CANCELLED @130 (proving STOP beats LIMIT same-bar).

## Deviations from Plan

None - plan executed exactly as written.

## Verification Evidence

Run with `PYTHONPATH="$PWD"` per the worktree .venv-shadowing note in MEMORY.md:
- `pytest tests/e2e/matching/brackets/oco_lifecycle -v` — 1 passed (vs frozen trades+summary+orders).
- `pytest tests/e2e/matching/brackets/stop_beats_limit -v` — 1 passed (vs frozen trades+summary+orders).
- `pytest tests/e2e/matching/brackets -k "oco or priority or stop_beats" -v` — 2 passed in 0.10s (the plan verification command), warning-clean under `filterwarnings=["error"]`.
- Hand-verification: both leaves' frozen `orders.csv` + `trades.csv` + `summary.json` match the per-leaf VERIFY-note derivations exactly (TP touch @140 / SL pessimistic @110; ENTRY/SL/TP roles; PENDING/FILLED/CANCELLED, no ACTIVE, no UUIDs; ticker BTCUSD).

## Parallel-Safety Note

No shared-infra file was created or modified (conftest.py, scenario_spec.py, scripted_emitter.py, orders.py, the run loop are all untouched). This plan edited ONLY its own two leaf folders under `tests/e2e/matching/brackets/` plus the new cluster `__init__.py`, so it is parallel-safe with Plans 02/04/05 (D-13).

## Self-Check: PASSED
