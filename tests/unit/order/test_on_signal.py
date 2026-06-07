from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.events import OrderEvent, SignalEvent
from itrader.core.enums import OrderType, OrderStatus, Side
from itrader.core.sizing import FractionOfCash, TradingDirection


_STRATEGY_ID = 1


class _OnSignalHarness:
    """OrderHandler harness with a single funded portfolio and a signal factory."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.order_storage = OrderStorageFactory.create("test")
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.order_storage)
        # One portfolio per harness instance (per-test, like the legacy setUp).
        self.last_ptf_id = self.ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)

    def create_mock_signal(
        self, action, ticker="BTCUSDT", quantity=100.0, price=40.0,
        order_type="MARKET", stop_loss=0.0, take_profit=0.0,
    ):
        """Create a mock signal with proper quantity for testing."""
        return SignalEvent(
            time=datetime.now(),
            order_type=OrderType(order_type),
            ticker=ticker,
            action=Side(action),
            price=price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=_STRATEGY_ID,
            portfolio_id=self.last_ptf_id,
            # Typed policy defaults mirror the golden declarations (D-01/D-03):
            # the order manager does not read these fields yet (07-05 wires them).
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
            allow_increase=False,
        )


@pytest.fixture
def harness():
    h = _OnSignalHarness()
    yield h
    # Drain the queue after each test to prevent cross-test bleed.
    while not h.queue.empty():
        try:
            h.queue.get_nowait()
        except Exception:
            break


def test_on_signal_buy(harness):
    buy_signal = harness.create_mock_signal("BUY", quantity=100.0, price=40.0)

    harness.order_handler.on_signal(buy_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action is Side.BUY
    assert order_event.quantity == 100.0


def test_on_signal_sell(harness):
    sell_signal = harness.create_mock_signal("SELL", quantity=50.0, price=40.0)

    harness.order_handler.on_signal(sell_signal)

    order_event: OrderEvent = harness.queue.get(False)

    assert isinstance(order_event, OrderEvent)
    assert order_event.ticker == "BTCUSDT"
    assert order_event.action is Side.SELL
    assert order_event.quantity == 50.0


def test_on_signal_buy_with_sl_tp(harness):
    buy_signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(buy_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action is Side.BUY
    assert primary_event.quantity == 100.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending


def test_on_signal_sell_with_sl_tp(harness):
    sell_signal = harness.create_mock_signal(
        "SELL", quantity=50.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(sell_signal)

    # Drain all 3 order events: MARKET (primary) + STOP (SL) + LIMIT (TP)
    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in emitted if isinstance(e, OrderEvent) and e.type.name == "ORDER"
    ]
    # Find the primary MARKET order event
    primary_event = next(e for e in order_events if e.order_type == OrderType.MARKET)
    pending_orders = harness.order_storage.get_pending_orders()
    portfolio_orders = pending_orders.get(primary_event.portfolio_id, {})

    assert primary_event.ticker == "BTCUSDT"
    assert primary_event.action is Side.SELL
    assert primary_event.quantity == 50.0
    # All 3 legs emitted
    assert len(order_events) == 3
    # All 3 orders remain pending (market order is filled by execution handler, not self-filled)
    assert isinstance(pending_orders, dict)
    assert len(portfolio_orders) == 3  # MARKET, SL and TP orders all pending


def test_rejected_signal_persists_audited_rejected_order(harness):
    """A signal failing validation leaves exactly one stored REJECTED order (D-13).

    The rejection is an audited FIX/Nautilus-style state change — it transitions
    the PENDING entity to REJECTED through add_state_change (triggered_by
    "validator", event-derived timestamp) and persists it; nothing is emitted.
    """
    # cost = 100 * 200 = 20000 > 10000 portfolio cash → INSUFFICIENT_CASH_COST.
    # SL/TP set: rejection must short-circuit BEFORE any child entity is built.
    signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=200.0, stop_loss=180.0, take_profit=220.0
    )

    harness.order_handler.on_signal(signal)

    # No OrderEvent reaches the execution handler
    assert harness.queue.empty()

    storage = harness.order_storage
    # Exactly one stored order for the ticker — the rejected primary; the
    # bracket children were never created (create-all-then-emit only runs
    # after acceptance).
    stored = storage.get_orders_by_ticker("BTCUSDT", harness.last_ptf_id)
    assert len(stored) == 1
    rejected = stored[0]
    assert rejected.status == OrderStatus.REJECTED
    # Rejected orders never enter the active book
    assert storage.get_active_orders(harness.last_ptf_id) == []

    # Audited state change: PENDING → REJECTED, by the validator, stamped with
    # the signal's event time — never the wall clock (M2-09).
    last_change = rejected.get_latest_state_change()
    assert last_change.from_status == OrderStatus.PENDING
    assert last_change.to_status == OrderStatus.REJECTED
    assert last_change.triggered_by == "validator"
    assert last_change.timestamp == signal.time


def test_bracket_two_directional_linkage_and_parent_first_emission(harness):
    """Brackets carry two-directional linkage and are emitted parent-first (D-11)."""
    signal = harness.create_mock_signal(
        "BUY", quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0
    )

    harness.order_handler.on_signal(signal)

    emitted = [harness.queue.get(False) for _ in range(harness.queue.qsize())]
    order_events = [e for e in emitted if isinstance(e, OrderEvent)]
    assert len(order_events) == 3

    # Parent-first queue order: primary MARKET, then stop-loss STOP, then
    # take-profit LIMIT — identical to the pre-D-11 emit-per-creation sequence.
    assert [e.order_type for e in order_events] == [
        OrderType.MARKET, OrderType.STOP, OrderType.LIMIT
    ]

    parent_event, sl_event, tp_event = order_events
    # Children carry parent_order_id
    assert sl_event.parent_order_id == parent_event.order_id
    assert tp_event.parent_order_id == parent_event.order_id
    # The parent event carries both child ids (populated BEFORE emission)
    assert set(parent_event.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    # Non-bracket children carry the empty tuple
    assert sl_event.child_order_ids == ()
    assert tp_event.child_order_ids == ()

    # The stored entities carry the same two-directional linkage
    storage = harness.order_storage
    stored_parent = storage.get_order_by_id(parent_event.order_id, harness.last_ptf_id)
    assert set(stored_parent.child_order_ids) == {sl_event.order_id, tp_event.order_id}
    for child_id in stored_parent.child_order_ids:
        child = storage.get_order_by_id(child_id, harness.last_ptf_id)
        assert child.parent_order_id == stored_parent.id
