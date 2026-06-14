---
phase: 06-order-lifecycle-time-in-force
plan: 03
subsystem: order-lifecycle / execution / trading-system
tags: [LIFE-01, time-in-force, EXPIRED, run-end-sweep, reconcile, non-cascade]
requires:
  - "v1.2 Phase 6 reconcile/ + lifecycle/ collaborators (the enabling surface)"
  - "Order.expire_order + OrderStatus.EXPIRED + FillStatus.EXPIRED + OrderCommand.EXPIRE (pre-existing, unwired)"
provides:
  - "LifecycleManager.expire_all_resting() run-end sweep (D-08/D-10)"
  - "SimulatedExchange.on_order OrderCommand.EXPIRE arm"
  - "ReconcileManager EXPIRED arm (_classify + _apply_expired + dispatch elif)"
  - "BacktestRunner run-end sweep + ONE final non-cascading drain"
affects:
  - "every backtest leaf with orders resting at run end (now EXPIRE instead of lingering PENDING)"
tech-stack:
  added: []
  patterns:
    - "ONE retire-a-resting-order pattern: EXPIRE arm is a near-verbatim peer of the CANCEL arm at every seam"
    - "idempotency-for-free via VALID_ORDER_TRANSITIONS[EXPIRED]==[] (no custom already-EXPIRED guard)"
key-files:
  created:
    - tests/unit/order/test_expire_all_resting.py
    - tests/unit/order/test_reconcile_expired.py
    - tests/unit/execution/test_simulated_expire.py
    - tests/integration/test_expire_non_cascade.py
  modified:
    - itrader/order_handler/lifecycle/lifecycle_manager.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/reconcile/reconcile_manager.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/trading_system/backtest_runner.py
    - itrader/core/enums/order.py
    - tests/e2e/matching/never_fill/scenario.py
decisions:
  - "OrderOperationType.EXPIRE_ORDER added (new member) rather than reusing CANCEL_ORDER — distinct audit type for the run-end sweep"
  - "WR-05 orphaned-child cancel block left byte-identical (NOT extended to EXPIRED) — the sweep visits ALL active orders including children, so each child gets its own EXPIRE directly; no parent-driven orphan cancel needed"
  - "no golden --freeze in this plan — the PENDING->EXPIRED drift on 3 e2e leaves is the owner-gated re-baseline owned by Plan 06-04"
metrics:
  duration: ~25 min
  completed: 2026-06-13
---

# Phase 06 Plan 03: Order Lifecycle & Time-in-Force (EXPIRE wiring) Summary

Wired the existing-but-unwired EXPIRED lifecycle by adding a parallel EXPIRE arm at each of
four seams (D-08/D-09/D-10), each a near-verbatim copy of the CANCELLED arm beside it: the
`LifecycleManager.expire_all_resting()` run-end sweep, the `SimulatedExchange.on_order` EXPIRE
arm, the `ReconcileManager` EXPIRED arm (three additive edits, skeleton byte-identical), and the
`BacktestRunner` run-end sweep + one final provably-non-cascading drain. Run-end resting orders
now transition to EXPIRED — nothing lingers PENDING (Success Criterion 1).

## What Was Built

**Task 1 (TDD) — sweep + exchange arm + reconcile arm + Wave-0 unit tests** (`2430889` RED, `202aef6` GREEN):
- `LifecycleManager.expire_all_resting() -> list[OperationResult]` — the peer of `cancel_order`:
  outer loop over `portfolio_handler.get_active_portfolios()`, inner loop over
  `sorted(order_storage.get_active_orders(pf.portfolio_id), key=lambda o: o.id)` (D-10 deterministic
  UUIDv7 stable sort). Per order: `order.expire_order("run end (time-in-force)")` bool guard ->
  `update_order` -> `_brackets.consume(order.id)` (WR-03 symmetry) -> idempotent
  `portfolio_handler.release(...)` (WR-04) -> `OrderEvent(EXPIRE)` carried on a success
  `OperationResult`. The manager never touches the queue (D-18).
- `OrderManager.expire_all_resting()` one-line delegation; `OrderHandler.expire_all_resting()` enqueues
  each returned `OrderEvent(EXPIRE)` (the cancel handler's enqueue idiom).
- `SimulatedExchange.on_order` EXPIRE arm — parallel `elif event.command == OrderCommand.EXPIRE:` to
  CANCEL: `matching_engine.cancel(event.order_id)` bool guard then
  `FillEvent.new_fill('EXPIRED', event, ..., commission=Decimal("0"))`. A non-resting order_id emits
  no spurious fill.
- `ReconcileManager` EXPIRED arm — exactly THREE additive edits: (a) `_classify` line
  `if status == FillStatus.EXPIRED: return True, OrderStatus.EXPIRED`; (b) `_apply_expired(order)` static
  method (`order.expire_order("exchange expiration")`); (c) dispatch `elif ... EXPIRED: self._apply_expired(order)`
  before the defensive else. NO custom already-EXPIRED guard — idempotency is free via
  `VALID_ORDER_TRANSITIONS[EXPIRED] == []` (`add_state_change` returns False on EXPIRED->EXPIRED).
  The `should_release`/`try`/`finally`/`_release_reservation` skeleton is byte-identical (git diff shows
  only additive lines).
- `OrderOperationType.EXPIRE_ORDER` added to `core/enums/order.py` (matched the file's TAB indentation).
- Three Wave-0 unit test files (9 tests) including the D-09 LANDMINE idempotency test proving an
  already-EXPIRED returning fill is a no-op (no transition error, no double-release).

**Task 2 — runner sweep + final drain + non-cascade test + never_fill docstring** (`44afb2b`):
- `BacktestRunner._run_backtest`: after the `for time_event in ...:` loop exits, invokes
  `engine.order_handler.expire_all_resting()` then ONE final `engine.event_handler.process_events()`
  drain (the symmetric shutdown bookend, D-08).
- `tests/integration/test_expire_non_cascade.py`: builds a real engine with one order resting at run
  end, runs the exact sweep+drain bookend under a queue spy, and asserts the traffic contains an
  `OrderEvent(EXPIRE)` + a `FillEvent(EXPIRED)` but NO `SignalEvent` and NO `OrderEvent(NEW)` —
  the structural non-cascade proof (T-06-06).
- `tests/e2e/matching/never_fill/scenario.py` docstring + VERIFY block flipped from
  "PENDING / no run-end expiry / GAP #1" to "EXPIRED at run end" (the D-05 positive proof). No golden
  `--freeze` here (deferred to owner-gated Plan 06-04).

## Deviations from Plan

None of the Rule 1-4 deviations were needed. The implementation followed the plan's four-seam spec
exactly (sweep, exchange arm, reconcile arm, runner bookend).

**One scope note (not a deviation):** the plan named the `never_fill` e2e leaf as the example whose
docstring flips PENDING->EXPIRED. The result-changing EXPIRE wiring naturally also flips the held
SL/TP children on TWO more e2e leaves that have bracket children resting at run end — see Golden
Drift below. This is the same correct D-05 behavior, not a regression.

## Golden Drift (owner-gated re-baseline -> Plan 06-04)

Three e2e leaves now drift in the `orders.csv` `status` column ONLY (PENDING -> EXPIRED on orders
that rest at run end). This is the predicted result-change of LIFE-01 ("nothing lingers PENDING") and
the golden re-freeze is owned by the owner-gated Plan 06-04 (NOT --frozen in this plan):

| Leaf | Drift | Unchanged |
|------|-------|-----------|
| `tests/e2e/matching/never_fill` | the single BUY LIMIT row PENDING -> EXPIRED | trades.csv empty, prices, qty, filled_qty |
| `tests/e2e/sltp/from_decision_held` | SL + TP children PENDING -> EXPIRED | ENTRY still FILLED, all prices/qty, trades.csv |
| `tests/e2e/sltp/from_fill_held` | SL + TP children PENDING -> EXPIRED | ENTRY still FILLED, all prices/qty, trades.csv |

In all three the entry/fills/trades/cash are unchanged — only the run-end disposition of orders that
were left resting flips from PENDING to the new terminal EXPIRED. The byte-exact SMA_MACD integration
oracle (134 trades / `final_equity 46189.87730727451`) is UNAFFECTED (its orders all reach terminal
states during the run; the sweep produces no trades).

## Verification

- `pytest tests/unit/order tests/unit/execution` — 325 passed (no regression in cancel/reconcile branch coverage)
- `pytest tests/unit` — 920 passed (full unit suite; the global OrderOperationType enum change is inert)
- `pytest tests/integration` — 16 passed, **SMA_MACD oracle byte-exact (134 / 46189.87730727451)**
- `pytest tests/integration/test_expire_non_cascade.py` — passed (D-08 non-cascade proof)
- `pytest tests/e2e -m e2e` — 56 passed, 3 expected golden-status drifts (the owner-gated 06-04 re-baseline set above)
- `mypy --strict itrader` — clean (160 source files)

## Acceptance Criteria

- `grep -c expire_all_resting` >= 1 in lifecycle_manager.py (1), order_manager.py (2), order_handler.py (2) ✓
- `grep -c '_apply_expired' reconcile_manager.py` == 2 (def + dispatch) ✓
- `grep -c 'OrderCommand.EXPIRE' simulated.py` == 1 ✓
- reconcile idempotency test proves already-EXPIRED is a no-op (explicit assertion) ✓
- reconcile try/finally/should_release/_release_reservation skeleton byte-identical (additive 3-edit arm only) ✓
- `backtest_runner.py` calls `expire_all_resting()` then `process_events()` AFTER the for-loop ✓
- non-cascade integration test asserts no SignalEvent / no OrderEvent(NEW) post-drain ✓
- `grep -c 'no run-end expiry' never_fill/scenario.py` == 0 ✓
- no golden/orders.csv modified in this plan (Plan 06-04 owns the --freeze) ✓
- `mypy --strict` clean ✓

## Known Stubs

None. All four EXPIRE arms are fully wired and exercised end-to-end (unit + integration).

## Self-Check: PASSED

All created files exist (4 test files + this SUMMARY); all three task commits
(`2430889` test/RED, `202aef6` feat/GREEN Task 1, `44afb2b` feat Task 2) are present in git log.
