"""Liquidation formula / breach / penalty / cap (LIQ-01, LIQ-02) — Wave 0 stubs.

================================ WAVE 0 STUB — NOT YET IMPLEMENTED ================================
These are COLLECTIBLE skipped stubs satisfying the Nyquist sampling contract: every
Phase-4 liquidation unit verify selector (`-k`/file path) must resolve >=1 test BEFORE
the implementation RED step. The liquidation engine itself is implemented in plan 04-03;
each test below is bodied with `pytest.skip(...)` until then.

This file adds ZERO production code — it is a test-only change, so the SMA_MACD spot
oracle stays byte-exact (D-11, 134 / 46189.87730727451) and no behavior changes.

Selectors these stubs satisfy (04-VALIDATION Per-Task Verification Map):
* `poetry run pytest tests/unit/portfolio/test_liquidation.py`  (LIQ-01 formula/breach/floor)
* `poetry run pytest -k "multi_breach_deterministic"`           (LIQ-01 multi-breach order)
* `poetry run pytest -k "liquidation_penalty"`                  (LIQ-02 penalty + cap)
==================================================================================================

Folder-derived `unit` marker (tests/conftest.py applies it; no decorator here). Must
collect cleanly under `filterwarnings=["error"]` / `--strict-markers` — no reference-engine
import (NEVER `backtesting`/`backtrader`).
"""

from decimal import Decimal

import pytest

# Worked liquidation scenario (Entry=100, size=200, leverage L=5, MMR=0.01), shared by
# the unit stubs and the e2e leaves. Documented here so the downstream implementation
# (04-03) and the e2e leaves (04-04) reference one source of truth.
#   long  liq price = entry × (1 − 1/L + MMR) = 100 × (1 − 0.2 + 0.01) = 80.80808...
#   short liq price = entry × (1 + 1/L − MMR) = 100 × (1 + 0.2 − 0.01) = 118.81188...
_ENTRY = Decimal("100")
_LEVERAGE = Decimal("5")
_MMR = Decimal("0.01")

_SKIP = "Wave 0 stub — implemented in 04-03"


def test_isolated_liq_price_long():
    """LIQ-01: isolated-margin long liquidation price = entry × (1 − 1/L + MMR).

    For entry=100, L=5, MMR=0.01 the long liq price ≈ Decimal("80.808...").
    """
    pytest.skip(_SKIP)


def test_isolated_liq_price_short():
    """LIQ-01: isolated-margin short liquidation price = entry × (1 + 1/L − MMR).

    For entry=100, L=5, MMR=0.01 the short liq price ≈ Decimal("118.811...").
    """
    pytest.skip(_SKIP)


def test_liquidation_breach_detected_on_bar_close():
    """LIQ-01: maintenance-margin breach is detected on the bar CLOSE mark (no mark
    feed on daily OHLCV — the honest documented proxy)."""
    pytest.skip(_SKIP)


def test_liquidation_penalty():
    """LIQ-02: penalty = liquidation_fee_rate × |size| × liq_price (rides the existing
    commission/fee field; no new FillStatus)."""
    pytest.skip(_SKIP)


def test_liquidation_loss_capped_at_wb():
    """LIQ-02: the explicit `min(realized_loss + penalty, WB)` clamp triggers with a
    FAT liquidation fee (not only the MMR=0 degenerate case) — equity can never be
    driven impossibly negative (closes DEF-01-C)."""
    pytest.skip(_SKIP)


def test_multi_breach_deterministic():
    """LIQ-01: simultaneous multi-position breaches are liquidated in a FIXED
    symbol-then-open-time order → byte-identical double-run (determinism)."""
    pytest.skip(_SKIP)
