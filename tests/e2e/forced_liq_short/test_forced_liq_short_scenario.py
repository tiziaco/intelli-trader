"""Forced-liquidation SHORT white-box e2e — Wave 0 stub.

================================ WAVE 0 STUB — NOT YET IMPLEMENTED ================================
A COLLECTIBLE skipped stub satisfying the Nyquist sampling contract: the forced-liq-short
e2e verify selector (`poetry run pytest tests/e2e/forced_liq_short`) must resolve >=1 test
BEFORE the implementation RED step. The liquidation engine + this scenario's hand-computed
assertions are implemented in plan 04-04; the body is `pytest.skip(...)` until then.

This is a WHITE-BOX leaf mirroring `tests/e2e/levered_long/test_levered_long_scenario.py`
(NOT the `run_scenario`/`golden/` harness) — the load-bearing assertions will be liquidation
INTERNALS. Synthetic ticker `LIQUSD` (NEVER BTCUSD — the spot oracle must stay byte-exact,
134 / 46189.87730727451). Test-only change adds ZERO production code.
==================================================================================================

PLANNED HAND COMPUTATION (implemented in 04-04 — kept here so the leaf documents intent)
----------------------------------------------------------------------------------------
A leveraged short (Entry=100, size=200, leverage L=5, MMR=0.01) is marked adverse (UP) until
the bar CLOSE crosses the corrected short liquidation price:

    short liq price = entry × (1 + 1/L − MMR) = 100 × (1 + 0.2 − 0.01) = 118.811881...

`bars.csv` raises the close to 110 (still healthy) then 125 (ABOVE 118.811 → breach on close).
At the breach bar the engine mints an admission-bypassing forced-cover order tagged
`OrderTriggerSource.LIQUIDATION`, reconciles EXECUTED → FILLED (no new FillStatus), books the
penalty on the commission field, and clamps the total loss at the wallet balance.

Folder-derived `e2e` marker (tests/conftest.py applies it; no decorator). Must collect cleanly
under `filterwarnings=["error"]` — no `backtesting`/`backtrader` import.
"""

import pytest

_SKIP = "Wave 0 stub — implemented in 04-04"

# Synthetic ticker — NEVER BTCUSD, so the spot oracle (134 / 46189.87730727451) is untouchable.
_TICKER = "LIQUSD"


def test_forced_liq_short_scenario():
    """Forced-liquidation SHORT full run-path e2e (white-box). Hand-computed liquidation
    internals are asserted once in 04-04, then this leaf is parked (NOT a frozen golden)."""
    pytest.skip(_SKIP)
