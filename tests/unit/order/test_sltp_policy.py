"""
Plan 07-06: typed SLTPPolicy mechanics in the order layer (M5-06, D-13).

Covers the two engine-resolved SLTP kinds and their precedence rules:

* ``PercentFromDecision`` — children priced from the DECISION price at
  assembly time (signal.price ± pct), linked two-directionally.
* ``PercentFromFill`` — NO children at assembly; on the parent's EXECUTED
  fill the children are created, stored, linked and emitted priced from
  the ACTUAL fill price (RESEARCH Pattern 5 Option B, IB attached-order
  semantics — the documented carve-out to create-all-then-emit).
* Explicit ``stop_loss``/``take_profit`` levels WIN when both explicit
  levels and an SLTPPolicy are present (D-13 precedence).
* A parent REJECTED before any fill discards its pending-bracket entry —
  the children never exist (T-07-15; WR-05 untouched).

All expectations are hand-computed Decimals entered via string-path
literals (Pitfall 1). Entirely oracle-dark — the golden run carries no
brackets.
"""

from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import OrderStatus, OrderType, Side
from itrader.core.sizing import (
    FractionOfCash,
    PercentFromDecision,
    PercentFromFill,
    TradingDirection,
)
from tests.support.venue_wiring import backtest_portfolio_handler


_STRATEGY_ID = 1


class _SLTPHarness:
    """OrderHandler harness with a funded portfolio and an SLTP-aware signal factory."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = backtest_portfolio_handler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        self.last_ptf_id = self.ptf_handler.add_portfolio("test_ptf", "default", 10000)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=1.0, price=100.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
        sltp_policy=None,
    ):
        """A signal carrying an optional typed SLTPPolicy (D-13).

        Explicit ``stop_loss``/``take_profit`` default to 0 (absent) so the
        policy branch is exercised; pass both to assert explicit precedence.
        """
        return SignalEvent(
            time=datetime(2024, 1, 1),
            order_type=OrderType(order_type),
            ticker=ticker,
            action=Side(action),
            price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=_STRATEGY_ID,
            portfolio_id=self.last_ptf_id,
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
            sltp_policy=sltp_policy,
        )

    def drain_order_events(self):
        """Drain the queue, returning the OrderEvents in arrival order."""
        emitted = []
        while not self.queue.empty():
            ev = self.queue.get_nowait()
            if isinstance(ev, OrderEvent):
                emitted.append(ev)
        return emitted

    def fill(self, order_event, status="EXECUTED", price=None, time=None):
        """Drive a fill the canonical way: portfolio settles first (EXECUTED
        only), then the order mirror reconciles — exactly the FILL dispatch
        order of the event handler (the test_stop_limit_orders flow shape)."""
        fill = FillEvent.new_fill(
            status, order_event,
            price=price if price is not None else order_event.price,
            quantity=order_event.quantity,
            commission=0.0,
            time=time,
        )
        if status == "EXECUTED":
            self.ptf_handler.on_fill(fill)
        self.order_handler.on_fill(fill)
        return fill


@pytest.fixture
def harness():
    h = _SLTPHarness()
    yield h
    # Drain the queue after each test to prevent cross-test bleed.
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def test_percent_from_decision_prices_children_at_assembly(harness):
    """PercentFromDecision(sl 5%, tp 10%) BUY at 100: children created at
    assembly with stop 95 and limit 110 (Decimal-exact from the decision
    price), linked via parent_order_id/child_order_ids."""
    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, price=100.0,
        sltp_policy=PercentFromDecision(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
    )

    harness.order_handler.on_signal(signal)

    order_events = harness.drain_order_events()
    # All three legs emitted parent-first: MARKET, STOP (SL), LIMIT (TP).
    assert [e.order_type for e in order_events] == [
        OrderType.MARKET, OrderType.STOP, OrderType.LIMIT
    ]
    parent_event, sl_event, tp_event = order_events

    # Decision-price anchoring: 100 * (1 - 0.05) = 95, 100 * (1 + 0.10) = 110.
    assert sl_event.price == Decimal("95")
    assert tp_event.price == Decimal("110")
    # Children sell the long back (inverted action).
    assert sl_event.action is Side.SELL
    assert tp_event.action is Side.SELL

    # Two-directional linkage, identical to the explicit-levels path.
    assert sl_event.parent_order_id == parent_event.order_id
    assert tp_event.parent_order_id == parent_event.order_id
    assert set(parent_event.child_order_ids) == {sl_event.order_id, tp_event.order_id}

    # The stored entities carry the same linkage.
    stored_parent = harness.order_storage.get_order_by_id(
        parent_event.order_id, harness.last_ptf_id)
    assert set(stored_parent.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    for child_id in stored_parent.child_order_ids:
        child = harness.order_storage.get_order_by_id(child_id, harness.last_ptf_id)
        assert child.parent_order_id == stored_parent.id


def test_percent_from_fill_creates_children_at_parent_fill(harness):
    """PercentFromFill BUY: after on_signal storage holds ONLY the parent;
    after the parent's EXECUTED fill at 102, on_fill returns child
    OrderEvents priced 96.9 / 112.2 (Decimal-exact from the FILL price,
    not the decision price) and storage holds the linked children."""
    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, price=100.0,
        sltp_policy=PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
    )

    harness.order_handler.on_signal(signal)

    # Assembly emits ONLY the parent — the children do not exist yet
    # (the documented carve-out to create-all-then-emit, Pattern 5 Option B).
    order_events = harness.drain_order_events()
    assert len(order_events) == 1
    parent_event = order_events[0]
    assert parent_event.order_type == OrderType.MARKET
    assert parent_event.child_order_ids == ()
    stored = harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1

    # Parent EXECUTED at 102 — the fill anchor, not the decision price.
    harness.fill(parent_event, status="EXECUTED", price=Decimal("102"))

    # The handler enqueued the children returned by OrderManager.on_fill
    # (D-18: the manager never touches the queue).
    child_events = harness.drain_order_events()
    assert [e.order_type for e in child_events] == [OrderType.STOP, OrderType.LIMIT]
    sl_event, tp_event = child_events

    # Fill-price anchoring: 102 * (1 - 0.05) = 96.9, 102 * (1 + 0.10) = 112.2.
    assert sl_event.price == Decimal("96.9")
    assert tp_event.price == Decimal("112.2")
    assert sl_event.action is Side.SELL
    assert tp_event.action is Side.SELL
    assert sl_event.parent_order_id == parent_event.order_id
    assert tp_event.parent_order_id == parent_event.order_id

    # Storage now holds the linked children alongside the parent.
    stored = harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 3
    stored_parent = harness.order_storage.get_order_by_id(
        parent_event.order_id, harness.last_ptf_id)
    assert set(stored_parent.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    for child_id in stored_parent.child_order_ids:
        child = harness.order_storage.get_order_by_id(child_id, harness.last_ptf_id)
        assert child.parent_order_id == stored_parent.id
        assert child.status == OrderStatus.PENDING

    # The pending entry was consumed — a second fill cannot re-create children.
    assert harness.order_handler.order_manager._pending_brackets == {}


def test_explicit_levels_win_over_sltp_policy(harness):
    """Explicit sl/tp + sltp_policy both present: the children match the
    EXPLICIT levels — D-13 precedence (the policy is ignored entirely)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, price=100.0,
        stop_loss=90.0, take_profit=120.0,
        sltp_policy=PercentFromDecision(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
    )

    harness.order_handler.on_signal(signal)

    order_events = harness.drain_order_events()
    assert [e.order_type for e in order_events] == [
        OrderType.MARKET, OrderType.STOP, OrderType.LIMIT
    ]
    _, sl_event, tp_event = order_events
    # Explicit levels, NOT the policy's 95/110.
    assert sl_event.price == Decimal("90")
    assert tp_event.price == Decimal("120")


def test_explicit_levels_win_over_percent_from_fill(harness):
    """Explicit levels + PercentFromFill: children are created at assembly
    from the explicit levels and NO pending bracket is recorded."""
    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, price=100.0,
        stop_loss=90.0, take_profit=120.0,
        sltp_policy=PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
    )

    harness.order_handler.on_signal(signal)

    order_events = harness.drain_order_events()
    assert len(order_events) == 3
    _, sl_event, tp_event = order_events
    assert sl_event.price == Decimal("90")
    assert tp_event.price == Decimal("120")
    # Explicit precedence means the fill-time path is never armed.
    assert harness.order_handler.order_manager._pending_brackets == {}


def test_rejected_parent_discards_pending_bracket(harness):
    """Parent REFUSED before any fill: the pending-bracket entry is
    discarded — no children ever exist (T-07-15; WR-05 untouched)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=1.0, price=100.0,
        sltp_policy=PercentFromFill(sl_pct=Decimal("0.05"), tp_pct=Decimal("0.10")),
    )

    harness.order_handler.on_signal(signal)
    order_events = harness.drain_order_events()
    assert len(order_events) == 1
    parent_event = order_events[0]
    # The pending bracket is armed while the parent is in flight.
    assert parent_event.order_id in harness.order_handler.order_manager._pending_brackets

    # Exchange refuses the parent — terminal without any fill.
    harness.fill(parent_event, status="REFUSED")

    # No child OrderEvents were emitted; the pending entry is gone.
    assert harness.drain_order_events() == []
    assert harness.order_handler.order_manager._pending_brackets == {}

    # Storage holds ONLY the rejected parent — the children never existed.
    stored = harness.order_storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1
    rejected = stored[0]
    assert rejected.status == OrderStatus.REJECTED
    assert rejected.child_order_ids == []
