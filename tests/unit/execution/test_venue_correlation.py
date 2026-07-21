"""Direct, socket-free unit suite for ``VenueCorrelationIndex`` (WR-05 R1/R2/R3).

``VenueCorrelationIndex`` lifts the OKX arm's insert-only venue-correlation state
(the three correlation maps + the late-fill buffer + the trade-id dedup set +
``_correlation_lock``) into one cohesive, unit-testable class so the WR-05
unbounded-growth vector can be closed and exercised WITHOUT a socket, an
``OkxExchange``, or a connector. Every test here constructs the index DIRECTLY.

Coverage (the seven WR-05 behaviors):
- R1 encapsulation — register -> resolve and adopt -> resolve round-trips.
- R3 bounded ring — ``mark_seen`` dedup + FIFO eviction past a small capacity.
- R2 release-on-terminal — a partial fill RETAINS the order's entries; fills
  summing to ``order.quantity`` self-release (resolve returns None, 0 entries);
  ``release`` drains buffered late fills BEFORE evicting (WR05-D3, no WR-02
  regression) and is idempotent on an unknown / already-released venue_id.

Folder-derived ``unit`` marker (no decorator). Decimal edge held (money is
``Decimal`` end-to-end). No new pytest marker, no watch-mode flags.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from itrader.core.enums import OrderCommand, OrderType, Side
from itrader.core.exceptions import ValidationError
from itrader.events_handler.events import OrderEvent
from itrader.execution_handler.exchanges.venue_correlation import (
    VenueCorrelationIndex,
    _extract_client_order_id,
)


def _make_order(
    *,
    quantity: Decimal = Decimal("0.5"),
    order_id: int = 1,
) -> OrderEvent:
    """Mirror ``test_okx_fill_idempotency.py::_make_order`` — a minimal OrderEvent."""
    return OrderEvent(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTC-USDT",
        action=Side.BUY,
        price=Decimal("42000.0"),
        quantity=quantity,
        exchange="okx",
        strategy_id=7,
        portfolio_id=3,
        order_type=OrderType.LIMIT,
        order_id=order_id,
        command=OrderCommand.NEW,
    )


# --- R1: register / adopt -> resolve round-trips -------------------------------


def test_register_then_resolve_returns_order() -> None:
    """Registering an OrderEvent by venue_id resolves it back from a streamed fill."""
    idx = VenueCorrelationIndex()
    order = _make_order(order_id=1)

    idx.register("OID-1", order, "it1")
    res = idx.resolve({"id": "T-1", "order": "OID-1", "amount": "0.2"})

    assert res.order is order
    assert res.venue_id == "OID-1"
    assert res.outcome == "emit"


def test_adopt_then_resolve_returns_order() -> None:
    """``adopt`` (restart rehydration) repopulates the maps so a fill resolves."""
    idx = VenueCorrelationIndex()
    order = _make_order(order_id=55)

    idx.adopt("OID-REHY", order, "it55")
    res = idx.resolve({"id": "T-9", "order": "OID-REHY", "amount": "0.5"})

    assert res.order is order
    assert res.venue_id == "OID-REHY"


# --- R3: mark_seen dedup + bounded ring ----------------------------------------


def test_mark_seen_reports_newly_seen_then_duplicate() -> None:
    """``mark_seen`` is an idempotent no-op on a re-send: first True, then False."""
    idx = VenueCorrelationIndex()

    assert idx.mark_seen("T-1") is True
    assert idx.mark_seen("T-1") is False


def test_resolve_dedups_an_already_seen_trade_id() -> None:
    """A trade id already marked seen resolves as a duplicate (no re-emit).

    WR-02: ``resolve`` no longer consumes the slot itself — the caller marks the dedup key
    seen only after a True ``_emit_fill``. So the second resolve dedups only AFTER the caller
    confirms the first emit via ``mark_seen(dedup_key)``.
    """
    idx = VenueCorrelationIndex()
    order = _make_order()
    idx.register("OID-1", order, "it1")

    first = idx.resolve({"id": "T-DUP", "order": "OID-1", "amount": "0.2"})
    assert first.outcome == "emit"
    # The caller consumes the slot after proving the fill emitted.
    idx.mark_seen(first.dedup_key)  # type: ignore[arg-type]

    second = idx.resolve({"id": "T-DUP", "order": "OID-1", "amount": "0.2"})
    assert second.outcome == "duplicate"
    assert second.order is None


def test_bounded_ring_evicts_oldest_id() -> None:
    """Inserting > capacity distinct ids keeps the dedup set <= capacity and evicts
    the OLDEST — its membership flips back to not-seen."""
    idx = VenueCorrelationIndex(capacity=3)

    for tid in ("t0", "t1", "t2"):
        assert idx.mark_seen(tid) is True
    assert idx.seen_count() == 3

    # A 4th distinct id evicts the oldest (t0) — size stays bounded.
    assert idx.mark_seen("t3") is True
    assert idx.seen_count() == 3

    # t0 was evicted: it is no longer deduped (membership flipped to not-seen).
    assert idx.mark_seen("t0") is True
    assert idx.seen_count() == 3


# --- D-16 WR-02: mark-seen ordering (slot consumed only after proven emit) ------


def test_resolve_does_not_mark_seen_until_caller_confirms_corrected_resend() -> None:
    """WR-02: ``resolve`` returns an ``emit`` verdict WITHOUT consuming the dedup slot —
    the slot is consumed only when the caller confirms a True ``_emit_fill`` via
    ``mark_seen(dedup_key)``. So a malformed-then-corrected re-send of the SAME
    ``{ticker}:{trade_id}`` is NOT silently dropped: a second ``resolve`` still emits
    until the caller marks the key seen."""
    idx = VenueCorrelationIndex()
    order = _make_order()
    idx.register("OID-1", order, "it1")

    first = idx.resolve({"id": "T-1", "order": "OID-1", "amount": "0.2"})
    assert first.outcome == "emit"
    # WR-02: the slot is NOT consumed by resolve (the caller emits first).
    assert idx.seen_count() == 0

    # A corrected re-send BEFORE the caller confirms the emit still resolves to emit
    # (the malformed first attempt did not burn the slot).
    second = idx.resolve({"id": "T-1", "order": "OID-1", "amount": "0.2"})
    assert second.outcome == "emit"
    assert second.dedup_key == "BTC-USDT:T-1"

    # Once the caller proves the fill emitted, it marks the slot seen; a later re-send dedups.
    idx.mark_seen(first.dedup_key)  # type: ignore[arg-type]
    third = idx.resolve({"id": "T-1", "order": "OID-1", "amount": "0.2"})
    assert third.outcome == "duplicate"
    assert third.order is None


# --- R2: release-on-terminal (drain-then-evict, partial vs full, idempotent) ----


def test_release_surfaces_buffered_fills_and_clears_them() -> None:
    """A fill buffered before correlation is SURFACED by ``release`` for emission
    (drain-before-evict, WR05-D3) and the pending buffer is cleared."""
    idx = VenueCorrelationIndex()
    buffered_fill = {"id": "T-1", "order": "OID-9", "amount": "0.5"}

    # Fill arrives before any correlation -> buffered, not emitted.
    res = idx.resolve(buffered_fill)
    assert res.outcome == "buffered"
    assert idx.pending_count("OID-9") == 1

    # release drains + returns the buffered fill so the caller can emit it, then clears.
    released_order, drained = idx.release("OID-9")
    assert drained == [buffered_fill]
    assert idx.pending_count("OID-9") == 0


def test_partial_fill_retains_entries_full_fill_self_releases() -> None:
    """A partial cumulative (< quantity) RETAINS the order's entries; fills summing
    to ``order.quantity`` report terminal and ``release`` drops them to 0 entries."""
    idx = VenueCorrelationIndex()
    order = _make_order(quantity=Decimal("0.5"))
    idx.register("OID-1", order, "it1")

    # Partial: cumulative 0.2 < 0.5 -> NOT terminal, entries retained.
    assert idx.record_fill("OID-1", order, Decimal("0.2")) is False
    assert idx.resolve({"id": "P-1", "order": "OID-1", "amount": "0.1"}).order is order
    assert len(idx) == 1

    # Remaining: cumulative 0.5 == 0.5 -> terminal; entries live until release.
    assert idx.record_fill("OID-1", order, Decimal("0.3")) is True
    assert len(idx) == 1

    released_order, _drained = idx.release("OID-1")
    assert released_order is order
    assert len(idx) == 0
    # After release the venue id resolves to no order (entries dropped).
    assert idx.resolve({"id": "P-2", "order": "OID-1", "amount": "0.1"}).order is None


def test_release_is_idempotent_on_unknown_venue_id() -> None:
    """Releasing an unknown / already-released venue_id is a harmless no-op."""
    idx = VenueCorrelationIndex()
    order = _make_order()
    idx.register("OID-1", order, "it1")

    first_order, first_drained = idx.release("OID-1")
    assert first_order is order
    assert first_drained == []
    assert len(idx) == 0

    # Second release of the now-gone venue id: no raise, empty drain, no order.
    second_order, second_drained = idx.release("OID-1")
    assert second_order is None
    assert second_drained == []

    # An entirely unknown venue id is likewise a clean no-op.
    unknown_order, unknown_drained = idx.release("NEVER-SEEN")
    assert unknown_order is None
    assert unknown_drained == []


# --- D-16 WR-01: release_pending pairs register_pending on submit failure --------


def test_release_pending_removes_leaked_correlation() -> None:
    """WR-01: ``release_pending`` is the paired inverse of ``register_pending`` — it drops
    the pre-correlation clOrdId entry so a failed submit does not leak it. Idempotent."""
    idx = VenueCorrelationIndex()
    order = _make_order()

    idx.register_pending("cid-1", order)
    assert idx.resolve({"id": "T-1", "clientOrderId": "cid-1", "amount": "0.1"}).order is order

    idx.release_pending("cid-1")
    # The pending correlation is gone — a fill echoing the clOrdId no longer resolves.
    res = idx.resolve({"id": "T-2", "clientOrderId": "cid-1", "amount": "0.1"})
    assert res.order is None
    assert res.outcome == "uncorrelated"

    # Idempotent on an unknown / already-released clOrdId.
    idx.release_pending("never-registered")


# --- D-16 IN-01: reject capacity < 1 at construction ----------------------------


def test_capacity_below_one_is_rejected() -> None:
    """IN-01: a dedup-ring capacity < 1 is a construction error (the ring must hold >= 1)."""
    with pytest.raises(ValidationError):
        VenueCorrelationIndex(capacity=0)
    with pytest.raises(ValidationError):
        VenueCorrelationIndex(capacity=-5)
    # capacity == 1 is the accepted boundary.
    assert VenueCorrelationIndex(capacity=1).seen_count() == 0


# --- D-16 / MPORT-04: the venue-vocabulary seam ---------------------------------


def test_extract_client_order_id_prefers_the_top_level_ccxt_spelling() -> None:
    """ccxt surfaces the echoed client order id as top-level ``clientOrderId``.

    Characterization of the existing helper: this behavior predates the D-16 rename and is
    asserted here so the rename cannot silently change what the seam reads off the wire.
    """
    assert _extract_client_order_id({"clientOrderId": "it7"}) == "it7"
    # The top level WINS over the nested venue spelling when both are present.
    assert _extract_client_order_id(
        {"clientOrderId": "it-top", "info": {"clOrdId": "it-nested"}}) == "it-top"


def test_extract_client_order_id_falls_back_to_the_nested_venue_spelling() -> None:
    """A trade carrying ONLY the venue's nested spelling still resolves (D-16).

    ``info["clOrdId"]`` is OKX's own field name and ``info["clientOrderId"]`` is the
    ccxt-normalized nested form. Both are WIRE vocabulary and must keep working verbatim —
    the D-16 rename touches engine identifiers only, never what the venue echoes back.
    """
    assert _extract_client_order_id({"info": {"clOrdId": "it42"}}) == "it42"
    assert _extract_client_order_id({"info": {"clientOrderId": "it43"}}) == "it43"
    # OKX's own spelling wins over the nested ccxt alias when both are present.
    assert _extract_client_order_id(
        {"info": {"clOrdId": "it-okx", "clientOrderId": "it-ccxt"}}) == "it-okx"


def test_extract_client_order_id_returns_none_for_every_degenerate_shape() -> None:
    """T-11-07: venue trade dicts are UNTRUSTED input — every degenerate shape returns
    ``None`` (never a raise, never an empty string) so the caller falls through to the
    buffer path instead of correlating a fill to the wrong order."""
    # Not a dict at all.
    assert _extract_client_order_id(None) is None
    assert _extract_client_order_id("not-a-dict") is None
    assert _extract_client_order_id(["not", "a", "dict"]) is None
    # A dict carrying neither field.
    assert _extract_client_order_id({}) is None
    assert _extract_client_order_id({"id": "T-1", "order": "OID-1"}) is None
    # A dict whose ``info`` is not a dict (venue-supplied shape drift).
    assert _extract_client_order_id({"info": "not-a-dict"}) is None
    assert _extract_client_order_id({"info": None}) is None
    assert _extract_client_order_id({"info": ["clOrdId"]}) is None
    # A field that is PRESENT but falsy — an empty clOrdId correlates nothing.
    assert _extract_client_order_id({"clientOrderId": ""}) is None
    assert _extract_client_order_id({"info": {"clOrdId": ""}}) is None


def test_registration_lands_in_the_renamed_client_order_id_map() -> None:
    """D-16 / LR-19: the engine-side map is ``_orders_by_client_order_id`` — no engine
    identifier spells the venue's ``clOrdId`` field name. Registering an order then
    resolving it by client order id returns the SAME OrderEvent under the renamed map."""
    idx = VenueCorrelationIndex()
    order = _make_order(order_id=11)

    idx.register_pending("it11", order)
    assert idx._orders_by_client_order_id["it11"] is order

    # The renamed map is what the resolve path actually consults.
    res = idx.resolve({"id": "T-1", "clientOrderId": "it11", "amount": "0.1"})
    assert res.order is order
    assert res.outcome == "emit"


def test_release_drops_the_renamed_client_order_id_map_entry() -> None:
    """R2 bound under the renamed identifiers: ``release`` still drops the client-order-id
    map entry (and its venue-id link), so a terminalized order leaves no residue.

    Mirrors the REAL submit sequence in ``OkxExchange._submit_order``: ``register_pending``
    writes ``_orders_by_client_order_id`` BEFORE the create_order RPC, then ``register``
    writes the venue-id maps + the ``_client_order_id_by_venue_id`` link once the RPC returns.
    ``register`` alone does NOT populate the client-order-id map — only ``register_pending``
    and ``adopt`` do — so both calls are required to set up the release bound.
    """
    idx = VenueCorrelationIndex()
    order = _make_order(order_id=12)

    idx.register_pending("it12", order)
    idx.register("OID-12", order, "it12")
    assert idx._orders_by_client_order_id["it12"] is order
    assert idx._client_order_id_by_venue_id["OID-12"] == "it12"

    released_order, _drained = idx.release("OID-12")
    assert released_order is order
    # Both renamed maps are empty — the R2 bound holds.
    assert idx._orders_by_client_order_id == {}
    assert idx._client_order_id_by_venue_id == {}


# --- D-16: bound + alarm the uncorrelated-fill buffer ---------------------------


def test_uncorrelated_buffer_is_bounded_and_alarms(caplog: pytest.LogCaptureFixture) -> None:
    """A flood of external (unknown venue id) fills cannot grow ``_pending_fills_by_venue_id``
    without limit: the total buffered fills stay bounded and a WARNING alarms on eviction."""
    idx = VenueCorrelationIndex(pending_buffer_max=3)

    with caplog.at_level(logging.WARNING):
        for i in range(6):
            res = idx.resolve({"id": f"T-{i}", "order": f"EXT-{i}", "amount": "0.1"})
            assert res.outcome == "buffered"

    # Bounded: the total number of buffered fills never exceeds the cap.
    total = sum(idx.pending_count(f"EXT-{i}") for i in range(6))
    assert total <= 3

    # Alarmed: at least one WARNING fired on eviction.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when the uncorrelated-fill buffer overflows"
