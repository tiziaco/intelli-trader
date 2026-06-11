---
phase: 06-order-matching-scenarios
plan: 05
subsystem: testing
tags: [e2e, golden-master, matching-engine, operator, modify, cancel, never-fill, orders-snapshot]

# Dependency graph
requires:
  - phase: 06-order-matching-scenarios
    plan: 01
    provides: shared ScenarioSpec/Action, date-keyed ScriptedEmitter, oracle-inert on_tick hook, orders-snapshot serializer, conftest opt-in orders.csv + actions->on_tick operator translation
provides:
  - MATCH-07 operator CANCEL leaf (tests/e2e/matching/operator/cancel) — far-from-market BUY LIMIT cancelled via the real cancel_order round-trip, ends CANCELLED
  - MATCH-07 operator MODIFY re-price leaf (tests/e2e/matching/operator/modify_reprice) — BUY LIMIT re-priced 120->125 so it fills at the NEW level
  - MATCH-07 operator MODIFY re-size leaf (tests/e2e/matching/operator/modify_resize) — BUY LIMIT re-sized 79.166->50 before it fills
  - MATCH-08 never-fill leaf (tests/e2e/matching/never_fill) — far-from-market BUY LIMIT ends PENDING (GAP #1/D-10), zero trades
affects: [order-matching-scenarios, e2e-coverage-matrix]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Operator MODIFY/CANCEL leaf: ScenarioSpec.actions -> harness on_tick -> the REAL OrderHandler.modify_order/cancel_order round-trip, predicate-resolved by ticker+PENDING, passing order.id (UUID, never int)"
    - "Funded re-price/re-size: keep the post-amendment fill within the signal-time reservation (re-price up only within funded headroom; re-size DOWN) so hand-derivation stays clean"
    - "never-fill as-is assertion: a BUY LIMIT below every later bar's open AND low ends PENDING (NOT ACTIVE) at run end — no run-end expiry on the backtest path"

key-files:
  created:
    - tests/e2e/matching/operator/__init__.py
    - tests/e2e/matching/operator/cancel/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/operator/modify_reprice/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/operator/modify_resize/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
    - tests/e2e/matching/never_fill/{__init__.py,bars.csv,scenario.py,test_scenario.py,golden/trades.csv,golden/summary.json,golden/orders.csv}
  modified: []

key-decisions:
  - "modify_reprice re-prices UP (120->125) but within funded headroom: qty sized at 120 (79.166), fill at 125 costs 9_895.83 < 10_000 cash — so the re-price is load-bearing (original @120 never fills) AND the fill is funded"
  - "modify_resize re-sizes DOWN (79.166->50) so the smaller fill is always funded; a clean 50-unit round-trip lands"
  - "cancel + never_fill reuse the same far-from-market BUY LIMIT @80 (trigger = decision-bar close 80, below every later bar's open>=120 and low>=119); cancel removes it mid-run (CANCELLED), never_fill leaves it (PENDING)"
  - "the SELL exit in the modify leaves is also a LIMIT (order_type is a per-INSTANCE config field, D-03); a SELL LIMIT @144 gap-fills at the next bar's open 150 — same exit price as MARKET would give"

patterns-established:
  - "Operator leaf authoring: name the target by ticker only in ScenarioSpec.actions; the shared harness owns predicate resolution (sole PENDING order) and the UUID order.id round-trip (GAP #2) — leaves never reference a UUID"

requirements-completed: [MATCH-07, MATCH-08]

# Metrics
duration: ~30min
completed: 2026-06-10
---

# Phase 6 Plan 05: Operator MODIFY/CANCEL + Never-Fill Leaves Summary

**Authored the three operator MATCH-07 leaves (cancel, modify re-price, modify re-size) that exercise the only new Phase 6 seam — ScenarioSpec.actions -> harness on_tick -> the REAL OrderHandler.modify_order/cancel_order round-trip — plus the MATCH-08 far-from-market never-fill leaf that freezes the order as PENDING; all four are hand-verified, --freeze-locked, and green against the Plan 01 shared infra, with no shared-infra file touched.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 / 2
- **Files created:** 30 (4 leaf folders x [__init__ + bars.csv + scenario.py + test_scenario.py + 3 goldens] + 1 operator package __init__; 2 leaves share the operator/ parent)
- **Files modified:** 0 (parallel-safe: only this plan's own leaf folders)

## Accomplishments

### Task 1 — operator cancel + modify_reprice leaves (commit 3efa7b9)

- **operator/cancel:** a BUY LIMIT rests at the decision-bar close (80) — far below every later bar's range (open >= 120, low >= 119), so absent the operator it would rest forever. `actions=[Action(bar_date="2020-01-03", kind="cancel", ticker="BTCUSD")]` resolves the sole PENDING BTCUSD order at bar2 and calls the REAL `cancel_order(order.id, portfolio_id)`. Frozen `orders.csv`: STANDALONE / LIMIT / BUY / **CANCELLED** / price 80 / filled_quantity 0; `trades.csv` empty.
- **operator/modify_reprice:** a BUY LIMIT rests at 120 (unreachable — later lows >= 124). `Action(kind="modify", new_price=Decimal("125"))` at bar2 re-prices it; bar3 low 124 <= 125 fills at the NEW limit 125 (proving the modify took effect — the original 120 never fills). A SELL LIMIT @144 exits at the next bar's open 150. Frozen `orders.csv`: BUY **FILLED at price 125.0** (the new level), qty/filled 79.16666...; `trades.csv`: LONG buy@125/sell@150, realised_pnl 1_979.16666...

### Task 2 — modify_resize + never_fill leaves (commit d69348b)

- **operator/modify_resize:** a BUY LIMIT rests at 120 (reachable by bar3, low 118). `Action(kind="modify", new_quantity=Decimal("50"))` at bar2 re-sizes it from the original 79.16666... DOWN to 50 BEFORE it fills; bar3 fills 50 units at 120. SELL @144 exits at 150. Frozen `orders.csv`: BUY **FILLED, quantity == filled_quantity == 50.0** (the resize took effect); `trades.csv`: LONG 50@120/50@150, realised_pnl 1_500.0, final_equity 11_500.0.
- **never_fill (MATCH-08):** a BUY LIMIT @80 below every later bar's open AND low never triggers; the run completes cleanly; NO actions. Frozen `orders.csv`: exactly ONE row, **PENDING** (NOT ACTIVE — GAP #1/D-10), filled_quantity 0; `trades.csv` empty; `summary.json` valid no-trade scalars (trade_count 0, final_equity 10_000).

## Deviations from Plan

None - plan executed exactly as written.

## Verification Evidence

Run with `PYTHONPATH="$PWD"` per the worktree .venv-shadowing note in MEMORY.md.

- `pytest tests/e2e/matching/operator/cancel tests/e2e/matching/operator/modify_reprice -v` — 2 passed (Task 1 acceptance command).
- `pytest tests/e2e/matching/operator/modify_resize tests/e2e/matching/never_fill -v` — 2 passed (Task 2 acceptance command).
- `pytest tests/e2e/matching/operator tests/e2e/matching/never_fill -v` — 4 passed (plan verification command, all leaves green vs frozen goldens incl. orders.csv).
- Each leaf is warning-clean under `filterwarnings=["error"]`; goldens carry no UUIDs; ticker BTCUSD throughout; statuses are PENDING/FILLED/CANCELLED only (no ACTIVE).
- `git diff 385f17f..HEAD -- tests/e2e/conftest.py tests/e2e/scenario_spec.py tests/e2e/strategies/scripted_emitter.py itrader/reporting/orders.py itrader/trading_system/backtest_trading_system.py` — EMPTY (no shared-infra file touched; parallel-safe with Plans 02/03/04).

## Hand-Verification Cross-Checks (against the frozen goldens)

| Leaf | Final order state | Trades | Key proof |
|------|-------------------|--------|-----------|
| cancel | STANDALONE LIMIT BUY CANCELLED @80, filled 0 | none | the real cancel_order round-trip removed the resting order |
| modify_reprice | STANDALONE LIMIT BUY FILLED @125, filled 79.166 | LONG buy@125/sell@150, pnl 1_979.166 | filled at the NEW price 125 (original 120 unreachable) |
| modify_resize | STANDALONE LIMIT BUY FILLED @120, qty/filled 50 | LONG 50@120/50@150, pnl 1_500.0 | filled the RESIZED 50 (not the original 79.166) |
| never_fill | STANDALONE LIMIT BUY PENDING @80, filled 0 | none | PENDING (not ACTIVE) at run end, clean completion |

## Threat Flags

None — offline E2E test leaves only; the operator round-trip uses the existing real OrderHandler API and the Plan 01-owned on_tick hook. No new production attack surface (T-06-05-01/02 dispositions: accept).

## Self-Check: PASSED

- All four `golden/orders.csv` files exist (FOUND x4).
- Both task commits present in `git log`: 3efa7b9, d69348b.
- All four leaves green against frozen goldens (4 passed).
