from datetime import datetime
from types import SimpleNamespace

import pytest

from itrader.events_handler.event import EventType, FillStatus
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus
from itrader.events_handler.event import (
    TimeEvent,
    BarEvent,
    SignalEvent,
    OrderEvent,
    FillEvent,
)


@pytest.fixture
def events():
    """The full set of events constructed from a market BUY signal."""
    time = datetime.now()
    time_event = TimeEvent(time)
    bar_event = BarEvent(time, {})
    signal_event = SignalEvent(
        time=time, order_type="MARKET", ticker="BTCUSDT", action="BUY",
        price=42350.72, stop_loss=42000, take_profit=45000,
        strategy_id="test_strategy", portfolio_id="portfolio_id",
        strategy_setting={}, quantity=1,
    )
    # Create Order first, then OrderEvent
    order = Order.new_order(signal_event, "test_exchange")
    mkt_order_event = OrderEvent.new_order_event(order)
    fill_event = FillEvent.new_fill(
        "EXECUTED", mkt_order_event,
        price=mkt_order_event.price, quantity=mkt_order_event.quantity, commission=1.5)
    return SimpleNamespace(
        time_event=time_event,
        bar_event=bar_event,
        signal_event=signal_event,
        order=order,
        mkt_order_event=mkt_order_event,
        fill_event=fill_event,
    )


def test_time_event_initialization(events):
    assert isinstance(events.time_event, TimeEvent)


def test_bar_event_initialization(events):
    assert isinstance(events.bar_event, BarEvent)


def test_signal_event_initialization(events):
    assert isinstance(events.signal_event, SignalEvent)
    assert type(events.mkt_order_event.time) is datetime
    assert events.signal_event.ticker == "BTCUSDT"
    assert events.signal_event.action == "BUY"
    assert events.signal_event.price == 42350.72
    assert events.signal_event.quantity == 1
    assert events.signal_event.stop_loss == 42000
    assert events.signal_event.take_profit == 45000
    assert events.signal_event.strategy_id == "test_strategy"
    assert events.signal_event.portfolio_id == "portfolio_id"


def test_order_event_initialization(events):
    assert isinstance(events.mkt_order_event, OrderEvent)
    assert type(events.mkt_order_event.time) is datetime
    # Test Order object attributes (not OrderEvent)
    assert events.order.type == OrderType.MARKET
    assert events.order.status == OrderStatus.PENDING
    # Test OrderEvent attributes
    assert events.mkt_order_event.ticker == "BTCUSDT"
    assert events.mkt_order_event.action == "BUY"
    assert events.mkt_order_event.price == 42350.72
    assert events.mkt_order_event.quantity == 1
    assert events.mkt_order_event.strategy_id == "test_strategy"
    assert events.mkt_order_event.portfolio_id == "portfolio_id"


def test_fill_event_initialization(events):
    assert isinstance(events.fill_event, FillEvent)
    assert type(events.mkt_order_event.time) is datetime
    assert events.fill_event.status == FillStatus.EXECUTED
    assert events.fill_event.ticker == "BTCUSDT"
    assert events.fill_event.action == "BUY"
    assert events.fill_event.price == 42350.72
    assert events.fill_event.quantity == 1
    assert events.fill_event.commission == 1.5
    assert events.fill_event.portfolio_id == "portfolio_id"
