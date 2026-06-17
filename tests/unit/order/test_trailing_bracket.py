"""Wave 0 Nyquist scaffolding for Phase 5 — collectible trailing-bracket stubs.

Empty (``pytest.skip``-bodied) placeholders created in plan 05-00. The function names
contain BOTH ``trailing`` and ``bracket`` so the compound selector
``-k "trailing and bracket"`` used by plan 05-03 Task 1 (D-TRAIL-3/D-TRAIL-5 bracket
declaration) collects >=1 test — otherwise pytest exits code 5 (no coverage evidence
for the bracket-declaration task). Both long and short are covered (shorts were added
only in Phase 3 — coverage does NOT transfer). The real bracket-declaration assertions
land in plan 05-03.

Folder-derived ``unit`` marker only (tests/conftest.py auto-applies it; no decorator —
``--strict-markers``). No ``backtesting``/``backtrader`` import (Pitfall 3).
"""

import pytest


def test_trailing_bracket_child_replaces_fixed_sl():
    pytest.skip("Wave 0 stub — implemented in 05-03")


def test_trailing_bracket_child_replaces_fixed_sl_short():
    pytest.skip("Wave 0 stub — implemented in 05-03")
