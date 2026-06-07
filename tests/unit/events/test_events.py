from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from itrader.core.bar import Bar
from itrader.core.enums import EventType, FillStatus, OrderType, OrderStatus, Side
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.order_handler.order import Order
from itrader.events_handler.events import (
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
    time_event = TimeEvent(time=time)
    # M5-02: BarEvent payload is dict[str, Bar] — one Decimal struct per ticker.
    bar_event = BarEvent(time=time, bars={
        "BTCUSDT": Bar(time=time, open=Decimal("42000"), high=Decimal("42500"),
                       low=Decimal("41800"), close=Decimal("42350.72"),
                       volume=Decimal("10")),
    })
    signal_event = SignalEvent(
        time=time, order_type=OrderType.MARKET, ticker="BTCUSDT", action=Side.BUY,
        # D-22: event money is Decimal — enter via the string path (D-04).
        price=Decimal("42350.72"), stop_loss=Decimal("42000"), take_profit=Decimal("45000"),
        strategy_id="test_strategy", portfolio_id="portfolio_id",
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        quantity=Decimal("1"),
    )
    # Create Order first, then OrderEvent
    order = Order.new_order(signal_event, "test_exchange")
    mkt_order_event = OrderEvent.new_order_event(order)
    fill_event = FillEvent.new_fill(
        "EXECUTED", mkt_order_event,
        price=mkt_order_event.price, quantity=mkt_order_event.quantity,
        commission=Decimal("1.5"))
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
    assert events.time_event.type is EventType.TIME


def test_bar_event_initialization(events):
    assert isinstance(events.bar_event, BarEvent)
    assert events.bar_event.type is EventType.BAR
    # M5-02 payload: direct field access on the Bar struct, Decimal money.
    assert isinstance(events.bar_event.bars["BTCUSDT"], Bar)
    assert events.bar_event.bars["BTCUSDT"].close == Decimal("42350.72")


def test_signal_event_initialization(events):
    assert isinstance(events.signal_event, SignalEvent)
    assert type(events.mkt_order_event.time) is datetime
    assert events.signal_event.ticker == "BTCUSDT"
    assert events.signal_event.action is Side.BUY
    assert events.signal_event.order_type is OrderType.MARKET
    assert events.signal_event.price == Decimal("42350.72")
    assert events.signal_event.quantity == Decimal("1")
    assert events.signal_event.stop_loss == Decimal("42000")
    assert events.signal_event.take_profit == Decimal("45000")
    assert events.signal_event.strategy_id == "test_strategy"
    assert events.signal_event.portfolio_id == "portfolio_id"
    # Frozen-event base fields (M3-01)
    assert events.signal_event.event_id.version == 7
    assert events.signal_event.created_at == events.signal_event.time


def test_order_event_initialization(events):
    assert isinstance(events.mkt_order_event, OrderEvent)
    assert type(events.mkt_order_event.time) is datetime
    # Test Order object attributes (not OrderEvent)
    assert events.order.type == OrderType.MARKET
    assert events.order.status == OrderStatus.PENDING
    # Test OrderEvent attributes
    assert events.mkt_order_event.ticker == "BTCUSDT"
    assert events.mkt_order_event.action is Side.BUY
    # D-22: the entity's Decimal money passes through the event exactly.
    assert events.mkt_order_event.price == Decimal("42350.72")
    assert events.mkt_order_event.quantity == Decimal("1")
    assert events.mkt_order_event.strategy_id == "test_strategy"
    assert events.mkt_order_event.portfolio_id == "portfolio_id"
    # D-12: the OrderEvent carries its entity's id; D-11: empty bracket tuple
    assert events.mkt_order_event.order_id == events.order.id
    assert events.mkt_order_event.child_order_ids == ()
    assert events.mkt_order_event.event_id.version == 7


def test_fill_event_initialization(events):
    assert isinstance(events.fill_event, FillEvent)
    assert type(events.mkt_order_event.time) is datetime
    assert events.fill_event.status == FillStatus.EXECUTED
    assert events.fill_event.ticker == "BTCUSDT"
    assert events.fill_event.action is Side.BUY
    # D-22: fill money is Decimal — exact Decimal equality, no approx.
    assert events.fill_event.price == Decimal("42350.72")
    assert events.fill_event.quantity == Decimal("1")
    assert events.fill_event.commission == Decimal("1.5")
    assert events.fill_event.portfolio_id == "portfolio_id"
    # D-12 audit chain: fill -> order -> strategy
    assert events.fill_event.fill_id.version == 7
    assert events.fill_event.order_id == events.order.id
    assert events.fill_event.strategy_id == "test_strategy"
