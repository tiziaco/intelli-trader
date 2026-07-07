"""``Universe.apply`` / ``UniverseDelta`` / leaving-set surface (Plan 06-01 Task 2).

The dynamic-universe mutation seam (D-03). ``Universe.apply(desired)`` diffs the
desired symbol set against current membership, returns a ``UniverseDelta``, and
mutates ``_members`` IN PLACE (slice-assign — the feed holds the list by
identity, Pitfall 4). The empty-delta fast path returns WITHOUT touching state
(oracle-dark: single-symbol SMA_MACD yields ``desired == current``). A
leaving-set surface (mark/read/clear) backs the later remove-policy admission
gate.

``Universe`` stays connector-free (D-03): the poll handler resolves precision
from the venue markets map and passes an ``instruments`` map into ``apply``; a
missing entry falls back to the ``instruments.py`` ``_DEFAULT_*`` ladder (paper).
"""

from decimal import Decimal

import pytest

from itrader.core.instrument import Instrument
from itrader.universe import Universe
from itrader.universe.universe import UniverseDelta

pytestmark = pytest.mark.unit


def _inst(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        price_precision=Decimal("0.01"),
        quantity_precision=Decimal("0.00000001"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=Decimal("1"),
    )


def _universe(*symbols: str) -> Universe:
    members = sorted(symbols)
    instruments = {s: _inst(s) for s in members}
    return Universe(members=members, instrument_map=instruments)


# --- empty-delta fast path (oracle-dark) ----------------------------------


def test_apply_unchanged_returns_empty_delta_without_mutation():
    universe = _universe("A")
    before = universe.members
    before_id = id(universe.members)
    delta = universe.apply({"A"})
    assert delta.is_empty()
    assert delta.added == ()
    assert delta.removed == ()
    # No mutation on the fast path — same object, same contents.
    assert id(universe.members) == before_id
    assert universe.members == before == ["A"]


def test_universe_delta_is_empty():
    assert UniverseDelta(added=(), removed=()).is_empty() is True
    assert UniverseDelta(added=("X",), removed=()).is_empty() is False
    assert UniverseDelta(added=(), removed=("Y",)).is_empty() is False


# --- add / remove -----------------------------------------------------------


def test_apply_adds_symbol():
    universe = _universe("A")
    delta = universe.apply({"A", "B"}, instruments={"B": _inst("B")})
    assert delta.added == ("B",)
    assert delta.removed == ()
    assert universe.members == ["A", "B"]  # sorted (WR-05)
    assert universe.instrument("B").symbol == "B"


def test_apply_removes_symbol():
    universe = _universe("A", "B")
    delta = universe.apply({"B"})
    assert delta.added == ()
    assert delta.removed == ("A",)
    assert universe.members == ["B"]
    # WR-01 keep-until-flat (Plan 07-02, D-13): apply no longer drops the record
    # — only membership shrinks. The removed symbol's record survives (so a
    # still-held orphan never KeyErrors) until discard_instrument tears it down.
    assert universe.instrument("A").symbol == "A"
    universe.discard_instrument("A")
    with pytest.raises(KeyError):
        universe.instrument("A")  # gone after the atomic teardown


def test_apply_adds_and_removes_together():
    universe = _universe("A", "B")
    delta = universe.apply({"B", "C"}, instruments={"C": _inst("C")})
    assert delta.added == ("C",)
    assert delta.removed == ("A",)
    assert universe.members == ["B", "C"]


# --- identity preservation (Pitfall 4) -------------------------------------


def test_apply_preserves_members_list_identity():
    universe = _universe("A", "B")
    held = universe.members  # the object the feed binds by identity
    held_id = id(held)
    universe.apply({"B", "C"}, instruments={"C": _inst("C")})
    # Same list object after an apply that both adds AND removes.
    assert id(universe.members) == held_id
    assert universe.members is held
    assert held == ["B", "C"]


# --- added-symbol Instrument fallback (default ladder) ---------------------


def test_apply_added_symbol_falls_back_to_default_ladder():
    universe = _universe("A")
    # No instruments map passed -> default-ladder Instrument, never a KeyError.
    delta = universe.apply({"A", "Z"})
    assert delta.added == ("Z",)
    inst = universe.instrument("Z")
    assert inst.symbol == "Z"
    assert inst.price_precision == Decimal("0.01")       # _DEFAULT_PRICE_SCALE
    assert inst.quantity_precision == Decimal("0.00000001")  # _DEFAULT_QUANTITY_SCALE


# --- leaving-set surface ---------------------------------------------------


def test_leaving_set_starts_empty():
    universe = _universe("A")
    assert universe.leaving_symbols() == set()


def test_mark_and_clear_leaving():
    universe = _universe("A", "B")
    universe.mark_leaving("A")
    assert universe.leaving_symbols() == {"A"}
    universe.clear_leaving("A")
    assert universe.leaving_symbols() == set()


def test_leaving_symbols_returns_a_copy():
    universe = _universe("A")
    universe.mark_leaving("A")
    snapshot = universe.leaving_symbols()
    snapshot.add("MUTANT")
    # Caller mutation must not corrupt internal state.
    assert universe.leaving_symbols() == {"A"}
