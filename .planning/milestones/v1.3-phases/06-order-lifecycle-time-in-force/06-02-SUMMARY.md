---
phase: 06-order-lifecycle-time-in-force
plan: 02
subsystem: order_handler
tags: [dead-code-removal, validator-overlap, D-03, D-03a, W4-09, LIFE-01]
requires:
  - "v1.2 Phase 6 / 06-03: AdmissionManager owns the signal→order pipeline"
  - "OrderOperationType.CREATE_ORDERS_FROM_SIGNAL enum (live ref bracket_manager.py:220)"
provides:
  - "OrderHandler without the dead create_order method"
  - "AdmissionManager with process_signal as the single validated signal→order entry point"
  - "W4-04 validator-overlap doc softened to the live-path-only justification"
affects:
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/admission/admission_manager.py
  - CLAUDE.md
  - .planning/codebase/CONVENTIONS.md
tech-stack:
  added: []
  patterns:
    - "Single validated signal→order path (process_signal); the unvalidated second path removed"
key-files:
  created: []
  modified:
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/admission/admission_manager.py
    - CLAUDE.md
    - .planning/codebase/CONVENTIONS.md
decisions:
  - "D-03: collapse to ONE validated signal→order path by removing the dead create_order chain"
  - "D-03a: drop ONLY the create_order clause from the W4-04 doc; keep the live-TradingInterface bypass justification + all validator code"
  - "Pitfall 1: KEEP OrderOperationType.CREATE_ORDERS_FROM_SIGNAL — still referenced by the LIVE validated path at bracket_manager.py:220"
metrics:
  duration: ~6 min
  completed: 2026-06-13
  tasks: 1
  files: 5
---

# Phase 6 Plan 02: Remove Dead create_order Path & Soften W4-04 Doc Summary

Removed the dead, unvalidated `OrderHandler.create_order` → `OrderManager.create_orders_from_signal`
→ `AdmissionManager.create_orders_from_signal` chain (D-03, W4-09), collapsing the engine to a
single validated `process_signal` path, and softened the W4-04 validator-overlap doc (D-03a) — all
byte-exact against the golden master with the live `CREATE_ORDERS_FROM_SIGNAL` enum + validator code
intact.

## What Was Built

**Task 1 — Delete the dead create_order path + soften the W4-04 doc (commit c68ec04):**

- Deleted `OrderHandler.create_order` (was lines ~215-245) — confirmed zero callsites before removal
  (the live `TradingInterface` builds `OrderEvent`s directly; the run loop uses only
  `on_signal`/`process_signal`). Trimmed its mention from the class docstring API list.
- Deleted `OrderManager.create_orders_from_signal` delegation and the docstring clause naming it as a
  public delegate.
- Deleted `AdmissionManager.create_orders_from_signal` (the unvalidated second entry point) and
  trimmed the module + class docstrings that named it a public entry point — replacing with a D-03/W4-09
  note that `process_signal` is now the single validated path.
- **KEPT** `OrderOperationType.CREATE_ORDERS_FROM_SIGNAL` (`core/enums/order.py:124`) — Pitfall 1: it
  is still referenced by the LIVE validated path at `bracket_manager.py:220`
  (`_assemble_bracket_and_emit` error result). Deleting it would break mypy/import.
- **KEPT UNTOUCHED** `process_signal` and its `_assemble_bracket_and_emit` call (the single validated
  signal→order path).
- **D-03a:** dropped ONLY the `create_order` clause from the W4-04 "Dual-Layer Order-Validator Overlap"
  justification in BOTH `CLAUDE.md` (convention (4)) and `.planning/codebase/CONVENTIONS.md` (W4-04
  section). Kept the live-`TradingInterface`/`OrderEvent` bypass justification and all validator code
  (`order_validator.py` / `simulated.py` untouched).

## Verification Results

- `grep -rn '\.create_order(' itrader/ tests/ scripts/` → **0 lines**
- `grep -rn 'def create_orders_from_signal' itrader/` → **0 lines**
- `grep -c 'CREATE_ORDERS_FROM_SIGNAL' itrader/core/enums/order.py` → **1** (enum member KEPT)
- `grep -q CREATE_ORDERS_FROM_SIGNAL itrader/order_handler/brackets/bracket_manager.py` → **YES** (live ref intact)
- `grep -n 'def process_signal' .../admission/admission_manager.py` → **present** (validated path untouched)
- W4-04 doc (both files): no longer contains the `create_order` clause; still contains the
  live-`TradingInterface` bypass justification.
- `poetry run mypy itrader` → **Success: no issues found in 160 source files** (`--strict` clean)
- Full suite → **978 passed**; `tests/e2e -m e2e` → **59 passed** (58 v1.1 leaves + the Phase 5 LIMIT
  crossval leaf); `tests/integration` → **15 passed** (golden oracle byte-exact: 134 trades /
  `final_equity 46189.87730727451`)

This plan is a pure dead-code removal + doc softening — no run-path behavior change, oracle byte-exact
(LIFE-01 owner-gated re-baseline NOT triggered by this plan; the TIF wiring is the result-changing part,
landed separately).

## Deviations from Plan

None — plan executed exactly as written. The plan's `<interfaces>` line numbers were approximate
(`order_handler.py:215-245`, `order_manager.py:206-208`, `admission_manager.py:286-335`); the actual
ranges matched within a few lines and the unique-string edits applied cleanly. The plan's automated
`make test` was run as `PYTHONPATH="$PWD" poetry run pytest` to defeat the worktree `.venv` editable-install
shadowing hazard (the OLD main-checkout `itrader` would otherwise be imported).

## Notes

- The pre-existing unused `Callable` import in `order_handler.py` / `order_manager.py` was NOT introduced
  by this plan and is out of scope (`mypy --strict` does not flag unused imports); left untouched per the
  SCOPE BOUNDARY rule.
- No file deletions in the commit (only line removals); deletion-safety check clean.

## Self-Check: PASSED

- `itrader/order_handler/order_handler.py` — FOUND (modified)
- `itrader/order_handler/order_manager.py` — FOUND (modified)
- `itrader/order_handler/admission/admission_manager.py` — FOUND (modified)
- `CLAUDE.md` — FOUND (modified)
- `.planning/codebase/CONVENTIONS.md` — FOUND (modified)
- Commit c68ec04 — present in git log
