"""Borrow-interest days-basis / accrual formula (CARRY-01) — Phase 3 Wave 0 scaffold.

Collectible RED placeholder seeded by Plan 03-02 (the Nyquist contract, D-10):
the Plan 03-05 verify selector `days_basis` must select >=1 test BEFORE any
production code is written, so a downstream `<automated>` verify can never
select zero tests and report a silent green.

CARRY-01: borrow-interest accrual derives its days-basis from the bar's BUSINESS
time (never wall clock — determinism), and the per-bar carry debit is computed in
Decimal end-to-end. The `borrow_interest` accrual itself is also exercised by
`tests/unit/portfolio/test_cash_manager.py`; this NEW module is the dedicated home
for the days-basis / accrual-formula case. These stubs assert NOTHING yet — Plan
03-05 turns them green. Folder-derived `unit` marker only (tests/conftest.py
applies it; no decorator here).
"""

import pytest


def test_days_basis_stub():
    """CARRY-01: days basis comes from bar business time, no wall clock (Plan 03-05)."""
    pytest.skip("Phase 3 Wave 0 stub — implemented in plan 03-05")


def test_borrow_interest_accrual_formula_stub():
    """CARRY-01: per-bar borrow_interest accrual formula in Decimal (Plan 03-05).

    Named to also satisfy the `borrow_interest` selector from this dedicated
    carry module (the cash_manager module carries the op-flow case).
    """
    pytest.skip("Phase 3 Wave 0 stub — implemented in plan 03-05")
