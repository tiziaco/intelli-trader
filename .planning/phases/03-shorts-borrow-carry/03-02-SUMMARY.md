---
phase: 03-shorts-borrow-carry
plan: 02
subsystem: test-scaffold
tags: [nyquist, wave-0, test-only, e2e-parked, shorts, carry]
requires:
  - "tests/e2e/levered_long/ (PARKED e2e template)"
  - "tests/conftest.py (folder-derived type markers)"
provides:
  - "13 collectible skipped unit selector stubs (Nyquist Wave-0 coverage)"
  - "3 parked e2e scenario dirs (short_roundtrip, short_carry, partial_cover)"
  - "tests/unit/portfolio/test_carry.py (NEW days-basis/accrual module)"
  - "tests/unit/portfolio/test_portfolio_margin.py (NEW WR-01/WR-05 module)"
  - "tests/unit/strategy/test_strategies_handler_registration.py (NEW SHORT-01 module)"
affects:
  - "Plans 03-03 / 03-04 / 03-05 / 03-06 verify selectors (each now selects >=1 test)"
tech-stack:
  added: []
  patterns:
    - "pytest.skip-bodied collectible RED stubs (folder-derived markers, no decorator)"
    - "PARKED e2e convention mirrored from tests/e2e/levered_long/ (synthetic instrument, no --freeze)"
key-files:
  created:
    - tests/unit/strategy/test_strategies_handler_registration.py
    - tests/unit/portfolio/test_carry.py
    - tests/unit/portfolio/test_portfolio_margin.py
    - tests/e2e/short_roundtrip/__init__.py
    - tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py
    - tests/e2e/short_carry/__init__.py
    - tests/e2e/short_carry/test_short_carry_scenario.py
    - tests/e2e/partial_cover/__init__.py
    - tests/e2e/partial_cover/test_partial_cover_scenario.py
  modified:
    - tests/unit/order/test_admission_rules.py
    - tests/unit/order/test_sizing_resolver.py
    - tests/unit/portfolio/test_position_manager.py
    - tests/unit/portfolio/test_cash_manager.py
    - tests/unit/portfolio/test_portfolio_handler.py
decisions:
  - "D-10 Nyquist contract: every Phase-3 verify selector resolves to >=1 collectible test BEFORE its production plan runs"
  - "Parked e2e stubs carry the levered_long PARKED docstring convention; not frozen as golden until Phase 4/XVAL-01; no --freeze"
metrics:
  duration: ~9m
  completed: 2026-06-15
---

# Phase 3 Plan 02: Nyquist Wave-0 Test Scaffold Summary

Seeded 13 collectible `pytest.skip` unit selector stubs plus 3 parked e2e scenario dirs so every Phase-3 functional verify target (`-k`/`-m` token) selects at least one collectible test before any RED step — the Nyquist contract (D-10), test-only and oracle-untouched.

## What Was Built

**Task 1 — unit selector stubs (commit `fe4e02f`):** Added a skip-bodied stub function per Phase-3 verify selector, named so the RESEARCH verify-map `-k` token selects it. Extended 5 existing modules and created 3 new modules:

| Selector token | Module | Status |
|----------------|--------|--------|
| `short_registration` | `tests/unit/strategy/test_strategies_handler_registration.py` (NEW) | skipped |
| `cover_arm`, `over_cover_clamp`, `leverage_floor` | `tests/unit/order/test_admission_rules.py` (extended) | skipped |
| `cover_magnitude` | `tests/unit/order/test_sizing_resolver.py` (extended) | skipped |
| `short_pnl` | `tests/unit/portfolio/test_position_manager.py` (extended) | skipped |
| `borrow_interest`, `borrow_interest_op`, `release_symmetry` | `tests/unit/portfolio/test_cash_manager.py` (extended) | skipped |
| `days_basis` (+ `borrow_interest`) | `tests/unit/portfolio/test_carry.py` (NEW) | skipped |
| `funds_invariant_lock`, `open_commission_accumulator` | `tests/unit/portfolio/test_portfolio_margin.py` (NEW) | skipped |
| `universe_unwired` | `tests/unit/portfolio/test_portfolio_handler.py` (extended) | skipped |

**Task 2 — parked e2e scenario dirs (commit `a391e28`):** Created `short_roundtrip/`, `short_carry/`, `partial_cover/`, each with an empty `__init__.py` and a `test_<name>_scenario.py` carrying the PARKED docstring convention copied in spirit from `tests/e2e/levered_long/` (hand-computed literals to come, synthetic instrument NEVER BTCUSD, real run path, NO golden-diff harness, frozen as golden ONLY at Phase 4/XVAL-01). Each has a single `pytest.skip`-bodied test. No `bars.csv` data (the implementing plan authors the literals). No `--freeze`.

## Verification

- Task 1 `--co -k "<13 tokens>"`: **14 tests selected** (>=13 — `borrow_interest` matches both the cash_manager op-flow stub and the carry accrual stub), zero collection errors.
- Task 1 full run of the 8 modules: **153 passed, 14 skipped**, zero warnings-as-errors.
- Task 2 `--co -m e2e`: 3 scenario stubs collected, zero errors; run reports **3 skipped**.
- Full collection of touched domains (`tests/unit/{strategy,order,portfolio} tests/e2e`): **607 tests collected** with zero errors/warnings.
- `git diff` vs base `2cda596` touches **only `tests/`** — zero production code changes; SMA_MACD oracle untouched.
- No BTCUSD usage (the three docstring matches are the "NEVER BTCUSD" negation, mirroring the template); no `--freeze`; no golden artifact created.

## Deviations from Plan

None — plan executed exactly as written. The two RESEARCH-cited filename corrections from 03-PATTERNS.md (`test_position.py` → `test_position_manager.py`; `test_strategies_handler.py` → new `test_strategies_handler_registration.py`) were already resolved in the plan body and followed as specified.

## Known Stubs

All 14 unit stubs and 3 e2e stubs are intentional collectible RED placeholders (the Nyquist Wave-0 deliverable). Each is `pytest.skip`-bodied and names the implementing plan in its skip reason (03-03 / 03-04 / 03-05 / 03-06). They are turned green by the downstream production plans; this plan's goal IS to create them, so their stub status is the intended terminal state for Wave 0.
