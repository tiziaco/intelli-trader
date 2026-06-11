---
phase: 06-order-matching-scenarios
plan: 01
subsystem: testing
tags: [e2e, golden-master, matching-engine, scripted-emitter, on-tick, orders-snapshot]

# Dependency graph
requires:
  - phase: 04-e2e-harness-framework
    provides: run_scenario harness, --freeze discipline, exact no-tolerance diff, the single_market_buy canary copy-template
  - phase: 05-strategy-interface-hardening
    provides: frozen pydantic BaseStrategyConfig with per-instance OrderType, buy()/sell() sugar, FractionOfCash sizing policy
provides:
  - Shared tests/e2e/scenario_spec.py (ScenarioSpec/PortfolioSpec/Action) imported by every later matching leaf
  - Generic date-keyed ScriptedEmitter (one fixture covers all fill-shapes; order_type per-instance)
  - Oracle-inert on_tick hook on TradingSystem.run/_run_backtest (default None = byte-exact)
  - itrader/reporting/orders.py build_orders_snapshot serializer + ORDER_SNAPSHOT_COLUMNS
  - conftest opt-in orders.csv freeze+diff branch + actions->on_tick operator translation
  - MATCH-01 market next-bar-open leaf (frozen, hand-verified) — the D-13 proof
affects: [06-02, 06-03, 06-04, 06-05, order-matching-scenarios, e2e-coverage-matrix]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Date-keyed scripted emitter (decision-bar date -> scripted action) replaces bar-count keying"
    - "Oracle-inert optional callback hook (default None = byte-exact production path)"
    - "Opt-in golden artifact (presence = assertion) extended from equity.csv to orders.csv"
    - "Predicate-resolved operator MODIFY/CANCEL via the real OrderHandler round-trip (UUID order.id, never int)"

key-files:
  created:
    - tests/e2e/scenario_spec.py
    - tests/e2e/strategies/scripted_emitter.py
    - itrader/reporting/orders.py
    - tests/e2e/matching/entries/market_next_open/{scenario.py,test_scenario.py,bars.csv,golden/trades.csv,golden/summary.json}
  modified:
    - itrader/trading_system/backtest_trading_system.py
    - tests/e2e/conftest.py

key-decisions:
  - "Promoted ScenarioSpec/PortfolioSpec to a shared module (GAP #4) so the new actions field is defined once"
  - "on_tick fires post-bar (after process_events + record_metrics) so an amendment lands before the NEXT bar's matching (A2)"
  - "Snapshot status serializes via o.status.name => PENDING for never-filled orders (GAP #1, no OrderStatus.ACTIVE)"
  - "MATCH-01 mirrors the canary economics (buy@120/sell@140) to prove the date-keyed infra is equivalent"

patterns-established:
  - "Generic ScriptedEmitter: parallel leaves author only bars + script, never a new strategy class"
  - "orders-snapshot serializer joins the reporting family (pandas+stdlib, duck-typed input, Decimal->float at edge, same FLOAT_FORMAT)"

requirements-completed: [MATCH-01]

# Metrics
duration: ~25min
completed: 2026-06-10
---

# Phase 6 Plan 01: Order-Matching Shared Infra + MATCH-01 Proof Summary

**Built all Phase 6 shared E2E test infrastructure (date-keyed scripted emitter, shared ScenarioSpec/Action, oracle-inert on_tick hook, orders-snapshot serializer + opt-in conftest wiring) and proved it end-to-end with the hand-verified, frozen MATCH-01 market next-bar-open leaf — with the BTCUSD golden oracle held byte-exact.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3 / 3
- **Files created:** 8 (2 shared-infra + 1 serializer + 5 leaf files incl. 2 goldens + 3 __init__)
- **Files modified:** 2 (backtest run loop + conftest)

## Accomplishments

### Task 1 — Shared spec module + generic date-keyed emitter (commit c698bdd)
- Promoted `ScenarioSpec`/`PortfolioSpec` verbatim into `tests/e2e/scenario_spec.py` and added the frozen `Action` dataclass (predicate-resolved MODIFY/CANCEL, D-07) plus `ScenarioSpec.actions` (default empty tuple = oracle-inert, D-06).
- Generalized the Phase 4 canary into `ScriptedEmitter` (`tests/e2e/strategies/scripted_emitter.py`): keys off `bars.index[-1]` decision-bar date (D-04), `order_type` is a per-instance `BaseStrategyConfig` field (D-03, Pitfall 3), `max_window=100`.
- Verify command exits 0: constructing with `order_type=OrderType.LIMIT` yields `config.order_type is OrderType.LIMIT`.

### Task 2 — on_tick hook + orders serializer + conftest wiring (commit c064da6)
- Added `Callable` import + optional `on_tick` to `run()`/`_run_backtest()` (TABS). Invoked post-bar; default `None` changes zero bytes on the production path.
- Created `itrader/reporting/orders.py` (`build_orders_snapshot`, `ORDER_SNAPSHOT_COLUMNS`, `_order_role`): business columns only, no UUID/wall-clock, `PENDING` not `ACTIVE` (GAP #1), Decimal->float at the edge, same sort/empty-safe idiom as `frames.py`.
- Wired conftest: `_make_on_tick` predicate resolution via the real `modify_order`/`cancel_order` (passing the UUID `order.id`, GAP #2), `_ORDERS_IDENTITY_COLUMNS`/`_ORDERS_SORT_KEYS`, opt-in orders.csv freeze+diff cloned from equity.csv, snapshot threaded through `_assemble`/`_freeze`/`_diff`.
- Oracle byte-exact (134 trades / `final_equity 46189.87730727451`); snapshot import check exits 0; smoke canary green; `mypy` clean on both changed `itrader/` files.

### Task 3 — MATCH-01 leaf, hand-verified + frozen (commit fdadb74)
- Authored `tests/e2e/matching/entries/market_next_open/` through the new infra (shared spec + date-keyed emitter). Pure-fill (D-09): froze `trades.csv` + `summary.json`, NO `orders.csv`.
- Hand-derived in the VERIFY note and confirmed against the freeze: one LONG BTCUSD round-trip — buy @120 (2020-01-03, bar2 open), sell @140 (2020-01-05, bar4 open), qty 250/3, `realised_pnl 1666.666...`, `final_equity 11666.666...`, `slippage_entry/exit 6.0/6.0`, `trade_count 1`. BTCUSD ticker (Pitfall 1), zero-fee/zero-slippage (D-14).
- Freeze done one-scenario-at-a-time via the path selector; leaf green against the frozen golden.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Evidence

All four plan-verification commands pass (run with `PYTHONPATH="$PWD"` per the worktree .venv-shadowing note in MEMORY.md):
- `pytest tests/integration/test_backtest_oracle.py` — 3 passed (oracle byte-exact, on_tick=None oracle-dark).
- `pytest tests/e2e/smoke/single_market_buy` — 1 passed (canary unaffected; no actions => on_tick None).
- `pytest tests/e2e/matching/entries/market_next_open` — 1 passed (MATCH-01 vs frozen golden).
- `python -c "from tests.e2e.scenario_spec import ScenarioSpec, PortfolioSpec, Action"` + the Task 1/2 import checks — exit 0.
- Combined run: 5 passed in 5.00s.

## Wave-2 Precondition

All 5 shared-infra pieces are committed (scenario_spec.py, scripted_emitter.py, on_tick hook, orders.py serializer, conftest opt-in wiring). Parallel leaf plans (02-05) author ONLY their own `tests/e2e/matching/<cluster>/<leaf>/` folder and must NOT touch any file this plan created/modified (conftest.py, scenario_spec.py, scripted_emitter.py, orders.py, the run loop). The precondition for the parallel wave is satisfied.

## Self-Check: PASSED
