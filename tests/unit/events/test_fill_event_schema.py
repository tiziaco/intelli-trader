import uuid
from datetime import datetime

import uuid_utils.compat as uuid_compat

from itrader.events_handler.event import OrderEvent, FillEvent, FillStatus
from itrader.core.enums import OrderType

_STRATEGY_ID = uuid_compat.uuid7()


def _order_event():
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker="BTCUSDT", action="BUY",
        price=40.0, quantity=1.0, exchange="default", strategy_id=_STRATEGY_ID,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
    )


def test_executed_fill_carries_order_id():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.5)
    assert fill.order_id == 7
    assert fill.status is FillStatus.EXECUTED


def test_cancelled_status_supported():
    order = _order_event()
    fill = FillEvent.new_fill(
        "CANCELLED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill.status is FillStatus.CANCELLED
    assert fill.order_id == 7


def test_fill_id_is_uuid7():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert isinstance(fill.fill_id, uuid.UUID)
    assert fill.fill_id.version == 7


def test_each_fill_gets_a_unique_fill_id():
    order = _order_event()
    fill_a = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    fill_b = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill_a.fill_id != fill_b.fill_id


def test_strategy_id_copied_from_order():
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=order.price, quantity=order.quantity, commission=0.0)
    assert fill.strategy_id == _STRATEGY_ID


def test_executed_values_land_without_mutation():
    # Construct-complete (D-12): the executed price/quantity are explicit
    # constructor inputs — they land on the fill as-is, and the originating
    # order is left untouched.
    order = _order_event()
    fill = FillEvent.new_fill(
        "EXECUTED", order, price=41.5, quantity=0.75, commission=0.1)
    assert fill.price == 41.5
    assert fill.quantity == 0.75
    assert fill.commission == 0.1
    assert order.price == 40.0
    assert order.quantity == 1.0
