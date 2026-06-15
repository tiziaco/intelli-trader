"""PARKED short-with-carry e2e (SHORT-03 / CARRY-01) — Phase 3 Wave 0 scaffold.

================================ PARKED — NOT A GOLDEN ================================
This is a collectible RED placeholder seeded by Plan 03-02 (the Nyquist contract,
D-10). The scenario itself — a multi-bar HELD short accruing per-bar
BORROW_INTEREST debits before the cover — is AUTHORED + HAND-VERIFIED in Plan 03-06
Task 2.

When authored, EVERY asserted number will be a HAND-COMPUTED literal with the
arithmetic shown inline (mirroring tests/e2e/levered_long/), including each per-bar
carry debit. The scenario uses a SYNTHETIC instrument, NEVER BTCUSD — the SMA_MACD
spot oracle (134 / 46189.87730727451) must stay byte-exact and cannot be touched by
this file. It drives the engine's real SIGNAL -> ORDER -> FILL -> PORTFOLIO path and
asserts on margin / cash / carry INTERNALS. It does NOT use the golden-diff harness
and is NOT frozen as a golden here: the single owner-gated re-baseline is at Phase 4 /
XVAL-01 (cross-validation + owner sign-off). No `--freeze`.
=====================================================================================

This stub asserts NOTHING yet — Plan 03-06 turns it green. Folder-derived `e2e` marker
only (tests/conftest.py applies it; no decorator here).
"""

import pytest


def test_short_carry_scenario_parked():
    """PARKED short-with-carry (held short with per-bar BORROW_INTEREST debits).

    Authored + hand-verified in Plan 03-06; frozen as golden ONLY at Phase 4 /
    XVAL-01 under cross-validation + owner sign-off (D-10). No `--freeze`.
    """
    pytest.skip(
        "Phase 3 parked e2e — implemented + hand-verified in plan 03-06; "
        "frozen only at P4/XVAL-01"
    )
