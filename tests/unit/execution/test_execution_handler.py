from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.execution_handler.base import AbstractExecutionHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.events import FillEvent, OrderEvent
from itrader.core.enums import FillStatus, OrderType, Side


@pytest.fixture
def env():
    """ExecutionHandler with its queue plus a market BUY order event."""
    queue = Queue()
    execution_handler = ExecutionHandler(queue)
    order_event = OrderEvent(
        time=datetime(2024, 1, 1),
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


def test_on_order_rests_then_fill_arrives_with_next_bar(env, make_bar):
    """D-01/D-13: routing a NEW market order produces NO same-drain fill —
    the order rests and fills at the next routed bar's open."""
    queue, execution_handler, order_event = env
    execution_handler.on_order(order_event)
    assert queue.qsize() == 0          # rests; no immediate FillEvent

    bar = make_bar(open_=101.5, high=103, low=99, close=102,
                   time=datetime(2024, 1, 2))
    execution_handler.on_market_data(bar)
    fill_event: FillEvent = queue.get(False)
    assert isinstance(fill_event, FillEvent)
    assert fill_event.action is Side.BUY
    assert fill_event.status is FillStatus.EXECUTED
    assert fill_event.price == Decimal("101.5")   # the bar's open, exact
    assert fill_event.time == bar.time            # stamped T+1tf


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


def test_no_config_construction_admits_btcusd(env):
    """TEMPORARY BTCUSD backward-compat fallback (D-13, Trap 1; Wave 4 removes it).

    With NO ``exchange_config`` supplied, ``ExecutionHandler(global_queue)`` must
    still seed the COMPLETE default-preset ∪ {BTCUSD} set at construction so the
    direct-construction oracle/integration path (which lost the removed hardcoded
    ``register_symbol('BTCUSD')`` line) stays byte-exact. Seeding the complete set
    at construction is replacement-safe: a later ``update_config`` re-derivation
    can never silently wipe BTCUSD.
    """
    _queue, execution_handler, _order_event = env
    exchange = execution_handler.exchanges['simulated']
    assert 'BTCUSD' in exchange._supported_symbols
    # The default preset symbols must remain admitted (the union, not a replacement).
    assert {'BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'SOLUSDT'} <= exchange._supported_symbols
