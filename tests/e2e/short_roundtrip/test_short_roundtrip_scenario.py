"""PARKED pure-short round-trip e2e (SHORT-03) — Phase 3 Wave 0 scaffold.

================================ PARKED — NOT A GOLDEN ================================
This is a collectible RED placeholder seeded by Plan 03-02 (the Nyquist contract,
D-10). The scenario itself — a pure SHORT round-trip: SELL-to-open then BUY-to-cover
back to flat — is AUTHORED + HAND-VERIFIED in Plan 03-06 Task 2.

When authored, EVERY asserted number will be a HAND-COMPUTED literal with the
arithmetic shown inline (mirroring tests/e2e/levered_long/). The scenario uses a
SYNTHETIC instrument, NEVER BTCUSD — the SMA_MACD spot oracle (134 /
46189.87730727451) must stay byte-exact and cannot be touched by this file. It drives
the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path and asserts on margin /
cash / position INTERNALS. It does NOT use the golden-diff harness and is NOT frozen
as a golden here: the single owner-gated re-baseline is at Phase 4 / XVAL-01
(cross-validation + owner sign-off). No `--freeze`.
=====================================================================================

This stub asserts NOTHING yet — Plan 03-06 turns it green. Folder-derived `e2e` marker
only (tests/conftest.py applies it; no decorator here).
"""

import pytest


def test_short_roundtrip_scenario_parked():
    """PARKED pure-short round-trip (SELL-to-open -> BUY-to-cover -> flat).

    Authored + hand-verified in Plan 03-06; frozen as golden ONLY at Phase 4 /
    XVAL-01 under cross-validation + owner sign-off (D-10). No `--freeze`.
    """
    pytest.skip(
        "Phase 3 parked e2e — implemented + hand-verified in plan 03-06; "
        "frozen only at P4/XVAL-01"
    )
