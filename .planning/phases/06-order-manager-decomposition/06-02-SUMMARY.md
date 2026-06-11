---
phase: 06-order-manager-decomposition
plan: 02
subsystem: order_handler
tags: [refactor, brackets, code-motion, byte-exact, D-10-step-2]
requires:
  - "BracketBook primitive (single owner of the pending-bracket map, D-05) from plan 06-01 at brackets/bracket_book.py"
  - "_PendingBracket relocated to brackets/bracket_book.py (06-01, D-03)"
provides:
  - "stateless brackets/levels.py (_bracket_levels + _ONE, D-08) imported by both the bracket-assembly path AND the fill-anchored path"
  - "BracketManager collaborator (bracket assembly + SLTP fill-anchored children, D-04/D-08/D-13) at brackets/bracket_manager.py — TAB, no queue"
  - "OrderManager constructs BracketManager once at __init__ with the injected coordinator-owned BracketBook (D-04 star); 3 call sites delegate into it"
affects:
  - "plan 06-03+ (admission extraction imports the stateless levels.py helper; reconcile extraction will import _create_fill_anchored_children via the coordinator, NOT hold a BracketManager ref — D-08)"
tech-stack:
  added: []
  patterns:
    - "stateless pure-function module (levels.py) mirroring core/money.py shape — _-prefixed module constant + pure fn, no class/state (D-08)"
    - "manager-class collaborator skeleton: injected-deps __init__, bound logger, NO queue access (mirrors portfolio cash_manager shape)"
    - "coordinator-owned shared-state star: OrderManager owns the BracketBook, injects it into BracketManager (portfolio._init_managers analog)"
key-files:
  created:
    - itrader/order_handler/brackets/levels.py
    - itrader/order_handler/brackets/bracket_manager.py
  modified:
    - itrader/order_handler/brackets/__init__.py
    - itrader/order_handler/order_manager.py
decisions:
  - "Removed now-dead imports move-inherently (mirrors plan 06-01 precedent): SLTPPolicy from order_manager (Task 1, sole consumer _bracket_levels moved out); assert_never + PercentFromDecision + PercentFromFill + _PendingBracket from order_manager (Task 2, all used only inside the two moved methods). mypy strict does not flag unused imports, but leaving an import whose sole runtime consumer relocated is dead weight the move mandates removing."
  - "StrategyId import in order_manager.py is imported-but-unused — verified PRE-EXISTING (count 1 in the pre-Task-2 commit 230facd), so it is OUT OF SCOPE (scope-boundary rule) and left untouched, not folded into this plan's deviations."
  - "Method names kept as leading-underscore (_assemble_bracket_and_emit / _create_fill_anchored_children) on BracketManager — no public-rename ride-along (D-13). The 3 call sites call self.bracket_manager._assemble_bracket_and_emit(...) / ._create_fill_anchored_children(...) directly."
metrics:
  duration_min: 6
  completed: "2026-06-11"
  tasks: 2
  files: 4
---

# Phase 6 Plan 02: brackets/ Extraction (D-10 step 2) Summary

D-10 step 2 extracts the bracket-assembly logic out of `OrderManager` into a
`BracketManager` collaborator and lifts the pure `_bracket_levels` ± pct helper
(with its `_ONE` constant) into a stateless `brackets/levels.py`. Both moves are
pure code-motion (D-13) — the bodies relocate VERBATIM (TAB), proven byte-exact by
the golden oracle (134 / 46189.87730727451) and e2e 58/58. `levels.py` is imported
by BOTH the assembly path and the fill-anchored path so neither admission nor
reconcile (extracted in later plans) needs a brackets-collaborator ref (D-08).

## What Was Built

**Task 1 — stateless brackets/levels.py** (commit `230facd`):
- `itrader/order_handler/brackets/levels.py` (TAB): `_bracket_levels` moved verbatim
  from `order_manager.py` as a module-level pure function (verified: it referenced
  no instance state beyond its args — only `policy`/`anchor`/`action`/`_ONE`/`Side`),
  plus `_ONE = Decimal("1")` moved as the module-private constant (its sole consumer).
  Module docstring cites D-08/D-13/RESEARCH Pattern 5; mirrors the `core/money.py`
  pure-function-module shape.
- `order_manager.py`: removed the `_bracket_levels` method + `_ONE` constant; added
  `from .brackets.levels import _bracket_levels`; the 2 in-file callers
  (`_assemble_bracket_and_emit`, `_create_fill_anchored_children` — both still in
  order_manager THIS task) drop the `self.` prefix and call the module fn. Removed
  the now-dead `SLTPPolicy` import (sole consumer was `_bracket_levels`).

**Task 2 — BracketManager collaborator** (commit `b306ba0`):
- `itrader/order_handler/brackets/bracket_manager.py` (TAB, no queue): `class
  BracketManager` with an injected-dep `__init__` (`order_storage`, `logger`, the
  coordinator-owned `BracketBook` as `self._brackets`); `_assemble_bracket_and_emit`
  and `_create_fill_anchored_children` moved VERBATIM onto the class. The moved bodies
  call `_bracket_levels(...)` imported `from .levels import _bracket_levels` and
  `self._brackets.arm/.consume`. Module docstring cites D-04/D-08/D-13/T-07-15/RESEARCH
  Pattern 5.
- `brackets/__init__.py`: extended to re-export `BracketManager` +
  `BracketBook` (`__all__ = ["BracketManager", "BracketBook"]`).
- `order_manager.py`: removed the two moved methods; in `__init__`, after
  `self._brackets = BracketBook()`, constructed
  `self.bracket_manager = BracketManager(order_storage, logger, self._brackets)`
  (mirrors `portfolio._init_managers`). The 3 in-file call sites now delegate:
  `process_signal` + `create_orders_from_signal` →
  `self.bracket_manager._assemble_bracket_and_emit(...)`; `on_fill` →
  `self.bracket_manager._create_fill_anchored_children(...)`. Removed the now-dead
  imports (`assert_never`, `PercentFromDecision`, `PercentFromFill`, `_PendingBracket`)
  whose sole runtime consumers moved out.
- External `OrderManager` ctor signature UNCHANGED (5 args); `order_handler.py` and
  `order_handler/__init__.py` byte-unchanged.

## Deviations from Plan

### Auto-fixed Issues

None — both tasks executed as written (pure verbatim code-motion).

### Move-Inherent Dead-Import Removals (not deviations — mandated by the move)

The plan's action bodies mandate removing imports whose sole consumer relocated
(mirroring the plan 06-01 precedent of stripping `_PendingBracket`-only imports):

- **Task 1:** removed `SLTPPolicy` from `order_manager.py` (only `_bracket_levels`,
  now in `levels.py`, used it).
- **Task 2:** removed `assert_never`, `PercentFromDecision`, `PercentFromFill`, and
  `_PendingBracket` from `order_manager.py` (all used ONLY inside the two moved
  methods). `PercentFromFill` survives only in comments now.

`mypy --strict` does not flag unused imports (no linter gate in this repo), so this
is hygiene, not a gate fix — but leaving a dead import after its consumer relocates
contradicts the pure-move intent.

### Out-of-Scope Pre-Existing Finding (left untouched per scope boundary)

`StrategyId` is imported-but-unused in `order_manager.py` — verified PRE-EXISTING
(count 1 in commit `230facd`, before any Task-2 edit). Per the scope boundary
(only auto-fix issues DIRECTLY caused by this task's changes), it is left untouched
and NOT folded into this plan.

## Verification Results

- Golden master byte-exact: `pytest tests/integration/test_backtest_oracle.py` — 3
  passed (134 trades / `final_equity 46189.87730727451`) after BOTH tasks.
- `pytest tests/e2e -m e2e` — 58 passed (no leaf re-baselined); combined
  integration+e2e run 61 passed.
- `pytest tests/unit/order/` — 152 passed (incl. the untouched test_bracket_book.py
  + test_sltp_policy.py).
- `mypy itrader` — Success (165 files after Task 1; 166 after Task 2 — levels.py +
  bracket_manager.py the new modules).
- Indentation: `levels.py`, `bracket_manager.py`, and `order_manager.py` all TAB-only
  (`grep -cP "^    [^ ]"` = 0); `bracket_manager.py` has NO `global_queue` reference.
- `order_handler.py` + `order_handler/__init__.py` byte-unchanged (`git diff --quiet`).
- `self.bracket_manager` appears 4× in order_manager.py (1 construction + 3 delegating
  call sites); brackets/__init__ re-exports both BracketManager + BracketBook.

## Known Stubs

None — no placeholder values, empty returns, or unwired data sources introduced.

## Authentication Gates

None occurred — pure internal code-motion, no external surface.

## Threat Flags

None — per the plan threat model (T-06-03/04/SC), this change crosses no trust
boundary and introduces no new external surface. The primary financial-integrity
risk (a re-indentation or accidental edit silently changing bracket-emit behavior)
is mitigated by the TAB-only verbatim move + byte-exact golden gate
(134 / 46189.87730727451) + e2e 58/58, all green. No package installs this phase.

## Self-Check: PASSED

All created files exist on disk; both per-task commits (230facd, b306ba0) present in
git log.
