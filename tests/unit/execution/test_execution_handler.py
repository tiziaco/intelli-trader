from datetime import datetime, UTC
from queue import Queue

import pytest

from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.event import FillEvent, OrderEvent
from itrader.core.enums import OrderType


@pytest.fixture
def env():
    """ExecutionHandler with its queue plus a market BUY order event."""
    queue = Queue()
    execution_handler = ExecutionHandler(queue)
    order_event = OrderEvent(
        datetime.now(UTC),
        "BTCUSDT",
        "BUY",
        100.0,  # price
        1.0,    # quantity
        "simulated",
        1, 1,
        OrderType.MARKET,
    )
    yield queue, execution_handler, order_event
    while not queue.empty():
        queue.get_nowait()


def test_execution_handler_initialization(env):
    _queue, execution_handler, _order_event = env
    assert isinstance(execution_handler, ExecutionHandler)


def test_on_order(env):
    queue, execution_handler, order_event = env
    # Generate a fill event and process it from the order handler
    execution_handler.on_order(order_event)
    # Retrieve fill event from the queue
    fill_event: FillEvent = queue.get(False)
    assert isinstance(fill_event, FillEvent)
    assert fill_event.action == "BUY"
