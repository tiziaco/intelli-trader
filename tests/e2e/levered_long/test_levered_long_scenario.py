"""Wave 0 e2e stub for the levered-long scenario (Plan 06 builds the real scenario).

Collectible-but-skipped today so Plan 06's ``-k levered_long`` / ``-m e2e`` verify
target selects >=1 test before any RED->GREEN cycle (Nyquist Wave 0 contract).
"""

import pytest


def test_levered_long_scenario_wave0_stub():
    pytest.skip("Wave 0 stub — implemented in Phase 2 plan 06")
