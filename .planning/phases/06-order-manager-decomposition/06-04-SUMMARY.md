---
phase: 06-order-manager-decomposition
plan: 04
subsystem: order_handler
tags: [refactor, lifecycle, code-motion, byte-exact, D-10-step-4]
requires:
  - "BracketBook (the pending-bracket owner) from plan 06-01 at brackets/bracket_book.py — lifecycle's get/refresh_quantity/consume route through it"
  - "BracketManager + admission/ extractions (06-02/06-03) — lifecycle is the LAST extraction before the FRAGILE reconcile step, landing on top of the already-slimmed coordinator"
provides:
  - "LifecycleManager collaborator (modify/cancel verbs, D-07/D-08/D-09/D-13) at lifecycle/lifecycle_manager.py — TAB, no queue, no sibling-collaborator ref"
  - "OrderManager.modify_order / cancel_order are 1-line delegations into LifecycleManager (D-07); public surface + external ctor unchanged"
  - "OrderManager constructs LifecycleManager once at __init__ with the injected coordinator-owned BracketBook (D-04 star, D-08 — no reconcile/admission ref)"
affects:
  - "plan 06-05 (reconcile extraction, the FRAGILE step): cancel_order now lives in its own collaborator and stays reachable via the OrderManager delegation, so when on_fill moves to ReconcileManager the cancel call becomes a coordinator callback (D-04 star) with no circular import — the only non-delegation business logic left in order_manager.py is on_fill + __init__ wiring + the 7 read delegators (D-02)"
tech-stack:
  added: []
  patterns:
    - "manager-class collaborator skeleton: injected-deps __init__, bound logger, NO queue access (mirrors admission_manager / portfolio cash_manager shape)"
    - "coordinator-owned shared-state star: OrderManager injects the BracketBook into LifecycleManager, which holds NO reconcile/admission ref (D-08)"
    - "1-line public-delegation facade: OrderManager keeps modify_order/cancel_order byte-equal, delegating the body into the collaborator (D-07, RESEARCH Pitfall 4)"
key-files:
  created:
    - itrader/order_handler/lifecycle/lifecycle_manager.py
    - itrader/order_handler/lifecycle/__init__.py
  modified:
    - itrader/order_handler/order_manager.py
decisions:
  - "Removed move-inherent dead imports (06-02/06-03 precedent): OrderCommand + OrderOperationType (core.enums) — both consumed ONLY inside the two moved methods (OrderCommand.MODIFY/CANCEL + OrderOperationType.MODIFY_ORDER/CANCEL_ORDER). OrderStatus stays (get_orders_by_status read delegator). mypy strict does not flag unused imports, but leaving an import whose sole consumer relocated is dead weight the pure-move mandates removing."
  - "Dropped the unused `Order` import from lifecycle_manager.py: neither modify_order nor cancel_order annotates Order (both return OperationResult), so it was never referenced in the moved bodies — carrying it would be a dead import the pure-move forbids. (Pre-existing import-only StrategyId in order_manager.py left untouched — it predates this plan and is OUT of this move's scope.)"
metrics:
  duration_min: 6
  completed: "2026-06-11"
  tasks: 2
  files: 3
---

# Phase 6 Plan 04: lifecycle/ Extraction (D-10 step 4) Summary

D-10 step 4 extracts the **4th D-01 bucket** — the modify/cancel verbs — out of
`OrderManager` into a `LifecycleManager` collaborator. Both public entry points
(`modify_order`, `cancel_order`) relocate INTACT (D-07) and `OrderManager` keeps
them as 1-line delegations, so its public surface and external ctor stay
byte-equal. Lifecycle reaches the pending-bracket map through the coordinator-owned
`BracketBook` (the single owner from plan 01) and holds only injected deps — NO
sibling reconcile/admission ref (D-08). This is the LAST extraction before the
FRAGILE reconcile step: with `cancel_order` now in its own collaborator (still
reachable via the OrderManager delegation), plan 05 can move `on_fill` to
ReconcileManager and wire the reconcile→lifecycle seam through the coordinator
(D-04 star) without a circular import. Pure code-motion (D-13), proven byte-exact
by the golden oracle (134 / 46189.87730727451) and e2e 58/58.

## What Was Built

**Task 1 — LifecycleManager** (commit `0d72697`):
- `itrader/order_handler/lifecycle/lifecycle_manager.py` (TAB, no queue): `class
  LifecycleManager` with an injected-dep `__init__` (D-09): `order_storage`,
  `logger`, `order_validator`, `portfolio_handler` (read-model, for `release`) and
  the coordinator-owned `BracketBook` (`self._brackets`, D-05). Both verbs moved
  VERBATIM (TAB): `modify_order` (uses `self._brackets.get`/`refresh_quantity` via
  the WR-03-part-3 quantity refresh) and `cancel_order` (uses
  `self._brackets.consume` + the WR-04 idempotent `self.portfolio_handler.release`).
  Every other `self.*` reference resolves against the injected attrs. Module
  docstring cites D-01/D-07/D-08/D-09/D-13/T-05-17/RESEARCH Pattern 5.
- `itrader/order_handler/lifecycle/__init__.py`: single-symbol barrel re-exporting
  `LifecycleManager` (`__all__ = ["LifecycleManager"]`). NOT added to the
  order_handler top barrel (D-12).

**Task 2 — wire + delegate + remove** (commit `d2a496f`):
- `order_manager.py`: in `__init__`, after the `AdmissionManager` construction,
  constructed `self.lifecycle_manager = LifecycleManager(order_storage, logger,
  self.order_validator, portfolio_handler, self._brackets)` (D-09 order). Added
  `from .lifecycle import LifecycleManager`.
- Replaced the two verbs with 1-line delegations (D-07): `modify_order` →
  `self.lifecycle_manager.modify_order(order_id, new_price, new_quantity,
  portfolio_id, reason)`; `cancel_order` →
  `self.lifecycle_manager.cancel_order(order_id, portfolio_id, reason)`. Public
  signatures + return types byte-equal so `OrderHandler` (`:150`/`:182`),
  `test_order_manager.py`, and `on_fill`'s `:227`-class orphaned-child cancel keep
  delegating identically (Pitfall 4).
- Left `on_fill`'s `self.cancel_order(...)` call UNCHANGED — it now routes through
  the delegation, which forwards to LifecycleManager. (When `on_fill` extracts in
  plan 05, that call becomes a coordinator callback into the OrderManager
  delegation — handled there, not here, preserving the D-04 star with no circular
  import.)
- Removed the two moved bodies and the move-inherent dead imports `OrderCommand` +
  `OrderOperationType` (consumed ONLY inside the moved methods). External
  `OrderManager` ctor signature UNCHANGED (5 args); `order_handler.py` and
  `order_handler/__init__.py` byte-unchanged.

## Deviations from Plan

### Auto-fixed Issues

None — both tasks executed exactly as written; full gate green on the first run.

### Move-Inherent Dead-Import Removals (not deviations — mandated by the move)

The plan's action body mandates the verbatim move and STRICTLY ZERO unrelated
cleanup; per the 06-02/06-03 precedent a pure move also removes imports whose sole
consumer relocated. Removed from `order_manager.py`: `OrderCommand` (was used only
for `OrderCommand.MODIFY`/`CANCEL` inside the two moved methods) and
`OrderOperationType` (only `OrderOperationType.MODIFY_ORDER`/`CANCEL_ORDER` in the
moved bodies). `OrderStatus` stays (used by `get_orders_by_status`). In
`lifecycle_manager.py`, the boilerplate `Order` import was dropped before any
verification because neither moved method references `Order` (both return
`OperationResult`). `mypy --strict` does not flag unused imports (no linter gate),
so this is hygiene the pure-move intent requires, not a gate fix. The pre-existing
import-only `StrategyId` in `order_manager.py` predates this plan and is OUT of this
move's scope — left untouched (SCOPE BOUNDARY).

## Verification Results

- Golden master byte-exact: `pytest tests/integration/test_backtest_oracle.py` — 3
  passed (134 trades / `final_equity 46189.87730727451`).
- `pytest tests/e2e -m e2e` — 58 passed (no leaf re-baselined); combined
  integration+e2e run 61 passed.
- `pytest tests/unit/order/` — 152 passed (incl. the untouched `test_order_manager.py`,
  `test_sltp_policy.py`, `test_bracket_book.py`, `test_admission_rules.py`).
- `mypy itrader` — Success (170 files — lifecycle_manager.py the new module).
- Indentation: `lifecycle_manager.py` + `order_manager.py` TAB-only
  (`grep -cP "^    [^ ]"` = 0); `lifecycle_manager.py` has NO `global_queue`
  reference; defines both moved methods (`grep -c "def modify_order\|def
  cancel_order"` = 2).
- `order_manager.py`: 2 delegations present
  (`grep -c "self.lifecycle_manager.(modify_order|cancel_order)"` = 2); the moved
  bodies are gone (each def is now a single `return self.lifecycle_manager....`
  line); `on_fill` still calls `self.cancel_order(...)` at its WR-05 orphaned-child
  path (`grep -c "self.cancel_order"` = 1).
- `order_handler.py` + `order_handler/__init__.py` byte-unchanged (`git diff
  --quiet`); OrderManager external ctor signature unchanged (5 args).

## Known Stubs

None — no placeholder values, empty returns, or unwired data sources introduced.

## Authentication Gates

None occurred — pure internal code-motion, no external surface.

## Threat Flags

None — per the plan threat model (T-06-07/08/SC), this change crosses no trust
boundary and introduces no new external surface. The primary financial-integrity
risk (T-06-07 — a verbatim-move slip changing cancel/modify behavior or the
reservation `release`, the T-05-17 stuck/double-release class) is mitigated by the
TAB-only verbatim move + byte-exact golden gate (134 / 46189.87730727451) + e2e
58/58 (cash-release scenarios) + the intact unit suite, all green. The
reconcile→lifecycle pre-positioning (T-06-08) is accepted: `cancel_order` stays
reachable via the OrderManager delegation, so `on_fill`'s cancel call is
byte-unchanged this step; the cross-bucket coordinator-callback wiring is deferred
to plan 05 (the most-scrutinized step). No package installs this phase.

## Self-Check: PASSED

All created files exist on disk; both per-task commits (0d72697, d2a496f) present in
git log.
