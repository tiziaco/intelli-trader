"""Portfolio margin seam residuals (WR-01 / WR-05) — Phase 3 Wave 0 scaffold.

Collectible RED placeholders seeded by Plan 03-02 (the Nyquist contract, D-10):
the Plan 03-06 verify selectors `funds_invariant_lock` and
`open_commission_accumulator` must each select >=1 test BEFORE any production code
is written, so a downstream `<automated>` verify can never select zero tests and
report a silent green.

- WR-01 (`funds_invariant_lock`): the funds invariant (balance == available +
  reserved + locked) holds across the short reserve/lock lifecycle.
- WR-05 (`open_commission_accumulator`): opening commission accumulates correctly
  into the position cost basis under shorts.

These stubs assert NOTHING yet — Plan 03-06 turns them green. Folder-derived
`unit` marker only (tests/conftest.py applies it; no decorator here).
"""

import pytest


def test_funds_invariant_lock_stub():
    """WR-01: funds invariant holds across the short lock lifecycle (Plan 03-06)."""
    pytest.skip("Phase 3 Wave 0 stub — implemented in plan 03-06")


def test_open_commission_accumulator_stub():
    """WR-05: opening commission accumulates into cost basis (Plan 03-06)."""
    pytest.skip("Phase 3 Wave 0 stub — implemented in plan 03-06")
