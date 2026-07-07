"""``Universe`` readiness + keep-until-flat lifecycle (Plan 07-02, WR-01/WR-02).

Exercises the D-02/D-13/D-14/D-15 contract against the REAL ``Universe.apply``
-> ``TrackedInstrument`` record path (closing the "hand-built event" gap the
06-REVIEW flagged): the single ``_entries: dict[str, TrackedInstrument]`` record
map replaces the desync-prone ``_instruments`` + ``_leaving`` pair.

- Construction-time members default ``Readiness.READY`` — the oracle-inertness
  lever (backtest members carry store data, RESEARCH Pitfall 2), so the WR-02
  strategy readiness gate is a no-op on the SMA_MACD oracle path.
- ``apply`` adding a NEW symbol creates a ``PENDING`` record (untradeable until
  warmup marks it ``READY``); ``apply`` REMOVING a symbol does NOT drop the
  record (WR-01 keep-until-flat) — only ``_members`` shrinks.
- ``discard_instrument`` is the single atomic three-field teardown (D-13).
- Re-add of a still-held (leaving) symbol clears ``leaving`` and KEEPS its
  readiness — no re-warmup (D-14).
"""

from decimal import Decimal

import pytest

from itrader.core.enums import Readiness
from itrader.core.instrument import Instrument
from itrader.universe import Universe

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


# --- construction-time READY (oracle-inertness lever) ----------------------


def test_construction_members_default_ready() -> None:
    """Every construction-time member is READY so the readiness gate is a no-op
    on the backtest oracle path (RESEARCH Pitfall 2)."""
    universe = _universe("A", "B")
    assert universe.is_ready("A") is True
    assert universe.is_ready("B") is True


# --- apply-added symbol is PENDING (WR-02 warmup gate) ---------------------


def test_apply_added_symbol_is_pending_until_marked_ready() -> None:
    """A freshly apply-added symbol lands PENDING — not tradeable until warmed."""
    universe = _universe("A")
    universe.apply({"A", "B"}, instruments={"B": _inst("B")})
    assert universe.is_ready("B") is False


def test_mark_ready_and_mark_failed_flip_readiness() -> None:
    """mark_ready flips PENDING->READY; mark_failed flips PENDING->FAILED
    (is_ready stays False on FAILED)."""
    universe = _universe("A")
    universe.apply({"A", "B", "C"}, instruments={"B": _inst("B"), "C": _inst("C")})
    assert universe.is_ready("B") is False

    universe.mark_ready("B")
    assert universe.is_ready("B") is True

    universe.mark_failed("C")
    assert universe.is_ready("C") is False


# --- WR-01 keep-until-flat (apply does not drop the record) -----------------


def test_apply_remove_keeps_record_only_members_shrinks() -> None:
    """apply REMOVING a symbol does NOT drop its record (WR-01 keep-until-flat):
    instrument(sym) still resolves AND the readiness record survives; only the
    membership list shrinks."""
    universe = _universe("A", "B")
    universe.mark_ready("A")

    delta = universe.apply({"B"})
    assert delta.removed == ("A",)
    assert universe.members == ["B"]  # membership shrank
    # The record survives — no KeyError, readiness intact (keep-until-flat).
    assert universe.instrument("A").symbol == "A"
    assert universe.is_ready("A") is True


# --- D-14 re-add of a still-held (leaving) symbol keeps readiness -----------


def test_readd_of_held_leaving_symbol_clears_leaving_keeps_ready() -> None:
    """Re-add of a still-held leaving symbol clears leaving and KEEPS its
    existing readiness — no re-warmup (D-14)."""
    universe = _universe("A", "B")  # both READY at construction
    universe.apply({"B"})           # remove A (record survives, keep-until-flat)
    universe.mark_leaving("A")
    assert "A" in universe.leaving_symbols()

    # Re-add the still-held symbol: leaving cleared, readiness preserved (READY).
    delta = universe.apply({"A", "B"})
    assert delta.added == ("A",)
    assert "A" not in universe.leaving_symbols()
    assert universe.is_ready("A") is True  # NOT re-warmed to PENDING


def test_readd_of_discarded_symbol_is_fresh_pending() -> None:
    """A fully discard_instrument'd symbol re-adds as a fresh PENDING record
    (D-14) — the teardown fully forgot it, so warmup restarts."""
    universe = _universe("A", "B")
    universe.apply({"B"})            # remove A (record survives)
    universe.discard_instrument("A")  # fully tear the record down

    delta = universe.apply({"A", "B"})
    assert delta.added == ("A",)
    assert universe.is_ready("A") is False  # fresh PENDING, must re-warm


# --- D-13 discard_instrument = single atomic three-field teardown -----------


def test_discard_instrument_removes_record_entirely() -> None:
    """discard_instrument removes the whole record in one pop — instrument,
    readiness, and leaving all gone (D-13 atomic three-field teardown)."""
    universe = _universe("A", "B")
    universe.mark_leaving("A")

    universe.discard_instrument("A")

    with pytest.raises(KeyError):
        universe.instrument("A")            # instrument gone
    assert universe.is_ready("A") is False  # readiness gone (absent -> False)
    assert "A" not in universe.leaving_symbols()  # leaving gone


# --- CR-02 FAILED-retry accessors (mark_pending + failed_symbols) -----------


def test_mark_pending_flips_failed_back_to_pending() -> None:
    """mark_pending flips a FAILED record back to PENDING (CR-02 retry seam):
    is_ready stays False (PENDING is not READY) but the record is no longer FAILED,
    so the next warmup can drive it to READY."""
    universe = _universe("A")
    universe.apply({"A", "B"}, instruments={"B": _inst("B")})
    universe.mark_failed("B")
    assert universe.failed_symbols() == {"B"}

    universe.mark_pending("B")
    assert universe.is_ready("B") is False           # PENDING is still not tradeable
    assert universe.failed_symbols() == set()        # no longer FAILED
    assert universe._entries["B"].readiness is Readiness.PENDING


def test_failed_symbols_lists_only_failed_records() -> None:
    """failed_symbols() returns exactly the FAILED-readiness members (mirrors
    leaving_symbols) — READY/PENDING members are excluded."""
    universe = _universe("A")  # READY at construction
    universe.apply(
        {"A", "B", "C"}, instruments={"B": _inst("B"), "C": _inst("C")}
    )  # B, C PENDING
    assert universe.failed_symbols() == set()

    universe.mark_failed("B")
    assert universe.failed_symbols() == {"B"}        # only the FAILED one
    universe.mark_ready("C")
    assert universe.failed_symbols() == {"B"}        # READY C excluded


# --- D-15 leaving surface operates through the record, orthogonal to readiness


def test_leaving_surface_is_orthogonal_to_readiness() -> None:
    """mark_leaving/leaving_symbols/clear_leaving operate through the record
    (D-15) and do NOT touch readiness."""
    universe = _universe("A")  # READY at construction
    assert universe.leaving_symbols() == set()

    universe.mark_leaving("A")
    assert universe.leaving_symbols() == {"A"}
    assert universe.is_ready("A") is True  # readiness untouched by leaving

    universe.clear_leaving("A")
    assert universe.leaving_symbols() == set()
    assert universe.is_ready("A") is True
