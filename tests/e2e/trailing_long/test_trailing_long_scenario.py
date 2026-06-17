"""Wave 0 Nyquist scaffolding for Phase 5 — collectible trailing-long e2e leaf.

Empty (``pytest.skip``-bodied) placeholder created in plan 05-00 so the RESEARCH Test
Map e2e selector ``-k "trailing_long"`` collects >=1 test BEFORE the RED step. The real
end-to-end scenario (with its hand-computed ``bars.csv`` and engine drive) lands in plan
05-03; the stub loads no data.

Folder-derived ``e2e`` marker only (tests/conftest.py auto-applies it; no decorator —
``--strict-markers``). No ``backtesting``/``backtrader`` import (Pitfall 3).
"""

import pytest


def test_trailing_long_scenario():
    pytest.skip("Wave 0 stub — implemented in 05-03")
