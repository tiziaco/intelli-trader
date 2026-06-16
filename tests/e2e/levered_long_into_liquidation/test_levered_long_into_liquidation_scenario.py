"""Leveraged-long-into-liquidation white-box e2e — Wave 0 stub.

================================ WAVE 0 STUB — NOT YET IMPLEMENTED ================================
A COLLECTIBLE skipped stub satisfying the Nyquist sampling contract: the
levered-long-into-liquidation e2e verify selector
(`poetry run pytest tests/e2e/levered_long_into_liquidation`) must resolve >=1 test BEFORE the
implementation RED step. The liquidation engine + this scenario's hand-computed assertions are
implemented in plan 04-04; the body is `pytest.skip(...)` until then.

This is a WHITE-BOX leaf mirroring `tests/e2e/levered_long/test_levered_long_scenario.py`
(NOT the `run_scenario`/`golden/` harness) — the load-bearing assertions will be liquidation
INTERNALS, threading the margin/leverage core (Phase 2/3) into the liquidation trigger (Phase 4).
Synthetic ticker `LIQUSD` (NEVER BTCUSD — the spot oracle must stay byte-exact,
134 / 46189.87730727451). Test-only change adds ZERO production code.
==================================================================================================

PLANNED HAND COMPUTATION (implemented in 04-04 — kept here so the leaf documents intent)
----------------------------------------------------------------------------------------
A leveraged long opened under the Phase-2 margin core (LeveredFraction sizing, admission
reservation = notional / L) is marked DOWN past its long liquidation price:

    long liq price = entry × (1 − 1/L + MMR) = 100 × (1 − 0.2 + 0.01) = 80.808080...

`bars.csv` drops the close to 90 (healthy) then 75 (breach on close). The leaf proves the
maintenance-margin breach check fires on the bar close (no mark feed on daily OHLCV — the honest
documented proxy), the forced close releases the locked margin, and the total loss is clamped at
the wallet balance so equity cannot drift impossibly negative.

Folder-derived `e2e` marker (tests/conftest.py applies it; no decorator). Must collect cleanly
under `filterwarnings=["error"]` — no `backtesting`/`backtrader` import.
"""

import pytest

_SKIP = "Wave 0 stub — implemented in 04-04"

# Synthetic ticker — NEVER BTCUSD, so the spot oracle (134 / 46189.87730727451) is untouchable.
_TICKER = "LIQUSD"


def test_levered_long_into_liquidation_scenario():
    """Leveraged-long-into-liquidation full run-path e2e (white-box). Hand-computed
    liquidation internals are asserted once in 04-04, then this leaf is parked (NOT a frozen
    golden — accounting-core re-baseline is the single owner-gated freeze at P4/XVAL-01)."""
    pytest.skip(_SKIP)
