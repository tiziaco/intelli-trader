---
phase: 06-order-lifecycle-time-in-force
plan: 01
subsystem: core-enums
tags: [LIFE-01, D-09, enum, wave-0, byte-inert]
requires: []
provides:
  - "OrderCommand.EXPIRE member + order_command_map['EXPIRE'] entry"
  - "FillStatus.EXPIRED member (FillEvent.new_fill('EXPIRED', ...) parses)"
affects:
  - "Plan 03 EXPIRE arms (sweep / exchange EXPIRE / reconcile EXPIRED) consume these members"
tech-stack:
  added: []
  patterns:
    - "config-enum house pattern: explicit string value + case-insensitive _missing_ (no new _missing_ needed — inherited)"
key-files:
  created:
    - tests/unit/core/test_enums_expire.py
  modified:
    - itrader/core/enums/order.py
    - itrader/core/enums/execution.py
decisions:
  - "D-09 enum-first ordering: OrderCommand.EXPIRE + FillStatus.EXPIRED land BEFORE Plan 03 wires the EXPIRE arms (Pitfall 2: new_fill('EXPIRED', ...) raises ValueError until FillStatus.EXPIRED exists)"
  - "OrderStatus.EXPIRED / order_status_map / VALID_ORDER_TRANSITIONS already covered EXPIRED — confirmed present and left unchanged (regression-guarded by the new test)"
metrics:
  duration: ~6 min
  completed: 2026-06-13
  tasks: 1
  files: 3
---

# Phase 6 Plan 01: EXPIRE Lifecycle Enum Seams Summary

Added the two first-class enum members the EXPIRE lifecycle is built on — `OrderCommand.EXPIRE`
(`core/enums/order.py`) and `FillStatus.EXPIRED` (`core/enums/execution.py`) — per D-09, with a
Wave-0 unit test. Members are inert until Plan 03 wires them; zero run-path behavior change.

## What Was Built

- **`OrderCommand.EXPIRE = "EXPIRE"`** added to the `OrderCommand` Enum (tab-indented region) plus
  `"EXPIRE": OrderCommand.EXPIRE` to `order_command_map` (tab-indented dict region). The inherited
  case-insensitive `_missing_` resolves `OrderCommand("expire")` to the member with no change.
- **`FillStatus.EXPIRED = "EXPIRED"`** added to the `FillStatus` Enum (4-space region). This closes
  Pitfall 2: `FillEvent.new_fill('EXPIRED', ...)` runs `FillStatus(status)` and raised `ValueError`
  until the member existed.
- **`tests/unit/core/test_enums_expire.py`** (7 tests, `unit` marker folder-derived): EXPIRE value +
  map round-trip + case-insensitive `_missing_`; EXPIRED value + case-insensitive `_missing_`;
  `new_fill('EXPIRED', ...)` parses without raising (reuses the existing `_order_event()`
  OrderEvent-construction pattern from `test_fill_event_schema.py`); and a regression guard that
  `VALID_ORDER_TRANSITIONS[OrderStatus.EXPIRED] == []` and `PENDING -> EXPIRED` are pre-existing and
  unchanged.

## TDD Cycle

- **RED** (`5f6139f`): 6 of 7 tests fail (the new EXPIRE/EXPIRED members don't exist;
  AttributeError / KeyError / ValueError as expected); the transition-table guard already passes.
- **GREEN** (`1b20bab`): two enum members + one map entry added; all 7 tests pass.
- **REFACTOR**: not needed (two member additions, nothing to clean up).

## Indentation (tab/space hazard)

- `core/enums/order.py` is tab-indented throughout (verified byte-wise: both the `OrderCommand` Enum
  members AND the `order_command_map` dict body use `\t`). Edits matched tabs. (The PATTERNS.md prose
  said the Enum members were space-indented — that was inaccurate for this file; matched the actual
  file bytes per the project rule.)
- `core/enums/execution.py` is 4-space-indented; the `FillStatus.EXPIRED` edit matched 4 spaces.

## Verification

- `poetry run pytest tests/unit/core/test_enums_expire.py -x` -> 7 passed
- `poetry run mypy itrader` -> Success: no issues found in 160 source files
- `git diff` scope confirmed: only the two added enum members + one map entry across the two files
  (no edit to `VALID_ORDER_TRANSITIONS`, `order_status_map`, `OrderStatus`, or either `_missing_`).
- All test/typecheck invocations were run with `PYTHONPATH="$PWD"` to defeat the worktree `.venv`
  editable-install shadowing (worktree-venv-shadowing hazard).

## Deviations from Plan

None — plan executed exactly as written. (The only judgment call: PATTERNS.md prose described the
`OrderCommand` Enum members as space-indented, but the actual file uses tabs in that region; matched
the file bytes per the never-normalize rule. This is not a behavior deviation — the resulting diff is
identical in effect and is correctly tab-indented.)

## Known Stubs

None — both members are intentionally inert until Plan 03 wires them (sweep / exchange EXPIRE arm /
reconcile EXPIRED arm). This is by design per the plan objective, not an unresolved stub.

## Self-Check: PASSED

- FOUND: tests/unit/core/test_enums_expire.py
- FOUND: itrader/core/enums/order.py (contains `EXPIRE = "EXPIRE"` + `"EXPIRE": OrderCommand.EXPIRE`)
- FOUND: itrader/core/enums/execution.py (contains `EXPIRED = "EXPIRED"`)
- FOUND commit: 5f6139f (test/RED gate)
- FOUND commit: 1b20bab (feat/GREEN gate)

## TDD Gate Compliance

- RED gate commit present: `5f6139f` (`test(06-01): ...`)
- GREEN gate commit present: `1b20bab` (`feat(06-01): ...`)
- REFACTOR gate: not applicable (no refactor performed).
