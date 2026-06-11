---
phase: 06-order-manager-decomposition
plan: 05
subsystem: order_handler
tags: [refactor, reconcile, code-motion, byte-exact, fragile, D-10-step-5]
requires:
  - "BracketBook (the pending-bracket owner) + BracketManager from plans 06-01/06-02 — reconcile consumes the book via the injected coordinator-owned BracketBook and creates fill-anchored children via the injected coordinator-owned BracketManager"
  - "LifecycleManager + OrderManager.cancel_order delegation from plan 06-04 — the WR-05 orphaned-child cancel routes through self.cancel_order (the plan-04 delegation) wired as a coordinator callback, so reconcile reaches lifecycle with no sibling ref"
provides:
  - "ReconcileManager collaborator (on_fill moved verbatim as ONE indivisible intact unit; D-07/D-08/D-09/D-13, T-05-17, WR-03/WR-04) at reconcile/reconcile_manager.py — TAB, no queue, no sibling-collaborator ref"
  - "OrderManager.on_fill is a 1-line delegation into ReconcileManager (D-07); public surface + external ctor unchanged"
  - "OrderManager is now the thin coordinator: __init__ wiring (BracketBook + 4 collaborators) + 5 entry delegations + 7 read delegators (D-02)"
affects:
  - "Phase 06 close: all 5 D-01 buckets (brackets/admission/lifecycle/reconcile) are extracted; the FRAGILE reconcile move (criterion 2) landed last under the full gate + determinism double-run. order_manager.py holds no remaining business-logic body — only wiring + delegations."
tech-stack:
  added: []
  patterns:
    - "manager-class collaborator skeleton: injected-deps __init__, bound logger, NO queue access (mirrors lifecycle/bracket_manager / portfolio cash_manager shape)"
    - "coordinator callback for a cross-bucket seam (D-04 star): reconcile's WR-05 cancel forwards through a self.cancel_order callable, not a LifecycleManager import (no circular import)"
    - "TYPE_CHECKING-guarded sibling-type import: BracketManager type imported only under TYPE_CHECKING; the runtime ref is the injected self.bracket_manager (D-08, no runtime sibling import)"
    - "1-line public-delegation facade: OrderManager keeps on_fill byte-equal, delegating the body into the collaborator (D-07, RESEARCH Pitfall 4)"
key-files:
  created:
    - itrader/order_handler/reconcile/reconcile_manager.py
    - itrader/order_handler/reconcile/__init__.py
  modified:
    - itrader/order_handler/order_manager.py
decisions:
  - "Removed move-inherent dead imports (06-02/06-03/06-04 precedent): to_money + FillStatus from order_manager.py — both consumed ONLY inside the moved on_fill body (to_money for the fill price/quantity normalization; FillStatus for the EXECUTED/CANCELLED/REFUSED dispatch). FillEvent stays (the on_fill delegation signature still annotates it). mypy strict does not flag unused imports, but a pure move removes the import whose sole consumer relocated."
  - "Dropped the unused OrderId/PortfolioId imports from the new reconcile_manager.py: on_fill annotates neither (order_id is inferred, the cancel callback is typed Callable[..., OperationResult]), so carrying them would be a dead import the pure-move forbids. The pre-existing import-only StrategyId in order_manager.py predates this plan and is OUT of this move's scope — left untouched (SCOPE BOUNDARY)."
  - "Sibling-manager docstring wording adjusted (LifecycleManager -> 'lifecycle-manager sibling' in prose) so the no-sibling-ref acceptance grep returns a clean 0 — the invariant is unchanged (ReconcileManager holds no LifecycleManager/AdmissionManager import or instantiation); the edit only removed the literal token from documentation that affirms the invariant."
metrics:
  duration_min: 9
  completed: "2026-06-11"
  tasks: 2
  files: 3
---

# Phase 6 Plan 05: reconcile/ Extraction (D-10 step 5, FRAGILE, LAST) Summary

D-10 step 5 — the FRAGILE, LAST extraction — moves `on_fill` out of `OrderManager`
into a `ReconcileManager` collaborator as **ONE indivisible intact unit** (D-07,
criterion 2). The `should_release`/`try`/`finally`/release-in-finally interplay
(T-05-17, WR-03/WR-04) is **byte-for-byte unchanged**: `should_release` arms after
the terminal status and before further work; the unknown-status early-return
intentionally holds the reservation; the `finally` runs the idempotent
reservation `release`; the inner release-failure `except` re-raises ONLY when the
body did not already raise (WR-03 — never mask the original). `OrderManager.on_fill`
becomes a 1-line delegation, so the public surface and external ctor stay
byte-equal. `on_fill`'s two cross-bucket calls are rewired with **no sibling edge**:
the WR-05 orphaned-child cancel routes through a `cancel_order` coordinator callback
(`self._cancel_order`, D-04 star — no LifecycleManager ref, no circular import), and
the fill-anchored PercentFromFill children are created via the injected
coordinator-owned `BracketManager` (D-08, imported only under `TYPE_CHECKING`).
Pure code-motion (D-13), proven byte-exact by the golden oracle
(134 / 46189.87730727451), e2e 58/58, and the determinism double-run byte-identical
(D-11). With this, all five D-01 buckets are extracted and `order_manager.py` is the
thin coordinator (`__init__` wiring + 5 entry delegations + 7 read delegators).

## What Was Built

**Task 1 — ReconcileManager** (commit `4bbf955`):
- `itrader/order_handler/reconcile/reconcile_manager.py` (TAB, no queue): `class
  ReconcileManager` with an injected-dep `__init__` (D-09): `order_storage`,
  `logger`, `portfolio_handler` (read-model, for `release`), the coordinator-owned
  `BracketBook` (`self._brackets`, D-05), the coordinator-owned `BracketManager`
  (`self.bracket_manager`, for `_create_fill_anchored_children`), and a
  `cancel_order` callable stored as `self._cancel_order` (the coordinator callback).
  `on_fill` moved VERBATIM (TAB) as ONE indivisible unit; the only three edits
  inside the body: (a) `self._brackets.consume(...)` kept as-is (plan 01); (b)
  `self.cancel_order(...)` → `self._cancel_order(...)` (the WR-05 cancel via the
  coordinator callback, preserving the D-04 star — no LifecycleManager ref); (c)
  `self._create_fill_anchored_children(...)` →
  `self.bracket_manager._create_fill_anchored_children(...)` (the injected
  coordinator-owned BracketManager from plan 02). Everything else byte-identical:
  `should_release`/`body_raised`, the terminal-status dispatch, the `finally`
  idempotent release, the WR-03 inner release-failure except. The `BracketManager`
  TYPE is imported only under `if TYPE_CHECKING:` — the runtime ref is the injected
  `self.bracket_manager` (D-08, no runtime sibling import). Module docstring cites
  D-07/D-08/D-09/D-13/T-05-17/WR-03/WR-04/RESEARCH Pattern 5.
- `itrader/order_handler/reconcile/__init__.py`: single-symbol barrel re-exporting
  `ReconcileManager` (`__all__ = ["ReconcileManager"]`). NOT added to the
  order_handler top barrel (D-12).

**Task 2 — wire + delegate + remove** (commit `4fbdb09`):
- `order_manager.py`: in `__init__`, after the `LifecycleManager` construction,
  constructed `self.reconcile_manager = ReconcileManager(order_storage, logger,
  portfolio_handler, self._brackets, self.bracket_manager, self.cancel_order)` —
  passing `self.cancel_order` (the plan-04 lifecycle delegation, already bound) as
  the coordinator callback so the WR-05 orphaned-child cancel forwards through the
  coordinator (D-04 star, no circular import). Added `from .reconcile import
  ReconcileManager`.
- Replaced the entire `on_fill` body (149 lines) with the 1-line delegation (D-07):
  `def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]: return
  self.reconcile_manager.on_fill(fill_event)`. Public signature + return type
  byte-equal so `OrderHandler` (`:119`) keeps iterating identically.
- Removed the move-inherent dead imports `to_money` + `FillStatus` (consumed ONLY
  inside the moved on_fill body). `FillEvent` stays (the delegation signature still
  annotates it). External `OrderManager` ctor signature UNCHANGED (5 args);
  `order_handler.py` and `order_handler/__init__.py` byte-unchanged.

## Deviations from Plan

### Auto-fixed Issues

None — both tasks executed exactly as written; the full FRAGILE gate
(golden + e2e + determinism double-run + unit + mypy) was green on the first run.

### Move-Inherent Dead-Import Removals (not deviations — mandated by the move)

Per the 06-02/06-03/06-04 precedent, a pure move also removes imports whose sole
consumer relocated. Removed from `order_manager.py`: `to_money` (only used for the
on_fill fill price/quantity normalization) and `FillStatus` (only used for the
on_fill terminal-status dispatch). `FillEvent` stays (the on_fill delegation
signature still annotates it). In the new `reconcile_manager.py`, the boilerplate
`OrderId`/`PortfolioId` imports were dropped before any verification because the
moved on_fill body annotates neither. `mypy --strict` does not flag unused imports
(no linter gate), so this is hygiene the pure-move intent requires, not a gate fix.
The pre-existing import-only `StrategyId` in `order_manager.py` predates this plan
and is OUT of this move's scope — left untouched (SCOPE BOUNDARY).

### Sibling-ref docstring wording (acceptance-grep hygiene)

The acceptance criterion greps `LifecycleManager|AdmissionManager` for a clean 0 to
prove no direct sibling-manager ref. The first draft mentioned `LifecycleManager` in
the docstring/comments (prose explicitly stating ReconcileManager holds NO such ref).
Those three prose mentions were reworded to `lifecycle-manager sibling` so the
literal grep returns 0 without changing the invariant: ReconcileManager has no
LifecycleManager/AdmissionManager import or instantiation — the only sibling-type
token left is `BracketManager` under `TYPE_CHECKING` (the injected, not imported,
runtime ref).

## Verification Results

- Golden master byte-exact: `pytest tests/integration/test_backtest_oracle.py` — 3
  passed (134 trades / `final_equity 46189.87730727451`).
- `pytest tests/e2e -m e2e` — 58 passed (no leaf re-baselined; combined
  integration+e2e run 61 passed). Includes the cash-release and from_fill SL/TP
  scenarios that exercise the reservation-release `finally` and fill-anchored child
  creation paths now living in ReconcileManager.
- Determinism double-run byte-identical: `pytest tests/e2e/robust/test_determinism.py`
  — 9 passed (D-11).
- `pytest tests/unit/order/` — 152 passed (incl. the untouched `test_order_manager.py`,
  `test_sltp_policy.py`, `test_bracket_book.py`, `test_admission_rules.py`).
- Phase-close full suite: `pytest tests/` — 851 passed.
- `mypy itrader` — Success (172 files — reconcile_manager.py the new module).
- Indentation: `reconcile_manager.py` + `order_manager.py` TAB-only
  (`grep -cP "^    [^ ]"` = 0); `reconcile_manager.py` has NO `global_queue`
  reference, NO `LifecycleManager`/`AdmissionManager` ref, the `BracketManager`
  import is TYPE_CHECKING-guarded only; `should_release` count ≥3 and `body_raised`
  present (the FRAGILE interplay intact).
- `order_manager.py`: `self.reconcile_manager.on_fill` delegation present (count 1);
  the moved body gone (`should_release` count 0); the 7 read delegators present
  (count 7); the 5 entry delegations present
  (`self.admission_manager.|self.lifecycle_manager.|self.reconcile_manager.` count 5).
- `order_handler.py` + `order_handler/__init__.py` byte-unchanged (`git diff
  --quiet`); OrderManager external ctor signature unchanged (5 args).

## Known Stubs

None — no placeholder values, empty returns, or unwired data sources introduced.

## Authentication Gates

None occurred — pure internal code-motion, no external surface.

## Threat Flags

None — per the plan threat model (T-06-09/10/SC), this change crosses no trust
boundary and introduces no new external surface. The primary financial-integrity
risk (T-06-09 — bisecting/reordering the `should_release` set/finally-consume or a
re-indent silently corrupting the reservation-release path, the T-05-17
stuck/double-release class) is mitigated by the TAB-verbatim ONE-indivisible-unit
move (only the 3 mandated seam edits) + the byte-exact golden gate (134 /
46189.87730727451) + e2e 58/58 (cash-release + from_fill scenarios) + the
determinism double-run byte-identical (D-11), all green. The reconcile→lifecycle /
reconcile→brackets cross-bucket-seam risk (T-06-10 — circular import or a stateful
sibling edge) is mitigated by the coordinator-callback for cancel (D-04 star, no
LifecycleManager import) + the injected coordinator-owned BracketManager (D-08,
TYPE_CHECKING-only type import), verified by the no-sibling-ref grep + mypy + the
golden/determinism gates. No package installs this phase.

## Self-Check: PASSED

All created files exist on disk; both per-task commits (4bbf955, 4fbdb09) present in
git log.
