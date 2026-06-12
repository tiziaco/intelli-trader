---
phase: 06-order-manager-decomposition
plan: 01
subsystem: order_handler
tags: [refactor, brackets, code-motion, byte-exact, D-10-step-1]
requires:
  - "order_manager.py _pending_brackets raw dict + _PendingBracket dataclass (pre-extraction state)"
provides:
  - "BracketBook primitive (single owner of the pending-bracket map, D-05) at order_handler/brackets/bracket_book.py"
  - "_PendingBracket relocated to brackets/bracket_book.py (D-03), re-importable by order_manager.py"
  - "all 8 _pending_brackets sites in order_manager.py routed through BracketBook (arm/get/consume/refresh_quantity)"
affects:
  - "plan 06-02+ (admission/brackets/reconcile/lifecycle extractions inject + consume this BracketBook)"
tech-stack:
  added: []
  patterns:
    - "thin owner-class wrapping Dict[OrderId, _PendingBracket] with byte-equal named methods"
    - "dict-compat dunders (__eq__/__contains__/__len__) keep internal-attribute-coupled test green untouched (Pitfall 2 option a)"
    - "read-only _pending_brackets property returns the book (single owner, no second raw dict — Pitfall 2 option c forbidden)"
key-files:
  created:
    - itrader/order_handler/brackets/__init__.py
    - itrader/order_handler/brackets/bracket_book.py
    - tests/unit/order/test_bracket_book.py
  modified:
    - itrader/order_handler/order_manager.py
decisions:
  - "Relative-import depth: brackets/ is one level deeper than order_manager.py, so bracket_book.py uses ...core (three dots), not ..core as the plan interface note literally said (that note was written relative to order_manager.py's depth)."
  - "8 dict-op sites map to 6 BracketBook method calls: the :1164 get + :1166 set pair is collapsed into ONE refresh_quantity() call exactly as the plan action body specifies (the get is folded inside refresh_quantity). The acceptance grep that expected literal 8 was internally inconsistent with the action body; behavioral byte-exactness is the binding proof."
  - "Removed now-dead `from dataclasses import dataclass, replace` import: both symbols were used ONLY by the moved _PendingBracket (dataclass) and the collapsed :1166 set (replace); plan action mandates removing _PendingBracket-only imports."
metrics:
  duration_min: 3
  completed: "2026-06-11"
  tasks: 2
  files: 4
---

# Phase 6 Plan 01: BracketBook In-Place Wrap (D-10 step 1) Summary

D-10 step 1 introduces `BracketBook` IN PLACE as the single owner of the pending-bracket
map (D-04/D-05): `OrderManager._pending_brackets` (a raw `Dict[OrderId, _PendingBracket]`)
is replaced by a `BracketBook` instance whose methods are byte-equal wrappers over the
current dict ops, and all 8 verified sites are routed through it. `_PendingBracket` moves
verbatim into the new `brackets/bracket_book.py` (D-03). NO collaborator code is moved in
this step — this is the lowest-risk extraction, giving the shared FRAGILE bracket state a
single owner before any methods relocate, golden-gated in isolation.

## What Was Built

**Task 1 — brackets/ package + BracketBook + lean unit test** (commit `38e5fce`):
- `itrader/order_handler/brackets/bracket_book.py` (TAB-indented): `_PendingBracket` moved
  verbatim from `order_manager.py:34-52` (`action: str` kept — W2-02 deferred to 999.5 per
  D-13), plus the new `BracketBook` primitive with `arm`/`get`/`consume`/`refresh_quantity`
  byte-equal to the dict ops, and dict-compat dunders (`__eq__`/`__contains__`/`__len__`).
- `itrader/order_handler/brackets/__init__.py`: re-exports `BracketBook` only (`BracketManager`
  joins in plan 02), `__all__ = ["BracketBook"]`.
- `tests/unit/order/test_bracket_book.py` (4-space house style, 7 tests): arm/get round-trip,
  get-miss None, consume returns-and-removes, idempotent consume→None on miss,
  refresh_quantity replaces only quantity (preserves all other fields), refresh-miss no-op,
  dict-compat dunders.

**Task 2 — rewire order_manager.py's 8 sites** (commit `1644ed7`):
- `self._pending_brackets: Dict = {}` → `self._brackets = BracketBook()`.
- Sites :240/:249/:729/:1231 `.pop(.., None)` → `self._brackets.consume(..)` (idempotent).
- Site :640 `[primary.id] = _PendingBracket(..)` → `self._brackets.arm(primary.id, _PendingBracket(..))`.
- Sites :1164 `.get` + :1166-67 `[..] = replace(.., quantity=..)` → one
  `self._brackets.refresh_quantity(order.id, to_money(new_quantity))`.
- Added a read-only `_pending_brackets` property returning the book so the
  internal-attribute-coupled `test_sltp_policy.py` reaches it unchanged (its `== {}` / `in`
  assertions pass byte-equal via the dunders — Pitfall 2 option a; single owner, no second
  raw dict — option c forbidden).
- Removed the moved `_PendingBracket` dataclass + its now-dead `dataclass`/`replace` imports;
  added `from .brackets import BracketBook` and `from .brackets.bracket_book import _PendingBracket`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Relative-import depth corrected (..core → ...core)**
- **Found during:** Task 1 verification (ModuleNotFoundError: `itrader.order_handler.core`).
- **Issue:** The plan interface note said `from ..core.ids` / `from ..core.sizing`, but
  `bracket_book.py` lives at `order_handler/brackets/`, one level deeper than
  `order_manager.py` (where `..core` resolves correctly). From `brackets/`, `..core` resolves
  to the nonexistent `order_handler.core`.
- **Fix:** Used `...core.ids` / `...core.sizing` (three dots) to reach `itrader.core`.
- **Files modified:** itrader/order_handler/brackets/bracket_book.py
- **Commit:** 38e5fce

### Plan-Inconsistency Note (not a deviation — followed the action body)

**8 dict-op sites → 6 BracketBook method calls.** The plan's acceptance-criteria grep expected
`self._brackets.(arm|get|consume|refresh_quantity)` to return 8, but the plan's own action body
maps the :1164 `get` + :1166 `set` pair into a SINGLE `refresh_quantity()` call (the `get` is
folded inside `refresh_quantity`). The implemented result is 6 distinct call lines (4×consume,
1×arm, 1×refresh_quantity), which is the semantically-correct single-owner outcome. Byte-exact
golden + e2e 58/58 are the binding proof of behavior preservation; the literal grep count was an
internal inconsistency in the criteria text, not a behavioral requirement.

## Verification Results

- Golden master byte-exact: `pytest tests/integration/test_backtest_oracle.py` — 3 passed
  (134 trades / `final_equity 46189.87730727451`).
- `pytest tests/e2e -m e2e` — 58 passed (no leaf re-baselined).
- `pytest tests/unit/order/` — 155 passed (incl. new test_bracket_book.py 7/7 +
  test_sltp_policy.py 5/5 UNTOUCHED via `git diff --quiet`).
- `mypy itrader` — Success, no issues in 164 source files.
- `order_manager.py` remains TAB-only (`grep -cP "^    [^ ]"` = 0); `bracket_book.py` TAB-only.
- `order_handler/__init__.py` byte-unchanged (`git diff --quiet`).
- No raw dict subscript writes / `.pop` / `.get` on `_pending_brackets` remain in order_manager.py.

## No Code Moved Out

Per D-10 step 1, NO collaborator code (admission/brackets/reconcile/lifecycle methods) was
moved out of `order_manager.py` in this step — only the dict→BracketBook wrap. The
assemble/modify/reconcile bodies still live in `order_manager.py` and still reference
`_PendingBracket` (imported back from `brackets/bracket_book.py`).

## Known Stubs

None — no placeholder values, empty returns, or unwired data sources introduced.

## Authentication Gates

None occurred — pure internal code-motion, no external surface.

## Threat Flags

None — per the plan threat model (T-06-01/02/SC), this change crosses no trust boundary and
introduces no new external surface; the primary financial-integrity risk (non-byte-equal
wrapper) is mitigated by the byte-exact golden gate + e2e 58/58 + the D-15 idempotent-consume
unit test, all green.

## Self-Check: PASSED

All created files exist on disk; both per-task commits (38e5fce, 1644ed7) present in git log.
