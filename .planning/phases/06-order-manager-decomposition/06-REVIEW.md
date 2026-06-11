---
phase: 06-order-manager-decomposition
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/brackets/__init__.py
  - itrader/order_handler/brackets/bracket_book.py
  - itrader/order_handler/brackets/bracket_manager.py
  - itrader/order_handler/brackets/levels.py
  - itrader/order_handler/admission/__init__.py
  - itrader/order_handler/admission/admission_manager.py
  - itrader/order_handler/lifecycle/__init__.py
  - itrader/order_handler/lifecycle/lifecycle_manager.py
  - itrader/order_handler/reconcile/__init__.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - tests/unit/order/test_admission_rules.py
  - tests/unit/order/test_bracket_book.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

This phase decomposed the monolithic `OrderManager` (D-10) into five collaborator
buckets — `brackets/` (`BracketBook`, `BracketManager`, `levels`), `admission/`,
`lifecycle/`, `reconcile/` — with `OrderManager` reduced to a thin coordinator of
one-line delegations. The stated intent was a behavior-preserving VERBATIM move.

I verified that intent adversarially rather than accepting it:

- **Byte-level fidelity confirmed.** I diffed every moved method against the
  pre-phase `order_manager.py` (`38e5fce^`). `process_signal`, `on_fill`,
  `_assemble_bracket_and_emit`, `_create_fill_anchored_children`,
  `_bracket_levels`, `modify_order`, `cancel_order`, the admission gates and
  `_resolve_signal_quantity` are identical except for (a) trailing-whitespace
  lines and (b) the intended seam swaps. No logic drift.
- **Seam swaps all correct.** Every `self._pending_brackets[..] = ..` /
  `.pop(..)` / `.get(..)` raw-dict op was mapped to the matching `BracketBook`
  method (`arm`/`consume`/`get`/`refresh_quantity`) with identical semantics; the
  `self._assemble_bracket_and_emit` → `self.bracket_manager.…`,
  `self._create_fill_anchored_children` → `self.bracket_manager.…`, and
  `self.cancel_order` → `self._cancel_order` callback swaps are applied at every
  call site with no stale `self.` reference left behind.
- **Wiring is sound.** The `OrderManager.__init__` construction order
  (`BracketBook` → `BracketManager` → `AdmissionManager` → `LifecycleManager` →
  `ReconcileManager`) resolves the `self.cancel_order` callback lazily (bound
  method, invoked only at fill time), so the reconcile→lifecycle seam is not a
  construction-order hazard. No circular import: confirmed by a live import probe.
- **Gates verified.** `mypy --strict` clean on all 11 source files; `import` probe
  green; the 27 targeted tests and all 152 `tests/unit/order/` tests pass; the
  `BracketBook` dict-compat dunders keep `test_sltp_policy.py`'s `== {}` / `in`
  assertions green; indentation is TAB-consistent with the `order_handler/`
  convention (continuation-line alignment spaces are the established house style,
  not a tab/space hazard).

One genuine new defect was introduced by the move (a dead import left behind when
`_PendingBracket` relocated). The remaining items are minor quality notes.

## Warnings

### WR-01: Dead `StrategyId` import left behind by the `_PendingBracket` relocation

**File:** `itrader/order_handler/order_manager.py:20`
**Issue:** The pre-phase `order_manager.py` imported `StrategyId` solely for the
`_PendingBracket` dataclass field (`strategy_id: StrategyId`). The move relocated
`_PendingBracket` into `brackets/bracket_book.py` (which correctly re-imports
`StrategyId`), but the import on line 20 of `order_manager.py` was not cleaned up
and is now unused — the file references only `OrderId` and `PortfolioId`. This
slips past the project's static gate because `mypy --strict` does not flag unused
imports (no ruff/flake8 configured). It is a residue of the relocation, exactly the
"lost reference" class this review weights toward, and contradicts the file's own
"pure move" intent.
**Fix:**
```python
# itrader/order_handler/order_manager.py:20
from ..core.ids import OrderId, PortfolioId   # drop StrategyId (now used only in bracket_book.py)
```

## Info

### IN-01: `BracketManager` import is effectively eager despite the `TYPE_CHECKING` guard

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:41,47-48`
**Issue:** `ReconcileManager` guards `from ..brackets import BracketManager` under
`TYPE_CHECKING` (to advertise "no sibling import / no circular import"), but line 41
imports `BracketBook` from `..brackets` at runtime, which triggers
`brackets/__init__.py` to import `BracketManager` anyway. The guard therefore does
not actually avoid loading `BracketManager` at runtime. This is harmless (the
`brackets` package does not import `reconcile`, so there is no cycle, and the import
probe is green), but the comment's claim that the type is "imported only under
`TYPE_CHECKING`" is slightly misleading about the runtime import graph.
**Fix:** No functional change needed. Optionally soften the module docstring to note
that the runtime `BracketBook` import already pulls in the `brackets` package, and
the `TYPE_CHECKING` guard exists only to keep the annotation off the module's
runtime name bindings.

### IN-02: `_ONE = Decimal("1")` duplicated across `levels.py` and `sizing_resolver.py`

**File:** `itrader/order_handler/brackets/levels.py:23`
**Issue:** The module-private `_ONE = Decimal("1")` constant now exists in both
`brackets/levels.py` and `order_handler/sizing_resolver.py`. This is a deliberate
"travels with its sole consumer" choice per the `levels.py` docstring and matches
the pre-phase state (the constant moved with `_bracket_levels`), so it is not a
move regression. Noted only as a low-priority duplication that a future consolidation
into `core/money.py` could remove. No action required this phase.

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
