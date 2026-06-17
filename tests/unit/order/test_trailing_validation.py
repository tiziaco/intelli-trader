"""Wave 0 Nyquist scaffolding for Phase 5 — collectible trailing-validation stubs.

Empty (``pytest.skip``-bodied) placeholders created in plan 05-00 so the D-TRAIL-7
non-viable-trail rejection selector (``-k "trailing and reject"``) collects >=1 test
BEFORE the RED step. The real validator assertions land in plan 05-01.

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no decorator —
``--strict-markers``). No ``backtesting``/``backtrader`` import (Pitfall 3).
"""

import pytest


def test_trailing_reject_percent_ge_one():
    pytest.skip("Wave 0 stub — implemented in 05-01")


def test_trailing_reject_absolute_ge_reference_price():
    pytest.skip("Wave 0 stub — implemented in 05-01")


def test_trailing_reject_missing_trail_value():
    pytest.skip("Wave 0 stub — implemented in 05-01")
