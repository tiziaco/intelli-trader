"""Unit tests for the frozen ``Instrument`` value object (INST-01/INST-03).

These tests lock the contracts ``itrader/core/instrument.py`` must satisfy:

1. ``Instrument`` is a frozen value object (mirrors ``core/bar.py::Bar``) —
   assigning to any field after construction raises (D-04 immutability).
2. Precision is stored as the **Decimal scale** directly (Pitfall 3 / A1): a
   BTCUSD-like instrument carries ``price_precision == Decimal("0.00000001")``
   (8dp) byte-identical to the deleted ``_INSTRUMENT_SCALES["BTCUSD"]`` entry.
3. ``min_order_size`` defaults to ``None`` (D-01a — undeclared falls through to
   the venue ``ExchangeLimits`` fallback) and round-trips a declared Decimal.
4. The INST-03 margin fields (``maintenance_margin_rate``, ``max_leverage``,
   ``settles_funding``) land inert now for downstream phases; ``settles_funding``
   defaults to ``False`` and ``quote_currency`` defaults to ``"USD"``.

They carry an explicit module-level ``pytestmark`` so ``--strict-markers`` is
satisfied regardless of conftest ordering (mirrors ``test_money.py:29``).
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from itrader.core.instrument import Instrument

pytestmark = pytest.mark.unit


def _btcusd() -> Instrument:
    """A fully-declared BTCUSD-like Instrument (8dp price/quantity scales)."""
    return Instrument(
        symbol="BTCUSD",
        price_precision=Decimal("0.00000001"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("10"),
    )


def test_instrument_is_frozen():
    # D-04: a frozen dataclass rejects post-construction field assignment.
    instrument = _btcusd()
    with pytest.raises(FrozenInstanceError):
        instrument.symbol = "ETHUSD"  # type: ignore[misc]


def test_btcusd_scales_are_byte_exact_8dp():
    # INST-01 / Pitfall 3: the stored scales reproduce the deleted
    # _INSTRUMENT_SCALES["BTCUSD"] entry byte-for-byte (8dp Decimal scale).
    instrument = _btcusd()
    assert instrument.price_precision == Decimal("0.00000001")
    assert instrument.quantity_precision == Decimal("0.00000001")


def test_scale_decimal_choice_reproduces_deleted_table_entry():
    # Pitfall 3 guard: storing the Decimal scale directly (vs an int
    # place-count) is byte-identical to the deleted table literal.
    instrument = _btcusd()
    assert instrument.price_precision == Decimal(1).scaleb(-8)
    assert str(instrument.price_precision) == "1E-8"


def test_min_order_size_defaults_to_none():
    # D-01a: undeclared min_order_size is None so the exchange falls through
    # to the venue ExchangeLimits fallback (keeps the BTCUSD oracle byte-exact).
    instrument = _btcusd()
    assert instrument.min_order_size is None


def test_min_order_size_round_trips_declared_decimal():
    instrument = Instrument(
        symbol="ETHUSD",
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.0001"),
        min_order_size=Decimal("0.001"),
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=Decimal("5"),
    )
    assert instrument.min_order_size == Decimal("0.001")


def test_margin_fields_present_and_settable():
    # INST-03: margin params land inert now for Phase 2/4 consumers.
    instrument = Instrument(
        symbol="BTCUSD",
        price_precision=Decimal("0.00000001"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("10"),
    )
    assert instrument.maintenance_margin_rate == Decimal("0.005")
    assert instrument.max_leverage == Decimal("10")


def test_settles_funding_defaults_to_false():
    # INST-03: funding is a flag, default False (Phase B deferred / inert).
    assert _btcusd().settles_funding is False


def test_quote_currency_defaults_to_usd():
    # Source of the kind="cash" 2dp scale.
    assert _btcusd().quote_currency == "USD"


def test_borrow_rate_defaults_to_decimal_zero():
    # D-01 / Pitfall 3: undeclared borrow_rate defaults to Decimal("0")
    # (carry-off) so SMA_MACD stays oracle byte-exact.
    instrument = _btcusd()
    assert instrument.borrow_rate == Decimal("0")
    # MUST be a Decimal, never the literal int 0 (int re-enters int arithmetic
    # and fails mypy --strict in the Plan-05 carry formula).
    assert isinstance(instrument.borrow_rate, Decimal)


def test_borrow_rate_round_trips_declared_decimal():
    # D-01: a per-symbol borrow rate stores the Decimal value unchanged.
    instrument = Instrument(
        symbol="BTCUSD",
        price_precision=Decimal("0.00000001"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("10"),
        borrow_rate=Decimal("0.10"),
    )
    assert instrument.borrow_rate == Decimal("0.10")
    assert isinstance(instrument.borrow_rate, Decimal)
