---
phase: 04-m3-event-dispatch-core
plan: 02
subsystem: order-pipeline
tags: [events, orders, validation, de-mutation, brackets, behavior-preserving]
requires:
  - "04-01 (EventType in core/enums, TimeEvent family)"
provides:
  - "SignalEvent without verified; quantity: float | None = None (None = 'order/risk layer sizes me', D-10)"
  - "Mutation-free signal→order pipeline: zero SignalEvent writer sites anywhere (D-03/D-13)"
  - "Entity-based validation: EnhancedOrderValidator.validate_order_pipeline(Order) -> ValidationResult"
  - "Audited rejections: validation failure persists a REJECTED order (PENDING→REJECTED, triggered_by=validator, event-derived timestamp)"
  - "Create-all-then-emit brackets with two-directional linkage: parent.child_order_ids populated, OrderEvent.child_order_ids tuple"
affects: [04-04, 04-05, 04-06]
tech-stack:
  added: []
  patterns:
    - "entity-as-pipeline-state (D-13): sizing → PENDING entity → validate entity → reject via audited add_state_change OR assemble/store/emit"
    - "create-all-then-emit (D-11): all bracket entities built and linked before any store/emit; queue order unchanged"
    - "float-domain validator comparisons until M4: float(order.price)/float(order.quantity) coerced at the read boundary so verdicts are byte-identical to the pre-entity pipeline"
key-files:
  created: []
  modified:
    - itrader/events_handler/event.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_validator.py
    - itrader/order_handler/order.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/risk_manager/advanced_risk_manager.py
    - itrader/strategy_handler/position_sizer/variable_sizer.py
    - tests/unit/events/test_event_immutability.py
    - tests/unit/events/test_events.py
    - tests/unit/order/test_order_validator.py
    - tests/unit/order/test_on_signal.py
    - tests/unit/order/test_order_storage.py
    - tests/unit/order/test_order.py
key-decisions:
  - "Validator stays float-domain until M4: entity Decimals are float()-coerced inside the pipeline so every comparison reproduces the pre-D-13 float math exactly (also avoids Decimal/float TypeError against Portfolio.total_equity which returns float)"
  - "Legacy string order-type check dropped from the validator: the entity carries OrderType by construction; unsupported types short-circuit in _build_primary_order BEFORE entity creation"
  - "Dead signal-based compat wrappers (validate_signal/validate_signal_basic/validate_signal_complete) deleted — zero callers (D-18 mechanical-delete precedent)"
  - "Resolved sized quantity flows Decimal-native (full precision) onto the entity; the OrderEvent float() boundary produces the identical float as the old float-roundtrip path, keeping the oracle byte-exact"
metrics:
  duration: "~22 min"
  completed: "2026-06-05"
  tasks: 3
  files: 13
---

# Phase 4 Plan 02: Signal De-Mutation & Order-Entity Pipeline Summary

SignalEvent is now a pure immutable-in-practice strategy fact (verified deleted, quantity float|None, zero writer sites repo-wide); the Order entity is the pipeline state — validator verdicts apply to the PENDING entity, rejections persist as audited PENDING→REJECTED state changes, and brackets are created-all-then-emitted with populated two-directional linkage — suite + both oracle layers byte-exact at every commit.

## Tasks Completed

| Task | Name | Commit(s) | Key Files |
| ---- | ---- | --------- | --------- |
| 1 | Drop SignalEvent.verified + quantity-0 sentinel | d56c78f | event.py, order_validator.py, strategy_handler/{base,risk_manager,position_sizer}, event tests |
| 2 | Order entity as pipeline state + create-all-then-emit brackets | 608acf8 | order_manager.py, order_validator.py, order.py, event.py, test_order_validator.py |
| 3 | Rejection-audit + bracket-linkage tests | 907f2cc | test_on_signal.py, test_order_storage.py, test_order.py |

## What Was Built

- **SignalEvent (event.py, TABS):** `verified` deleted; `quantity: float | None = None` moved to the defaulted tail of the field list (None = "order/risk layer sizes me"; the 0 sentinel is gone). `strategy_handler/base.py` omits the quantity argument.
- **Sizing (order_manager.py):** `_resolve_signal_quantity` returns `Decimal | OperationResult` — the in-place `signal_event.quantity = float(...)` writes are gone; arithmetic byte-identical (`net_quantity` exit branch, `(0.95 * cash) / to_money(price)` entry branch); invalid-price failure still short-circuits BEFORE any entity exists.
- **Entity-as-state (D-13):** `process_signal` builds the primary PENDING `Order` via `_build_primary_order` (Order.new_order gained an explicit `quantity: Decimal` param), then `EnhancedOrderValidator.validate_order_pipeline(order)` checks the ENTITY. Rejection → `add_state_change(OrderStatus.REJECTED, summary, triggered_by="validator")` (timestamp defaults to the order's event-derived time, M2-09) → stored. Failure-result shape identical to the old signal-validation failure.
- **Create-all-then-emit (D-11):** `_assemble_bracket_and_emit` builds SL/TP entities first, sets `child.parent_order_id = primary.id`, populates `primary.child_order_ids` (declared at order.py:74 since M2, populated for the first time), stores all, THEN emits OrderEvents parent-first (primary, stop-loss, take-profit) — identical queue arrival sequence. `create_orders_from_signal` remains the unvalidated direct entry point with the same shape.
- **OrderEvent:** `child_order_ids: tuple[OrderId, ...] = ()` added; `new_order_event` reads `tuple(order.child_order_ids)`; every existing `float()` boundary coercion preserved exactly (D-04).
- **Validator (order_validator.py, SPACES):** entity-typed throughout; float-domain comparisons at the read boundary (`float(order.price)`, `float(order.quantity)`) so verdicts are byte-identical to the pre-entity pipeline; SignalEvent import gone.
- **strategy_handler RiskManager/DynamicSizer:** verified reads/writes removed; `refine_orders`/`check_cash` return typed bool verdicts, `size_order` returns the computed quantity — no SignalEvent mutation anywhere.

## Verification Results

- `grep -rn "\.verified" itrader/ tests/` → 0; `grep "verified" event.py` → 0; `grep "signal_event.quantity =\|signal.quantity ="` in itrader/ → 0
- `SignalEvent` declares `quantity: float | None = None`; `OrderEvent` declares `child_order_ids: tuple[OrderId, ...] = ()`
- Full suite green at every commit: 349 passed (d56c78f), 349 passed (608acf8), 353 passed (907f2cc — 4 new tests)
- `tests/integration/test_backtest_oracle.py` passed UNMODIFIED at every commit — `git diff` over `tests/integration/` is empty (M3-04, D-22)
- `poetry run mypy itrader` (the `make typecheck` command): Success, 127 source files at every commit
- New tests lock: rejected signal → exactly one stored REJECTED order with audited PENDING→REJECTED (`triggered_by="validator"`, timestamp == signal time), nothing emitted; bracket signal → two-directional linkage on events AND stored entities, parent-first emission; REJECTED orders never enter the active book

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Risk-manager/position-sizer paths differ from the plan**
- **Found during:** Task 1
- **Issue:** plan lists `itrader/order_handler/risk_manager/advanced_risk_manager.py` and `itrader/order_handler/position_sizer/variable_sizer.py`; the files live under `itrader/strategy_handler/`
- **Fix:** edited the real paths; same changes as planned
- **Commit:** d56c78f

**2. [Rule 3 - Blocking] `verified` references in two test files outside the plan's file list**
- **Found during:** Task 1 (the zero-references grep gate)
- **Issue:** `tests/unit/order/test_order_validator.py` (2 asserts) and `tests/unit/events/test_events.py` (1 assert) reference `signal.verified`
- **Fix:** assertions deleted; constructions left keyword-form
- **Commit:** d56c78f

**3. [Rule 3 - Blocking] mypy strict broke on `float | None` flowing into the validator and Order.new_order**
- **Found during:** Task 1 typecheck gate
- **Issue:** quantity comparisons/arithmetic against `None` at 6 validator sites + `to_money(signal.quantity)` in `Order.new_order`
- **Fix:** None-coalescing guards in the (still signal-based) validator phases; explicit `ValueError` for unsized signals in `new_order`. Both superseded by the Task 2 entity-based rewrite (entity quantity is always Decimal)
- **Commit:** d56c78f

**4. [Rule 3 - Blocking] test_order_validator.py rewritten for entity-based validation**
- **Found during:** Task 2
- **Issue:** the validator's entry point now takes the Order entity; the test module constructed SignalEvents and called `validate_signal_pipeline`
- **Fix:** rewritten against `create_test_order()` + `validate_order_pipeline`; same 14 test cases, same verdict assertions, plus an explicit no-mutation assertion (entity stays PENDING through validation)
- **Commit:** 608acf8

### Minor in-scope extensions

- `DynamicSizer.size_order` no longer writes `signal.quantity` (returns the size instead) — required by the must-have "no code anywhere mutates a SignalEvent"; the method is dead on the backtest path (sizing lives in OrderManager per D-09) with zero callers.
- Validator's float-coercion decision documented inline ("float-domain until M4") at every comparison site.

### Notes on planned-but-unneeded changes

- **Storage-count test adjustments (Pitfall 7):** none required. `InMemoryOrderStorage.add_order` only enters the active book for `is_active` orders, so persisted REJECTED orders never perturb `get_pending_orders`/`get_active_orders` counts — all existing assertions passed unchanged. A new test locks this semantics deliberately instead.

## Known Stubs

None — no placeholder values or unwired data introduced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-03 mitigated (rejections are audited add_state_change entries persisted to storage); T-04-04 mitigated (verified flag deleted; verdicts are typed ValidationResult + entity state); T-04-05 mitigated (identical arithmetic and float-domain validation inputs; oracle byte-exact at every commit).

## TDD Gate Compliance

Not applicable — plan type is `execute` (behavior-preserving refactor), not `tdd`.

## Self-Check: PASSED

- Modified files exist on disk (no files created or deleted this plan)
- Commits exist: d56c78f, 608acf8, 907f2cc
- No file deletions in any commit (`git diff --diff-filter=D` empty for all three)
- Oracle assertions untouched: `git diff 939e72b..HEAD -- tests/integration/` empty
