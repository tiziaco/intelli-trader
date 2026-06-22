---
phase: 03-shorts-borrow-carry
plan: 01
subsystem: core (value object + enum)
tags: [carry, shorts, instrument, cash-ledger, oracle-dark]
requires: []
provides:
  - "Instrument.borrow_rate (Decimal, default Decimal('0'))"
  - "CashOperationType.BORROW_INTEREST member"
affects:
  - "universe/universe.py instrument(symbol) read-model (surfaces borrow_rate per symbol)"
  - "Plan 05 per-bar short-carry accrual (consumes both seams)"
tech-stack:
  added: []
  patterns:
    - "Default-off gate via Decimal('0') (carry-off keeps SMA_MACD byte-exact)"
    - "Additive enum member picked up by _missing_ parser + duck-typed serializer"
key-files:
  created: []
  modified:
    - itrader/core/instrument.py
    - itrader/core/enums/portfolio.py
    - tests/unit/core/test_instrument.py
    - tests/unit/portfolio/test_cash_manager.py
decisions:
  - "D-01: borrow_rate is per-instrument, static-over-time, default Decimal('0')"
  - "D-03: BORROW_INTEREST is a first-class, auditable financing-cost op kind"
metrics:
  duration: ~12m
  completed: 2026-06-15
  tasks: 2
  files-changed: 4
---

# Phase 3 Plan 01: Borrow-Carry Data/Enum Foundations Summary

Landed two inert, default-off seams the CARRY-01 borrow-carry feature reads from: a per-symbol
`borrow_rate: Decimal = Decimal("0")` field on the frozen `Instrument` value object (D-01) and a
first-class `CashOperationType.BORROW_INTEREST` member (D-03). Both are oracle-dark — no run path
references them yet; SMA_MACD stays byte-exact (134 trades / `46189.87730727451`).

## What Was Built

### Task 1 — `Instrument.borrow_rate` (D-01) — TDD
- Added `borrow_rate: Decimal = Decimal("0")` to the defaulted tail of the frozen, `kw_only`
  `Instrument` dataclass (next to `settles_funding`), with a `Fields` docstring entry mirroring
  the `maintenance_margin_rate` style. 4-space indent (core/).
- Default is `Decimal("0")` — never int `0` (Pitfall 3 / T-03-01: an int default re-enters int
  arithmetic in the Plan-05 carry formula and fails `mypy --strict`). Guarded by an
  `isinstance(..., Decimal)` test assertion and `mypy --strict`.
- RED commit `6c43519` → GREEN commit `17acfa5`.

### Task 2 — `CashOperationType.BORROW_INTEREST` (D-03) — TDD
- Added one member `BORROW_INTEREST = "BORROW_INTEREST"` alongside `RELEASE_RESERVATION`. The
  existing `_missing_` case-insensitive parser resolves it automatically (no parser change).
- `reporting/cash_operations.py` left UNCHANGED — it serializes `op.operation_type.name`
  duck-typed, so the new member appears automatically (editing it is the RESEARCH anti-pattern).
  Verified unchanged via `git diff`.
- RED commit `a45c327` → GREEN commit `ae75316`.

## Verification

- `poetry run mypy --strict itrader/core/instrument.py itrader/core/enums/portfolio.py` — clean (2 files, 0 issues)
- `poetry run pytest tests/unit/core tests/unit/portfolio -q` — 357 passed
- Integration suite (`tests/integration -m integration`) — 16 passed, incl. `test_backtest_oracle.py`
  golden-master diff → SMA_MACD byte-exact (134 trades / `46189.87730727451`)
- `reporting/cash_operations.py` unchanged (enum-agnostic serializer)
- Both modified source files confirmed tab-free (4-space, per the Indentation Map)

## Deviations from Plan

None — plan executed exactly as written. No deviation rules triggered; both tasks were single-field
additive changes with their analogs in the same file.

## Self-Check: PASSED

- FOUND: itrader/core/instrument.py (`borrow_rate: Decimal = Decimal("0")`)
- FOUND: itrader/core/enums/portfolio.py (`BORROW_INTEREST = "BORROW_INTEREST"`)
- FOUND commit 6c43519 (Task 1 RED), 17acfa5 (Task 1 GREEN)
- FOUND commit a45c327 (Task 2 RED), ae75316 (Task 2 GREEN)

## TDD Gate Compliance

Both tasks followed RED → GREEN. Per task: a `test(...)` commit precedes its `feat(...)` commit in
git log. No REFACTOR commit needed (single-field additive changes). Gate sequence satisfied.
