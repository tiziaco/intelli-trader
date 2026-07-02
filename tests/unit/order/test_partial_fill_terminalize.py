"""Partial-fill accumulation + terminalization in ``ReconcileManager`` (RECON-02, D-12/D-13).

The order mirror was built for one clean simulated fill; a live venue delivers the order
in PIECES. These tests pin the partial-aware reconcile against a REAL ``Order`` (so
``add_fill`` / ``add_state_change`` enforce the real full-quantity + transition contracts):

1. Two partials summing to quantity -> the mirror accumulates to PARTIALLY_FILLED on the
   first increment (staying OPEN, reservation HELD) then terminalizes to FILLED on the
   completing increment (reservation released exactly once).
2. A partial then a venue CANCEL -> the mirror terminalizes to CANCELLED KEEPING the
   accumulated fills (the position already reflects them, D-12) — not an error/halt, and
   NOT an orphaned-child cancel (there IS a real position to protect).
3. An over-fill (increment > remaining) is rejected-and-logged: the mirror is left
   unchanged and the reservation HELD — never a crash, never a terminalize-on-bad-fill.

Plus the byte-exact single-full-fill path (the simulated arm) still terminalizes to FILLED
in one shot, and no engine-imposed timeout ages a long-open partial (D-13 — aging is a
strategy concern, kept out of the reconcile core).

Driven against lightweight fakes for storage/portfolio/brackets (mirrors
``test_reconcile_manager.py``) so the assertions isolate the accumulation/terminalization
logic. Folder-derived ``unit`` marker (no decorator).
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from itrader.core.enums import FillStatus, OrderStatus, Side
from itrader.order_handler.order import Order
from itrader.order_handler.reconcile.reconcile_manager import ReconcileManager


# --- helpers / fakes --------------------------------------------------------


def _make_order(quantity: str = "1.0") -> Order:
    """A REAL PENDING limit order — the mirror the reconcile accumulates against."""
    return Order.new_limit_order(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ticker="BTCUSDT",
        action=Side.BUY,
        price="42000",
        quantity=quantity,
        exchange="okx",
        strategy_id=7,
        portfolio_id=3,
    )


class _FakeStorage:
    """Returns the single real order and records update_order calls."""

    def __init__(self, order: Order) -> None:
        self._order = order
        self.update_calls = 0

    def get_order_by_id(self, order_id, portfolio_id=None):
        return self._order

    def update_order(self, order):
        self.update_calls += 1
        return True

    def get_active_orders(self, portfolio_id):
        return []


class _FakeBrackets:
    """consume() returns None — no pending bracket (no fill-anchored children)."""

    def consume(self, order_id):
        return None


class _RecordingPortfolio:
    """Records release() calls; get_position() reports flat (no OVERSELL path)."""

    def __init__(self) -> None:
        self.release_calls = []

    def release(self, portfolio_id, order_id):
        self.release_calls.append((portfolio_id, order_id))

    def get_position(self, portfolio_id, ticker):
        return None


class _FakeFill:
    """Minimal fill carrying only the attributes on_fill reads (the increment lives
    in ``quantity`` — each venue trade reports the amount THAT fill filled)."""

    def __init__(self, status, order: Order, quantity: str, *,
                 price: str = "42000", ticker: str = "BTCUSDT") -> None:
        self.status = status
        self.order_id = order.id
        self.portfolio_id = order.portfolio_id
        self.ticker = ticker
        self.quantity = Decimal(quantity)
        self.price = Decimal(price)
        self.time = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_manager(order: Order, portfolio, storage=None) -> ReconcileManager:
    return ReconcileManager(
        order_storage=storage if storage is not None else _FakeStorage(order),
        logger=Mock(),
        portfolio_handler=portfolio,
        brackets=_FakeBrackets(),
        bracket_manager=Mock(),
        cancel_order=Mock(),
    )


# --- (1) two partials accumulate -> PARTIALLY_FILLED then FILLED -------------


def test_two_partials_accumulate_then_fill():
    """A first increment (< qty) stays OPEN at PARTIALLY_FILLED with the reservation
    HELD; the completing increment terminalizes to FILLED, releasing exactly once."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    storage = _FakeStorage(order)
    manager = _make_manager(order, portfolio, storage=storage)

    # First partial: 0.4 of 1.0 -> PARTIALLY_FILLED, stays open.
    out1 = manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.4"))
    assert out1 == []
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("0.4")
    # D-12: a partial does NOT release the reservation — the order is still working.
    assert portfolio.release_calls == []
    # D-13: the partial mirror is persisted (cumulative-filled restart cross-check).
    assert storage.update_calls == 1

    # Completing fill: remaining 0.6 -> FILLED.
    out2 = manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.6"))
    assert out2 == []
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == Decimal("1.0")
    # Now terminal -> released exactly once.
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]
    assert storage.update_calls == 2


def test_three_partials_accumulate_then_fill():
    """Three increments (two PARTIALLY_FILLED -> PARTIALLY_FILLED, then FILLED)."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.3"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.3"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("0.6")
    assert portfolio.release_calls == []   # still HELD across both partials

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.4"))
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == Decimal("1.0")
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]


# --- (2) partial then venue cancel -> CANCELLED, fills retained --------------


def test_partial_then_cancel_terminalizes_cancelled_keeping_fills():
    """A partial then a venue CANCEL terminalizes to CANCELLED, KEEPING the accrued
    fills (the position already reflects them, D-12) — not an error, not an orphan
    cancel (there is a real position)."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.4"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("0.4")
    assert portfolio.release_calls == []

    # The venue cancels the remainder.
    out = manager.on_fill(_FakeFill(FillStatus.CANCELLED, order, "0"))
    assert order.status == OrderStatus.CANCELLED
    # Fills RETAINED — the 0.4 already settled to the position.
    assert order.filled_quantity == Decimal("0.4")
    # A terminal cancel releases the (remaining) reservation exactly once.
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]
    # No orphaned-child cancels emitted (no brackets, and filled_quantity > 0 so the
    # WR-05 terminal-without-fill path never triggers).
    assert out == []


# --- (3) over-fill is rejected/logged, never crashes -------------------------


def test_overfill_is_rejected_not_crashed():
    """An increment larger than the whole order is rejected-and-logged: the mirror is
    left unchanged, the reservation HELD, no crash."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    storage = _FakeStorage(order)
    manager = _make_manager(order, portfolio, storage=storage)

    out = manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "1.5"))

    assert out == []
    # Mirror unchanged — never terminalized on a bad fill.
    assert order.status == OrderStatus.PENDING
    assert order.filled_quantity == Decimal("0")
    # Not terminal -> reservation HELD, mirror not persisted.
    assert portfolio.release_calls == []
    assert storage.update_calls == 0


def test_overfill_after_partial_is_rejected_partial_kept():
    """An over-fill that overshoots the REMAINING quantity after a partial is rejected;
    the earlier partial is retained and the order stays PARTIALLY_FILLED (still open)."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.6"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("0.6")

    # Remaining is 0.4; an 0.9 increment overshoots -> rejected, partial kept.
    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "0.9"))
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("0.6")
    assert portfolio.release_calls == []


# --- byte-exact single full fill still terminalizes FILLED -------------------


def test_single_full_fill_terminalizes_filled():
    """The simulated single-fill path is untouched: one full-quantity fill goes
    straight to FILLED and releases once (no PARTIALLY_FILLED intermediate)."""
    order = _make_order(quantity="1.0")
    portfolio = _RecordingPortfolio()
    manager = _make_manager(order, portfolio)

    manager.on_fill(_FakeFill(FillStatus.EXECUTED, order, "1.0"))

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == Decimal("1.0")
    assert portfolio.release_calls == [(order.portfolio_id, order.id)]
