---
phase: 06-order-manager-decomposition
plan: 03
subsystem: order_handler
tags: [refactor, admission, code-motion, byte-exact, D-10-step-3]
requires:
  - "BracketBook + BracketManager (the bracket-assembly seam) from plan 06-02 at brackets/"
  - "stateless brackets/levels.py (06-02) — admission's bracket children flow through BracketManager, which imports levels.py"
provides:
  - "AdmissionManager collaborator (signal→order pipeline: 2 entry points + 7 gates/sizing/build helpers, D-07/D-08/D-09/D-13) at admission/admission_manager.py — TAB, no queue"
  - "OrderManager.process_signal / create_orders_from_signal are 1-line delegations into AdmissionManager (D-07); public surface + external ctor unchanged"
  - "OrderManager constructs AdmissionManager once at __init__ with the injected coordinator-owned BracketBook + BracketManager (D-04 star, D-08 no sibling reconcile/lifecycle ref)"
affects:
  - "plan 06-04+ (reconcile/lifecycle extraction): admission is OUT of order_manager.py; on_fill + modify/cancel remain to extract; admission holds the canonical commission_estimator now"
tech-stack:
  added: []
  patterns:
    - "manager-class collaborator skeleton: injected-deps __init__, bound logger, NO queue access (mirrors portfolio cash_manager shape)"
    - "coordinator-owned shared-state star: OrderManager injects the BracketBook + BracketManager into AdmissionManager (the assembly seam), holding NO reconcile/lifecycle ref (D-08)"
    - "1-line public-delegation facade: OrderManager keeps the public entry points byte-equal, delegating the body into the collaborator (D-07, RESEARCH Pitfall 4)"
key-files:
  created:
    - itrader/order_handler/admission/admission_manager.py
    - itrader/order_handler/admission/__init__.py
  modified:
    - itrader/order_handler/order_manager.py
    - tests/unit/order/test_admission_rules.py
decisions:
  - "Removed move-inherent dead imports (06-02 precedent): OrderType / Side / OrderTriggerSource (core.enums), InsufficientFundsError / SizingPolicyViolation (core.exceptions), TradingDirection (core.sizing) — all used ONLY inside the 9 moved methods. OrderStatus stays (get_orders_by_status read delegator). mypy strict does not flag unused imports, but leaving an import whose sole consumer relocated is dead weight the pure-move mandates removing."
  - "test_admission_rules.py:316 white-box injection retargeted to the new owner: the test reassigns the live commission_estimator attribute to inject a fake; since _estimate_commission relocated to AdmissionManager (which caches its own self.commission_estimator at construction), the canonical post-construction home is order_manager.admission_manager.commission_estimator. Mirrors plan 05-04's 'rewrote private-internals test consumers to the new home' — a white-box-coupling adjustment, not a behavior change (the test's assertion + verdict are byte-identical)."
metrics:
  duration_min: 9
  completed: "2026-06-11"
  tasks: 2
  files: 4
---

# Phase 6 Plan 03: admission/ Extraction (D-10 step 3) Summary

D-10 step 3 extracts the **largest verb bucket** — the entire signal→order
pipeline — out of `OrderManager` into an `AdmissionManager` collaborator. The two
public entry points (`process_signal`, `create_orders_from_signal`) relocate INTACT
(D-07) and `OrderManager` keeps them as 1-line delegations, so its public surface and
external ctor stay byte-equal. Admission reaches bracket assembly through the
coordinator-owned `BracketManager` (the seam from plan 02) and holds only injected
deps + the `BracketBook` — NO sibling reconcile/lifecycle ref (D-08). Pure
code-motion (D-13), proven byte-exact by the golden oracle (134 /
46189.87730727451) and e2e 58/58.

## What Was Built

**Task 1 — AdmissionManager** (commit `c50c57d`):
- `itrader/order_handler/admission/admission_manager.py` (TAB, no queue): `class
  AdmissionManager` with an injected-dep `__init__` (D-09): `order_storage`,
  `logger`, `order_validator`, `sizing_resolver`, `portfolio_handler` (read-model),
  `commission_estimator`, the coordinator-owned `BracketBook` (`self._brackets`,
  D-05) and `BracketManager` (`self.bracket_manager`, the assembly seam, D-08). All
  9 pipeline methods moved VERBATIM (TAB): `_estimate_commission`, `process_signal`,
  `create_orders_from_signal`, `_get_signal_exchange`, `_build_primary_order`,
  `_enforce_direction_admission`, `_enforce_position_admission`,
  `_resolve_signal_quantity`, `_reject_unsized_signal`. The only in-body edits were
  the two `self.bracket_manager._assemble_bracket_and_emit(...)` calls already wired
  in plan 02 (carried as-is in the moved bodies) — every other `self.*` reference
  resolves against the injected attrs. Module docstring cites
  D-07/D-08/D-09/D-13/WR-03/WR-04/T-05-17/RESEARCH Pattern 5.
- `itrader/order_handler/admission/__init__.py`: single-symbol barrel re-exporting
  `AdmissionManager` (`__all__ = ["AdmissionManager"]`). NOT added to the
  order_handler top barrel (D-12).

**Task 2 — wire + delegate + remove** (commit `e1b5908`):
- `order_manager.py`: in `__init__`, after `self._brackets = BracketBook()` and
  `self.bracket_manager = BracketManager(...)`, constructed
  `self.admission_manager = AdmissionManager(order_storage, logger,
  self.order_validator, self.sizing_resolver, portfolio_handler,
  commission_estimator, self._brackets, self.bracket_manager)` (D-09 order). Added
  `from .admission import AdmissionManager`.
- Replaced the two public entry points with 1-line delegations (D-07):
  `process_signal` / `create_orders_from_signal` →
  `return self.admission_manager.<same>(signal_event)`. Public signatures + return
  types byte-equal so `OrderHandler` (`:101`/`:210`) and `test_order_manager.py`
  keep delegating identically (Pitfall 4).
- Removed the 9 moved pipeline methods from `order_manager.py`. `on_fill`,
  `modify_order`, `cancel_order` and the 7 read delegators stay (extracted in later
  plans). External `OrderManager` ctor signature UNCHANGED (5 args);
  `order_handler.py` and `order_handler/__init__.py` byte-unchanged.
- Removed move-inherent dead imports (06-02 precedent): `OrderType`, `Side`,
  `OrderTriggerSource`, `InsufficientFundsError`, `SizingPolicyViolation`,
  `TradingDirection` — all consumed ONLY inside the moved methods.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_admission_rules white-box injection broke on the move**
- **Found during:** Task 2 verification (`pytest tests/unit/order/`).
- **Issue:** `test_increase_with_insufficient_funds_yields_cash_reservation_rejection`
  (`test_admission_rules.py:316`) injects a fake `commission_estimator` by
  reassigning the LIVE attribute on `order_manager`. Since `_estimate_commission`
  relocated to `AdmissionManager` — which caches its own
  `self.commission_estimator` at construction — mutating
  `order_manager.commission_estimator` no longer reached the reservation math: the
  inflated commission was ignored, the increase got funded, an OrderEvent was
  emitted, and `assert harness.queue.empty()` failed.
- **Fix:** retargeted the white-box injection to the canonical new owner —
  `order_manager.admission_manager.commission_estimator`. The test's assertion and
  expected verdict (`CASH_RESERVATION` rejection) are byte-identical — this is a
  white-box-coupling relocation, not a behavior change (mirrors plan 05-04's
  "rewrote private-internals test consumers to the new home").
- **Files modified:** `tests/unit/order/test_admission_rules.py`
- **Commit:** `e1b5908`

### Move-Inherent Dead-Import Removals (not deviations — mandated by the move)

The plan's action body mandates removing imports whose sole consumer relocated
(mirroring the plan 06-02 precedent). Removed from `order_manager.py`: `OrderType`,
`Side`, `OrderTriggerSource`, `InsufficientFundsError`, `SizingPolicyViolation`,
`TradingDirection` (all used ONLY inside the 9 moved methods). `OrderStatus` stays
(used by `get_orders_by_status`). `mypy --strict` does not flag unused imports (no
linter gate), so this is hygiene the pure-move intent requires, not a gate fix.

## Verification Results

- Golden master byte-exact: `pytest tests/integration/test_backtest_oracle.py` — 3
  passed (134 trades / `final_equity 46189.87730727451`).
- `pytest tests/e2e -m e2e` — 58 passed (no leaf re-baselined); combined
  integration+e2e run 61 passed.
- `pytest tests/unit/order/` — 152 passed (incl. the untouched `test_order_manager.py`,
  `test_sltp_policy.py`, `test_bracket_book.py`; `test_admission_rules.py` green
  after the white-box retarget).
- `mypy itrader` — Success (168 files — admission_manager.py the new module).
- Indentation: `admission_manager.py` + `order_manager.py` TAB-only
  (`grep -cP "^    [^ ]"` = 0); `admission_manager.py` has NO `global_queue`
  reference; defines all 9 moved methods.
- `order_manager.py`: 9 moved helpers gone (`grep -c def ...` = 0); 2 delegations
  present (`grep -c self.admission_manager.(process_signal|create_orders_from_signal)`
  = 2).
- `order_handler.py` + `order_handler/__init__.py` byte-unchanged (`git diff --quiet`);
  OrderManager external ctor signature unchanged (5 args).

## Known Stubs

None — no placeholder values, empty returns, or unwired data sources introduced.

## Authentication Gates

None occurred — pure internal code-motion, no external surface.

## Threat Flags

None — per the plan threat model (T-06-05/06/SC), this change crosses no trust
boundary and introduces no new external surface. The primary financial-integrity
risk (T-06-05 — a verbatim-move slip silently changing admission/sizing decisions)
is mitigated by the TAB-only verbatim move + byte-exact golden gate
(134 / 46189.87730727451) + e2e 58/58 (incl. admission scenarios) + the intact unit
suite, all green. The D-08 sibling-edge risk (T-06-06) is accepted: admission
receives the coordinator-owned BracketManager as an injected dep (star topology),
holding NO reconcile/lifecycle ref. No package installs this phase.

## Self-Check: PASSED

All created files exist on disk; both per-task commits (c50c57d, e1b5908) present in
git log.
