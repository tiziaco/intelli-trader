"""Wave 0 scaffold for the centralized money policy (M2-02).

These tests lock the contracts the money module (Task 3 of this plan) must
satisfy:

1. ``to_money`` enters Decimal via ``Decimal(str(x))`` so a binary float like
   ``10.1`` yields the exact ``Decimal("10.1")`` (D-04 — never ``Decimal(float)``,
   which would carry the float-repr artifact).
2. ``quantize`` applies the per-instrument scale with ``ROUND_HALF_UP`` at the
   money boundary: USD cash quantizes to 2dp (``Decimal("1.005")`` -> ``1.01``,
   D-03), BTC quantity quantizes to 8dp.

They are EXPECTED to fail (red) until Task 3 creates ``itrader/core/money.py``.
The module itself must import and collect cleanly (no syntax error, no
collection error) — only the import/assertions are allowed to fail.

This scaffold is co-located here (in the plan that builds ``core/money.py``)
rather than in Plan 01, so no same-wave plan verifies against a scaffold another
same-wave plan creates. It carries an explicit module-level ``pytestmark`` so
``--strict-markers`` is satisfied regardless of conftest ordering.
"""

from decimal import Decimal

import pytest

from itrader.core.instrument import Instrument
from itrader.core.money import quantize, to_money

pytestmark = pytest.mark.unit

# A BTCUSD-like Instrument (8dp price/quantity scales) reproducing the deleted
# _INSTRUMENT_SCALES["BTCUSD"] entry, and a default-precision Instrument standing
# in for the former "UNKNOWN" string -> default-scale fallback case.
_BTCUSD = Instrument(
    symbol="BTCUSD",
    price_precision=Decimal("0.00000001"),
    quantity_precision=Decimal("0.00000001"),
    maintenance_margin_rate=Decimal("0.005"),
    max_leverage=Decimal("10"),
)
_DEFAULT_INSTRUMENT = Instrument(
    symbol="DEFAULT",
    price_precision=Decimal("0.01"),
    quantity_precision=Decimal("0.00000001"),
    maintenance_margin_rate=Decimal("0.005"),
    max_leverage=Decimal("10"),
)


def test_to_money_uses_str_path():
    # D-04: Decimal(str(10.1)) == Decimal("10.1"); Decimal(10.1) would NOT.
    assert to_money(10.1) == Decimal("10.1")


def test_to_money_accepts_int_str_decimal():
    assert to_money(5) == Decimal("5")
    assert to_money("3.14") == Decimal("3.14")
    assert to_money(Decimal("2.5")) == Decimal("2.5")


def test_quantize_cash_half_up_2dp():
    # D-03: USD cash scale is 2dp, ROUND_HALF_UP -> 1.005 rounds up to 1.01.
    assert quantize(Decimal("1.005"), _BTCUSD, "cash") == Decimal("1.01")


def test_quantize_quantity_btc_8dp_half_up():
    # BTC quantity scale is 8dp (read off the Instrument), ROUND_HALF_UP.
    assert quantize(Decimal("0.123456785"), _BTCUSD, "quantity") == Decimal(
        "0.12345679"
    )


def test_quantize_default_instrument_uses_default_scale():
    # A default-precision Instrument -> the default cash scale (2dp).
    assert quantize(Decimal("1.005"), _DEFAULT_INSTRUMENT, "cash") == Decimal("1.01")
