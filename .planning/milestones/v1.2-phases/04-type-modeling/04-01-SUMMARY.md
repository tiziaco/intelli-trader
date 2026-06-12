---
phase: 04-type-modeling
plan: 01
subsystem: execution + order
tags: [type-modeling, immutability, dataclass, D-07, W2-04, TYPE-01]
requires:
  - "events_handler/events/error.py frozen-fact template (frozen=True, slots=True, kw_only=True)"
provides:
  - "frozen FillDecision/CancelDecision decision DTOs (matching_engine.py)"
  - "frozen OperationResult/SignalProcessingResult result DTOs with tuple event fields (operation_result.py)"
affects:
  - "itrader/execution_handler/matching_engine.py"
  - "itrader/order_handler/operation_result.py"
tech-stack:
  added: []
  patterns:
    - "frozen=True, slots=True, kw_only=True dataclass for in-process decision/result facts"
    - "tuple[T, ...] = () immutable collection fields built at construction (no field(default_factory=list))"
key-files:
  created: []
  modified:
    - "itrader/execution_handler/matching_engine.py"
    - "itrader/order_handler/operation_result.py"
decisions:
  - "Kept operation_type as str (the OrderOperationType enum flip is co-located in Plan 04-04 with the enum it needs, per 04-PATTERNS §2)"
requirements_completed: [TYPE-01]
metrics:
  duration_minutes: 12
  completed_date: 2026-06-11
  tasks: 2
  files_modified: 2
---

# Phase 4 Plan 01: Type Modeling — Freeze Decision/Result DTOs Summary

Froze the engine's four decision/result dataclasses into immutable facts (`frozen=True, slots=True, kw_only=True`) and migrated the mutable `List` event fields on the result DTOs to `tuple[OrderEvent, ...]` — a behavior-preserving correctness hardening that surfaces accidental mutation and positional construction as errors, byte-exact against the golden master.

## What Was Built

- **Task 1 — `matching_engine.py` (4-space file):** Changed the bare `@dataclass` on `FillDecision` (`order_event`, `fill_price`, `reason`) and `CancelDecision` (`order_event`, `reason`) to `@dataclass(frozen=True, slots=True, kw_only=True)`, copying the decorator form verbatim from `events/error.py:21`. Audited all three construction sites — the two `FillDecision(...)` calls were already keyword; the one positional `CancelDecision(sibling, "OCO - sibling filled")` OCO call was migrated to `CancelDecision(order_event=sibling, reason="OCO - sibling filled")`. No matching/trigger/OCO logic touched. Commit 9ac2d1d.
- **Task 2 — `operation_result.py` (TAB file):** Changed both `@dataclass` decorators on `OperationResult` and `SignalProcessingResult` to `@dataclass(frozen=True, slots=True, kw_only=True)`. Retyped the three mutable `List` fields to immutable tuples: `order_events: tuple[OrderEvent, ...] = ()`, `affected_order_ids: tuple[Any, ...] = ()`, `operation_results: tuple[OperationResult, ...] = ()`. The factory classmethods now build tuples at construction (`tuple(order_events or ())`, `tuple(affected_order_ids or ())`, `operation_results=tuple(operation_results)`). The `all_order_events` property is unchanged — it `extend`s a LOCAL list, unaffected by the frozen field. Dropped the now-unused `field` import. `operation_type` left as `str` (the `OrderOperationType` flip lives in Plan 04-04). Commit 8f1c5aa.

## Verification

- `poetry run mypy --strict itrader` → **Success: no issues found in 139 source files** (after each task).
- Runtime asserts: `FillDecision`/`CancelDecision`/`OperationResult`/`SignalProcessingResult` all report `__dataclass_params__.frozen=True`, `kw_only=True`, `__slots__` present; `OperationResult.success_result('ok').order_events` is a `tuple`; `SignalProcessingResult.from_operations([...]).operation_results` is a `tuple`.
- `pytest tests/integration` → **12 passed** including `test_backtest_oracle.py` which asserts byte-exact **134 trades / final_equity 46189.87730727451**.
- `pytest tests/e2e -m e2e` → **58 passed** (no leaf re-baselined).
- `pytest tests/unit/order tests/unit/execution` → **278 passed**.
- No positional `FillDecision(`/`CancelDecision(` construction remains (grep).

## Deviations from Plan

None — plan executed exactly as written. The only audit finding (one positional `CancelDecision` OCO call-site) was anticipated by the plan's `<action>` ("migrate any POSITIONAL call to KEYWORD args") and migrated, not a deviation.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: itrader/execution_handler/matching_engine.py
- FOUND: itrader/order_handler/operation_result.py
- FOUND commit: 9ac2d1d (refactor(04-01): freeze FillDecision/CancelDecision)
- FOUND commit: 8f1c5aa (refactor(04-01): freeze OperationResult/SignalProcessingResult)
