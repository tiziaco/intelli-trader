"""Universe facade coverage (Plan 01-02, D-06/D-07, Pitfall 4).

``Universe`` is a thin read-model facade COMPOSING the already-computed
``membership`` list + the ``derive_instruments`` map — it does NOT recompute
membership (D-07). Two behaviors are pinned:

* ``.members`` returns the SAME set-derived ``list[str]`` it was constructed
  with — byte-exact, so ``feed.bind`` stays byte-identical (Pitfall 4).
* ``.instrument(symbol)`` looks up the injected Instrument map.
"""

from decimal import Decimal

import pytest

from itrader.core.instrument import Instrument
from itrader.universe import Universe, derive_instruments, derive_membership

pytestmark = pytest.mark.unit


class StrategyStub:
    def __init__(self, tickers):
        self.tickers = tickers


def _build(strategies, screener_tickers=(), price_data=None):
    membership = derive_membership(strategies, screener_tickers)
    instruments = derive_instruments(
        strategies, screener_tickers, price_data=price_data or {})
    return Universe(members=membership, instrument_map=instruments), membership


def test_members_returns_the_same_membership_list_byte_exact():
    """Universe.members returns EXACTLY the list derive_membership(...) returns
    for the same inputs (Pitfall 4 — feed.bind must stay byte-identical)."""
    strategies = [StrategyStub(["BTCUSD"]), StrategyStub([("ETHUSD", "SOLUSD")])]
    universe, membership = _build(strategies, screener_tickers=["ADAUSD"])
    assert universe.members == membership


def test_members_preserves_list_identity():
    """The .members list IS the constructed list (same object identity) — no
    copy/reorder is interposed between membership-derive and feed.bind."""
    membership = derive_membership([StrategyStub(["BTCUSD"])])
    instruments = derive_instruments([StrategyStub(["BTCUSD"])], (), price_data={})
    universe = Universe(members=membership, instrument_map=instruments)
    assert universe.members is membership


def test_instrument_round_trip():
    """Universe.instrument(symbol) returns the resolved Instrument from the
    injected map."""
    universe, _ = _build([StrategyStub(["BTCUSD"])])
    inst = universe.instrument("BTCUSD")
    assert isinstance(inst, Instrument)
    assert inst.symbol == "BTCUSD"
    assert inst.price_precision == Decimal("0.00000001")


def test_instrument_unknown_symbol_raises_keyerror():
    """An unknown symbol raises KeyError (defined behavior: the universe only
    resolves its own members)."""
    universe, _ = _build([StrategyStub(["BTCUSD"])])
    with pytest.raises(KeyError):
        universe.instrument("NOPEUSD")
