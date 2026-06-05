from datetime import datetime
from queue import Queue

import pandas as pd
import pytest

from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.event import OrderEvent, BarEvent, FillStatus
from itrader.core.enums import OrderType, OrderCommand


class _RoutingEnv:
    def __init__(self):
        self.queue = Queue()
        self.handler = ExecutionHandler(self.queue)
        exchange = self.handler.exchanges["simulated"]
        exchange.connect()
        exchange.update_config(supported_symbols={"BTCUSDT"})

    def oe(self, order_type, action="BUY", price=40.0, order_id=1):
        return OrderEvent(
            time=datetime(2024, 1, 1), ticker="BTCUSDT", action=action, price=price,
            quantity=1.0, exchange="simulated", strategy_id=1, portfolio_id=1,
            order_type=order_type, order_id=order_id, command=OrderCommand.NEW,
        )


@pytest.fixture
def env():
    e = _RoutingEnv()
    yield e
    while not e.queue.empty():
        e.queue.get_nowait()


def test_market_order_routed_and_filled(env):
    env.handler.on_order(env.oe(OrderType.MARKET))
    fills = [env.queue.get() for _ in range(env.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.EXECUTED


def test_market_data_routed_to_exchange(env):
    env.handler.on_order(env.oe(OrderType.STOP, action="SELL", price=30.0, order_id=2))
    bars = {
        "BTCUSDT": pd.DataFrame(
            {"open": [35], "high": [36], "low": [20], "close": [25], "volume": [1]}
        )
    }
    env.handler.on_market_data(BarEvent(time=datetime(2024, 1, 1), bars=bars))
    fills = [env.queue.get() for _ in range(env.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].order_id == 2
