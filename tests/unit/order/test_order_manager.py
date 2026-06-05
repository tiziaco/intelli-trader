"""
Test suite for OrderManager - Internal order orchestration engine.

Tests the OrderManager's functionality including:
- Market-driven order processing
- Stop/Limit order trigger evaluation
- Market order execution timing
- Order fill processing
- State management and event generation
"""

import datetime as _dt
from datetime import datetime
from queue import Queue
from unittest.mock import Mock

import pytest

from itrader.order_handler.order_manager import OrderManager
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.order import Order
from itrader.order_handler.storage import OrderStorageFactory
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.events import SignalEvent, OrderEvent, FillEvent
from itrader.core.enums import OrderType, OrderCommand, OrderStatus, Side


# --- OrderManager initialization -------------------------------------------


def test_order_manager_initialization():
    """Test OrderManager initialization."""
    order_storage = InMemoryOrderStorage()
    logger = Mock()
    order_handler_ref = Mock()

    order_manager_immediate = OrderManager(
        order_storage, logger, order_handler_ref, market_execution="immediate"
    )
    order_manager_next_bar = OrderManager(
        order_storage, logger, order_handler_ref, market_execution="next_bar"
    )

    assert order_manager_immediate.market_execution == "immediate"
    assert order_manager_next_bar.market_execution == "next_bar"
    assert order_manager_immediate.order_storage == order_storage
    assert order_manager_immediate.logger == logger


# --- shared handler harness -------------------------------------------------


class _Harness:
    """OrderHandler + storage + one funded portfolio."""

    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
        self.portfolio_id = self.ptf_handler.add_portfolio(1, "p", "default", 100000)

    def signal(self, stop_loss=0.0, take_profit=0.0):
        return SignalEvent(
            time=_dt.datetime(2024, 1, 1), order_type=OrderType.MARKET,
            ticker="BTCUSDT", action=Side.BUY, price=40.0, quantity=1.0,
            stop_loss=stop_loss, take_profit=take_profit, strategy_id=1,
            portfolio_id=self.portfolio_id, strategy_setting={},
        )

    def rest_a_stop(self):
        order = Order.new_stop_order(
            time=_dt.datetime(2024, 1, 1), ticker="BTCUSDT",
            action="SELL", price=30.0, quantity=1.0, exchange="default",
            strategy_id=1, portfolio_id=self.portfolio_id,
        )
        self.storage.add_order(order)
        return order

    def fill(self, order, status):
        oe = OrderEvent(
            time=_dt.datetime(2024, 1, 1), ticker=order.ticker, action=Side(order.action),
            price=float(order.price), quantity=float(order.quantity), exchange=order.exchange,
            strategy_id=order.strategy_id, portfolio_id=order.portfolio_id,
            order_type=OrderType.STOP, order_id=order.id,
        )
        return FillEvent.new_fill(status, oe, price=oe.price, quantity=oe.quantity, commission=0.0)


@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


# --- bracket emission -------------------------------------------------------


def test_bracket_legs_emitted_and_linked(harness):
    harness.handler.on_signal(harness.signal(stop_loss=30.0, take_profit=55.0))
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [
        e for e in events
        if getattr(e, "order_type", None) is not None and e.type.name == "ORDER"
    ]
    types = sorted(e.order_type.name for e in order_events)
    assert types == ["LIMIT", "MARKET", "STOP"]
    primary = next(e for e in order_events if e.order_type == OrderType.MARKET)
    children = [e for e in order_events if e.order_type != OrderType.MARKET]
    for child in children:
        assert child.parent_order_id == primary.order_id


# --- commands ---------------------------------------------------------------


def test_cancel_emits_cancel_command(harness):
    order = harness.rest_a_stop()
    ok = harness.handler.cancel_order(order.id, harness.portfolio_id)
    assert ok
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == 1
    assert order_events[0].command is OrderCommand.CANCEL
    assert order_events[0].order_id == order.id


def test_modify_emits_modify_command(harness):
    order = harness.rest_a_stop()
    ok = harness.handler.modify_order(order.id, new_price=28.0, portfolio_id=harness.portfolio_id)
    assert ok
    events = [harness.queue.get() for _ in range(harness.queue.qsize())]
    order_events = [e for e in events if e.type.name == "ORDER"]
    assert len(order_events) == 1
    assert order_events[0].command is OrderCommand.MODIFY


# --- reconciliation ---------------------------------------------------------


def test_executed_fill_marks_order_filled(harness):
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "EXECUTED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.FILLED


def test_cancelled_fill_marks_order_cancelled(harness):
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "CANCELLED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.CANCELLED


def test_unknown_order_id_is_safe(harness):
    # A fill for an order not in storage must not raise.
    import dataclasses
    order = harness.rest_a_stop()
    # Events are frozen (M3-01) — build the unknown-id variant via replace.
    fake = dataclasses.replace(harness.fill(order, "EXECUTED"), order_id=999999)
    harness.handler.on_fill(fake)  # should be a no-op, no exception
    assert harness.storage.get_order_by_id(999999, harness.portfolio_id) is None
    # The real order remains untouched (still active/PENDING).
    assert (
        harness.storage.get_order_by_id(order.id, harness.portfolio_id).status
        == OrderStatus.PENDING
    )


def test_refused_fill_marks_order_rejected(harness):
    # A REFUSED fill marks the order REJECTED (terminal) and removes it from the active book.
    order = harness.rest_a_stop()
    harness.handler.on_fill(harness.fill(order, "REFUSED"))
    stored = harness.storage.get_order_by_id(order.id, harness.portfolio_id)
    assert stored.status == OrderStatus.REJECTED
    active_ids = [o.id for o in harness.storage.get_active_orders(harness.portfolio_id)]
    assert order.id not in active_ids
