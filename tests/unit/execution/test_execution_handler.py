from datetime import datetime, UTC
from queue import Queue

import pytest

from itrader.execution_handler.base import AbstractExecutionHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.core.enums import OrderType, Side


@pytest.fixture
def env():
    """ExecutionHandler with its queue plus a market BUY order event."""
    queue = Queue()
    execution_handler = ExecutionHandler(queue)
    order_event = OrderEvent(
        time=datetime.now(UTC),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=100.0,
        quantity=1.0,
        exchange="simulated",
        strategy_id=1,
        portfolio_id=1,
        order_type=OrderType.MARKET,
        order_id=1,
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
    assert fill_event.action is Side.BUY


def test_abstract_execution_handler_is_real_abc():
    """AbstractExecutionHandler is a real ABC (D-21/#39): both event hooks
    are abstract and the base class cannot be instantiated."""
    with pytest.raises(TypeError):
        AbstractExecutionHandler()  # type: ignore[abstract]

    assert getattr(AbstractExecutionHandler.on_order, '__isabstractmethod__', False)
    assert getattr(AbstractExecutionHandler.on_market_data, '__isabstractmethod__', False)


def test_execution_handler_implements_both_hooks(env):
    """The concrete ExecutionHandler satisfies the ABC contract."""
    _queue, execution_handler, _order_event = env
    assert isinstance(execution_handler, AbstractExecutionHandler)
