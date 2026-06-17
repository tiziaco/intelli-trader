"""Wave 0 Nyquist scaffolding for Phase 5 — collectible trailing-short e2e leaf.

Empty (``pytest.skip``-bodied) placeholder created in plan 05-00 so the RESEARCH Test
Map e2e selector ``-k "trailing_short"`` collects >=1 test BEFORE the RED step. Shorts
were added only in Phase 3, so long coverage does NOT transfer — the short e2e needs its
own dedicated collectible stub. The real end-to-end scenario lands in plan 05-03; the
stub loads no data.

Folder-derived ``e2e`` marker only (tests/conftest.py auto-applies it; no decorator —
``--strict-markers``). No ``backtesting``/``backtrader`` import (Pitfall 3).
"""

import pytest


def test_trailing_short_scenario():
    pytest.skip("Wave 0 stub — implemented in 05-03")
