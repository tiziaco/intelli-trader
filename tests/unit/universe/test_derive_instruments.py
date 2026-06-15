"""INST-02 — ``derive_instruments`` precision ladder coverage (Plan 01-02, D-03/D-07/D-09/D-10).

``derive_instruments`` is the pure derive-once sibling of ``derive_membership``:
for each member symbol it builds an ``Instrument`` via the precision ladder
(D-09): ``price_precision = declared -> inferred(guarded, string-read, 8dp cap)
-> default``; ``quantity_precision = declared -> default`` (NOT inferable, D-10);
``min_order_size = declared -> None`` (D-01a, NOT inferable); margin params =
declared -> default.

The byte-exact discipline (Plan 01-03) rests on two guards proven here:

1. BTCUSD ALWAYS takes the DECLARED 8dp branch (D-10) — inference never runs on
   the oracle symbol. Covered by ``test_btcusd_takes_declared_8dp`` +
   ``test_btcusd_min_order_size_undeclared``.
2. Inference (INST-02) reads the RAW CSV string (not the float64 frame, Pitfall 1)
   and CAPS at 8 decimal places — covered on a SYNTHETIC non-oracle symbol only.
"""

from decimal import Decimal

import pytest

from itrader.core.instrument import Instrument
from itrader.universe import derive_instruments

pytestmark = pytest.mark.unit


class StrategyStub:
    """Minimal strategy shape: only the ``tickers`` attribute matters."""

    def __init__(self, tickers):
        self.tickers = tickers


# -- Declared wins (D-10): BTCUSD never infers ------------------------------

def test_btcusd_takes_declared_8dp():
    """BTCUSD resolves to the DECLARED 8dp scale from the in-code table —
    inference is NOT consulted (D-10). The price_data deliberately carries a
    2dp BTCUSD cell that would infer 2dp if inference ran; declared wins."""
    instruments = derive_instruments(
        [StrategyStub(["BTCUSD"])],
        screener_tickers=(),
        price_data={"BTCUSD": ["6543.21"]},  # 2dp — would drift the oracle if inferred
    )
    inst = instruments["BTCUSD"]
    assert inst.price_precision == Decimal("0.00000001")
    assert inst.quantity_precision == Decimal("0.00000001")


def test_btcusd_min_order_size_undeclared():
    """BTCUSD leaves min_order_size UNDECLARED (None, D-01a) so the exchange
    falls through to ExchangeLimits(0.001) — the oracle-protecting fallback."""
    instruments = derive_instruments(
        [StrategyStub(["BTCUSD"])], screener_tickers=(), price_data={})
    assert instruments["BTCUSD"].min_order_size is None


# -- Inferred (INST-02) on a SYNTHETIC non-oracle symbol --------------------

def test_inferred_price_precision_counts_decimal_places():
    """A non-oracle symbol with a raw price cell '0.00012345' infers
    price_precision counting 8 decimal places (Decimal('0.00000001'))."""
    instruments = derive_instruments(
        [StrategyStub(["DOGEUSD"])],
        screener_tickers=(),
        price_data={"DOGEUSD": ["0.00012345"]},
    )
    # 8 decimal places -> scale 1e-8
    assert instruments["DOGEUSD"].price_precision == Decimal("0.00000001")


def test_inferred_price_precision_counts_fewer_places():
    """A cell with 3 decimal places infers a 3dp scale (Decimal('0.001'))."""
    instruments = derive_instruments(
        [StrategyStub(["FOOUSD"])],
        screener_tickers=(),
        price_data={"FOOUSD": ["12.345"]},
    )
    assert instruments["FOOUSD"].price_precision == Decimal("0.001")


def test_inferred_price_precision_caps_at_8dp():
    """A cell with MORE than 8 decimal places is CAPPED at 8dp (crypto max)."""
    instruments = derive_instruments(
        [StrategyStub(["TINYUSD"])],
        screener_tickers=(),
        price_data={"TINYUSD": ["0.0001234567890123"]},  # 16 dp
    )
    assert instruments["TINYUSD"].price_precision == Decimal("0.00000001")


def test_inference_reads_string_not_float():
    """Inference reads the RAW CSV string, not the float64 frame (Pitfall 1).

    A value like '0.000000010' carries a trailing-zero decimal count of 9 in
    the string; under float coercion ``float('0.000000010')`` -> ``1e-08`` and
    ``str(1e-08)`` loses the explicit places. Reading the string and capping at
    8 still infers correctly (8dp), proving the string path is used."""
    instruments = derive_instruments(
        [StrategyStub(["STRUSD"])],
        screener_tickers=(),
        price_data={"STRUSD": ["0.000000010"]},  # 9 raw dp -> capped to 8
    )
    assert instruments["STRUSD"].price_precision == Decimal("0.00000001")


def test_inference_takes_max_decimal_places_across_cells():
    """When several raw cells are given, inference takes the MAX decimal count
    (the finest resolution the data exhibits), capped at 8dp."""
    instruments = derive_instruments(
        [StrategyStub(["BARUSD"])],
        screener_tickers=(),
        price_data={"BARUSD": ["12.3", "12.34", "12.3456"]},
    )
    assert instruments["BARUSD"].price_precision == Decimal("0.0001")


# -- Default fallback (D-09): no declared entry, no price data --------------

def test_default_fallback_when_no_declared_and_no_price_data():
    """A symbol with no declared entry and no price data resolves price to the
    default 2dp (Decimal('0.01')); quantity to default 8dp (NOT inferable,
    D-10); min_order_size to None."""
    instruments = derive_instruments(
        [StrategyStub(["NEWUSD"])], screener_tickers=(), price_data={})
    inst = instruments["NEWUSD"]
    assert inst.price_precision == Decimal("0.01")
    assert inst.quantity_precision == Decimal("0.00000001")
    assert inst.min_order_size is None


def test_quantity_precision_never_inferred():
    """Quantity precision is declared-or-default ONLY (D-10) — it is never
    inferred from price data even when price IS inferred."""
    instruments = derive_instruments(
        [StrategyStub(["QTYUSD"])],
        screener_tickers=(),
        price_data={"QTYUSD": ["1.23456"]},  # price infers 5dp
    )
    inst = instruments["QTYUSD"]
    assert inst.price_precision == Decimal("0.00001")
    assert inst.quantity_precision == Decimal("0.00000001")  # default, NOT 5dp


# -- Shape / coverage -------------------------------------------------------

def test_returns_instrument_per_member_symbol():
    """Every member symbol (union of strategy + screener tickers) gets an
    Instrument; the result is keyed by symbol."""
    instruments = derive_instruments(
        [StrategyStub(["BTCUSD"]), StrategyStub([("ETHUSD", "SOLUSD")])],
        screener_tickers=["ADAUSD"],
        price_data={},
    )
    assert set(instruments) == {"BTCUSD", "ETHUSD", "SOLUSD", "ADAUSD"}
    for inst in instruments.values():
        assert isinstance(inst, Instrument)


def test_margin_fields_present_and_typed():
    """The inert INST-03 margin fields land present + Decimal-typed on every
    derived Instrument (defaults this phase; consumed in later phases)."""
    instruments = derive_instruments(
        [StrategyStub(["BTCUSD"])], screener_tickers=(), price_data={})
    inst = instruments["BTCUSD"]
    assert isinstance(inst.maintenance_margin_rate, Decimal)
    assert isinstance(inst.max_leverage, Decimal)
    assert inst.settles_funding is False
