from datetime import datetime

from itrader.events_handler.event import OrderEvent
from itrader.core.enums import OrderType, OrderCommand
from itrader.order_handler.order import Order


def _order(order_type):
    return Order(
        time=datetime(2024, 1, 1), type=order_type, status=None,
        ticker="BTCUSDT", action="SELL", price=42.0, quantity=2.0,
        exchange="default", strategy_id=1, portfolio_id=1,
    )


def test_preserves_real_order_type():
    oe = OrderEvent.new_order_event(_order(OrderType.STOP))
    assert oe.order_type is OrderType.STOP


def test_preserves_order_id():
    order = _order(OrderType.LIMIT)
    oe = OrderEvent.new_order_event(order)
    assert oe.order_id == order.id


def test_command_defaults_to_new():
    oe = OrderEvent.new_order_event(_order(OrderType.MARKET))
    assert oe.command is OrderCommand.NEW


def test_command_can_be_overridden():
    oe = OrderEvent.new_order_event(_order(OrderType.STOP), command=OrderCommand.CANCEL)
    assert oe.command is OrderCommand.CANCEL


def test_parent_order_id_copied():
    order = _order(OrderType.STOP)
    order.parent_order_id = 999
    oe = OrderEvent.new_order_event(order)
    assert oe.parent_order_id == 999
