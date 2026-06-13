from datetime import datetime
from decimal import Decimal

from itrader.events_handler.events import OrderEvent
from itrader.core.enums import OrderType, OrderCommand, Side
from itrader.order_handler.order import Order


def _order(order_type):
    return Order(
        time=datetime(2024, 1, 1), type=order_type, status=None,
        ticker="BTCUSDT", action=Side.SELL, price=42.0, quantity=2.0,
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


def test_action_parsed_to_side_member():
    # SIG-03 (D-03): the entity now stores a Side member; the factory's
    # Side(order.action) is a no-op pass-through at the event boundary.
    oe = OrderEvent.new_order_event(_order(OrderType.MARKET))
    assert oe.action is Side.SELL


def test_decimal_money_passes_through_exactly():
    # D-22 (closing the Phase 4 D-04 deferral): the factory passes the Order
    # entity's Decimal price/quantity through EXACTLY — the float() boundary
    # coercion is gone, so no binary round-trip can alter the value.
    order = Order(
        time=datetime(2024, 1, 1), type=OrderType.LIMIT, status=None,
        ticker="BTCUSDT", action=Side.SELL,
        price=Decimal("123.45678901"), quantity=Decimal("0.12345678901234567890123456"),
        exchange="default", strategy_id=1, portfolio_id=1,
    )
    oe = OrderEvent.new_order_event(order)
    assert isinstance(oe.price, Decimal)
    assert isinstance(oe.quantity, Decimal)
    assert oe.price == Decimal("123.45678901")
    assert str(oe.price) == "123.45678901"
    # Full 26-significant-digit Decimal survives — a float round-trip could not
    # carry this precision.
    assert oe.quantity == Decimal("0.12345678901234567890123456")
    assert str(oe.quantity) == "0.12345678901234567890123456"


def test_frozen_base_fields_present():
    # M3-01 base fields: uuid7 event_id + business-time created_at; D-11
    # bracket linkage defaults to the empty tuple on non-bracket orders.
    oe = OrderEvent.new_order_event(_order(OrderType.MARKET))
    assert oe.event_id.version == 7
    assert oe.created_at == oe.time
    assert oe.child_order_ids == ()
