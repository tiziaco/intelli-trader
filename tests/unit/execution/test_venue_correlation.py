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

from datetime import datetime, timezone
from decimal import Decimal

from itrader.core.enums import OrderCommand, OrderType, Side
from itrader.events_handler.events import OrderEvent
from itrader.execution_handler.exchanges.venue_correlation import VenueCorrelationIndex


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
    """A trade id already marked seen resolves as a duplicate (no re-emit)."""
    idx = VenueCorrelationIndex()
    order = _make_order()
    idx.register("OID-1", order, "it1")

    first = idx.resolve({"id": "T-DUP", "order": "OID-1", "amount": "0.2"})
    second = idx.resolve({"id": "T-DUP", "order": "OID-1", "amount": "0.2"})

    assert first.outcome == "emit"
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
