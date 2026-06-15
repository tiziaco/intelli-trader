"""INST-03 — SimulatedExchange min_order_size Instrument-first resolution (Plan 01-02, D-01/D-01a).

The exchange resolves the effective ``min_order_size`` Instrument-first ->
``ExchangeLimits`` fallback:

    effective_min = instrument.min_order_size
                    if instrument.min_order_size is not None
                    else self.config.limits.min_order_size

``ExchangeLimits.min_order_size`` is reframed (value UNCHANGED, ``Decimal("0.001")``)
as the venue-level fallback for undeclared symbols (D-01). Three behaviors are
pinned:

* an ``Instrument`` with ``min_order_size=None`` resolves to ``ExchangeLimits(0.001)``;
* an ``Instrument`` with a DECLARED ``min_order_size`` resolves to that value;
* BTCUSD (undeclared, D-01a) resolves to ``Decimal("0.001")`` — the
  oracle-protecting fallback that keeps admission byte-identical (Pitfall 2).

When NO universe is injected (the byte-exact default), the venue fallback is used
unconditionally — every pre-existing exchange test keeps its old behavior.
"""

from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.instrument import Instrument
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.universe import Universe, derive_instruments, derive_membership

pytestmark = pytest.mark.unit


def _instrument(symbol: str, min_order_size: Decimal | None) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.00000001"),
        quantity_precision=Decimal("0.00000001"),
        min_order_size=min_order_size,
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _exchange(universe: Universe | None = None) -> SimulatedExchange:
    exchange = SimulatedExchange(Queue())
    if universe is not None:
        exchange.set_universe(universe)
    return exchange


def _universe(symbol: str, instrument: Instrument) -> Universe:
    return Universe(members=[symbol], instrument_map={symbol: instrument})


def test_instrument_none_resolves_to_venue_fallback():
    """An Instrument with min_order_size=None -> ExchangeLimits(0.001)."""
    inst = _instrument("FOOUSD", None)
    exchange = _exchange(_universe("FOOUSD", inst))
    assert exchange.resolve_min_order_size("FOOUSD") == Decimal("0.001")


def test_declared_instrument_min_order_size_wins():
    """An Instrument with a DECLARED min_order_size resolves to that value."""
    inst = _instrument("BARUSD", Decimal("5.0"))
    exchange = _exchange(_universe("BARUSD", inst))
    assert exchange.resolve_min_order_size("BARUSD") == Decimal("5.0")


def test_btcusd_resolves_to_oracle_protecting_fallback():
    """BTCUSD (undeclared min_order_size, D-01a) resolves to Decimal('0.001') —
    byte-identical to the venue fallback read today (Pitfall 2)."""

    class _Strat:
        tickers = ["BTCUSD"]

    members = derive_membership([_Strat()])
    instruments = derive_instruments([_Strat()], price_data={})
    universe = Universe(members=members, instrument_map=instruments)
    exchange = _exchange(universe)
    assert instruments["BTCUSD"].min_order_size is None
    assert exchange.resolve_min_order_size("BTCUSD") == Decimal("0.001")


def test_no_universe_uses_venue_fallback_unconditionally():
    """With NO universe injected (byte-exact default), resolution returns the
    venue fallback for any symbol — pre-existing tests keep their behavior."""
    exchange = _exchange(universe=None)
    assert exchange.resolve_min_order_size("ANYUSD") == Decimal("0.001")


def test_symbol_not_in_universe_uses_venue_fallback():
    """A symbol absent from the injected universe falls back to the venue min
    (the universe resolves only its own members; a non-member is venue-default)."""
    inst = _instrument("FOOUSD", Decimal("9.0"))
    exchange = _exchange(_universe("FOOUSD", inst))
    assert exchange.resolve_min_order_size("OTHERUSD") == Decimal("0.001")
