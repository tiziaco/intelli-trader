from datetime import datetime
from decimal import Decimal
from queue import Queue

import pytest

from itrader.core.bar import Bar
from itrader.execution_handler.execution_handler import (
    DEFAULT_ACCOUNT_ID,
    ExecutionHandler,
)
from itrader.events_handler.events import OrderEvent, BarEvent
from itrader.core.enums import FillStatus, OrderType, OrderCommand, Side

from tests.support.venue_wiring import backtest_venue_bundles


class _RoutingEnv:
    def __init__(self):
        self.queue = Queue()
        self.handler = ExecutionHandler(
            self.queue, venue_bundles=backtest_venue_bundles(self.queue))
        exchange = self.handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)]
        exchange.connect()
        exchange.update_config({"limits": {"supported_symbols": {"BTCUSDT"}}})

    def oe(self, order_type, action="BUY", price=40.0, order_id=1):
        return OrderEvent(
            time=datetime(2024, 1, 1), ticker="BTCUSDT", action=Side(action), price=price,
            quantity=1.0, exchange="paper", strategy_id=1, portfolio_id=1,
            order_type=order_type, order_id=order_id, command=OrderCommand.NEW,
        )


@pytest.fixture
def env():
    e = _RoutingEnv()
    yield e
    while not e.queue.empty():
        e.queue.get_nowait()


def test_market_order_routed_rests_then_fills_at_next_open(env):
    """D-01/D-13: the handler routes the NEW market order to the exchange,
    where it RESTS; the next routed bar fills it at the bar's open with
    FillEvent.time == the bar's event time."""
    env.handler.on_order(env.oe(OrderType.MARKET, price=40.0))
    assert env.queue.qsize() == 0          # no same-drain fill

    t = datetime(2024, 1, 2)
    bars = {
        "BTCUSDT": Bar(time=t, open=Decimal("41.5"), high=Decimal("45"),
                       low=Decimal("40"), close=Decimal("44"), volume=Decimal("1"))
    }
    env.handler.on_market_data(BarEvent(time=t, bars=bars))
    fills = [env.queue.get() for _ in range(env.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.EXECUTED
    assert fills[0].price == Decimal("41.5")   # the next bar's open, exact
    assert fills[0].time == t                  # stamped T+1tf


def test_market_data_routed_to_exchange(env):
    env.handler.on_order(env.oe(OrderType.STOP, action="SELL", price=30.0, order_id=2))
    t = datetime(2024, 1, 1)
    bars = {
        "BTCUSDT": Bar(time=t, open=Decimal("35"), high=Decimal("36"),
                       low=Decimal("20"), close=Decimal("25"), volume=Decimal("1"))
    }
    env.handler.on_market_data(BarEvent(time=t, bars=bars))
    fills = [env.queue.get() for _ in range(env.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].order_id == 2
