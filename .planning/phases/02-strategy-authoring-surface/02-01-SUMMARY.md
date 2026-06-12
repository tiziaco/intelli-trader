---
phase: 02-strategy-authoring-surface
plan: 01
subsystem: core/exceptions
tags: [exceptions, strategy, validation, foundation]
requires: []
provides:
  - "UnknownParamError (subclass of ValidationError)"
  - "MissingParamError (subclass of ValidationError)"
  - "barrel re-export of both via itrader.core.exceptions"
affects:
  - "Plan 02 (strategy param-introspection engine imports these symbols)"
tech-stack:
  added: []
  patterns:
    - "domain-exception module shape (order.py analog): docstring -> import base -> ValidationError subclasses with structured __init__"
key-files:
  created:
    - itrader/core/exceptions/strategy.py
  modified:
    - itrader/core/exceptions/__init__.py
decisions:
  - "UnknownParamError accepts list[str] (engine call-shape UnknownParamError(sorted(kwargs))); sets self.names + field='strategy_params'"
  - "MissingParamError accepts a single str (engine call-shape MissingParamError(name)); sets self.name + field=name"
  - "Both subclass house ValidationError per RESEARCH §Don't Hand-Roll — never bare ValueError"
metrics:
  duration: ~5 min
  completed: 2026-06-12
requirements: [STRAT-01]
---

# Phase 2 Plan 01: Strategy Authoring Surface — Exceptions Foundation Summary

Created `core/exceptions/strategy.py` with `UnknownParamError` and `MissingParamError` — the two loud-rejection errors the Strategy param-introspection engine (Plan 02) raises on unknown kwargs (D-06) and missing-required bare-annotation attrs (D-07); both subclass the house `ValidationError` and are re-exported through the barrel. Zero run-path touch — landed in its own wave to de-risk the Wave-2 engine migration.

## What Was Built

### Task 1 — `itrader/core/exceptions/strategy.py` (commit `9b19970`)
- New 4-space-indented module mirroring `order.py`'s docstring-per-class shape.
- `UnknownParamError(ValidationError)` — accepts `names: list[str]`, stores `self.names`, builds a message naming the offending param(s), supers with `field="strategy_params"`. Satisfies the engine call-shape `UnknownParamError(sorted(kwargs))`.
- `MissingParamError(ValidationError)` — accepts `name: str`, stores `self.name`, supers with `field=name`. Satisfies the engine call-shape `MissingParamError(name)`.
- Both set their structured attribute(s) THEN super, mirroring `UnsizedSignalError`.

### Task 2 — `itrader/core/exceptions/__init__.py` (commit `fb7cdb4`)
- Added a `# Strategy exceptions` import group importing both classes from `.strategy`.
- Appended both names to `__all__` under a matching `# Strategy exceptions` comment (single-quote style preserved).

## Threat Mitigations Delivered

| Threat ID | Disposition | Mitigation |
|-----------|-------------|------------|
| T-02-01 (unknown kwarg silently dropped) | mitigate | `UnknownParamError` defined (raised by the engine in Plan 02, D-06) |
| T-02-02 (under-specified strategy) | mitigate | `MissingParamError` defined (raised by the engine in Plan 02, D-07) |

## Verification

- `from itrader.core.exceptions.strategy import UnknownParamError, MissingParamError` — both subclass `ValidationError`; `MissingParamError("sizing_policy")` and `UnknownParamError(["typo_kw"])` construct without error.
- `from itrader.core.exceptions import UnknownParamError, MissingParamError` — barrel import succeeds.
- `poetry run mypy --strict itrader/core/exceptions/strategy.py` — clean.
- `pytest tests/integration` — 12 passed, BTCUSD oracle byte-exact (134 trades / `final_equity 46189.87730727451`).
- `pytest tests/e2e -m e2e` — 58/58 passed (no leaf re-baselined). `tests/unit/strategy` green.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- FOUND: itrader/core/exceptions/strategy.py
- FOUND: commit 9b19970
- FOUND: commit fb7cdb4
