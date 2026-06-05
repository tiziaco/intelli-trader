from datetime import datetime

from itrader.events_handler.event import OrderEvent, FillEvent, FillStatus
from itrader.core.enums import OrderType


def _order_event():
    return OrderEvent(
        time=datetime(2024, 1, 1), ticker="BTCUSDT", action="BUY",
        price=40.0, quantity=1.0, exchange="default", strategy_id=1,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
    )


def test_executed_fill_carries_order_id():
    fill = FillEvent.new_fill("EXECUTED", 0.5, _order_event())
    assert fill.order_id == 7
    assert fill.status is FillStatus.EXECUTED


def test_cancelled_status_supported():
    fill = FillEvent.new_fill("CANCELLED", 0.0, _order_event())
    assert fill.status is FillStatus.CANCELLED
    assert fill.order_id == 7
