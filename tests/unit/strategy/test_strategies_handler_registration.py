"""Strategy registration gate (SHORT-01) — Phase 3 Wave 0 scaffold.

Collectible RED placeholder seeded by Plan 03-02 (the Nyquist contract, D-10):
the Plan 03-03 verify selector `short_registration` must select >=1 test BEFORE
any production code is written, so a downstream `<automated>` verify can never
select zero tests and report a silent green.

SHORT-01: a non-LONG_ONLY strategy is admitted only under BOTH the shorts-enabled
flags (two-flag gate). Default-off keeps SMA_MACD byte-exact. This stub asserts
NOTHING yet — Plan 03-03 turns it green. Folder-derived `unit` marker only
(tests/conftest.py applies it; no decorator here).
"""

import pytest


def test_short_registration_stub():
    """SHORT-01: two-flag registration gate for non-LONG_ONLY strategies.

    Plan 03-03 implements the assertion (admitted only under both flags).
    """
    pytest.skip("Phase 3 Wave 0 stub — implemented in plan 03-03")
