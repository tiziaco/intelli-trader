from queue import Queue
from datetime import datetime, UTC

import pytest

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.events_handler.events import SignalEvent
from itrader.core.enums import OrderType, Side


_STRATEGY_ID = 1
_PORTFOLIO_ID = 1


@pytest.fixture
def order_handler():
    """An OrderHandler wired to a PortfolioHandler with one funded portfolio.

    Seeds a BUY signal onto the shared queue (mirroring the legacy setUp) and drains
    the queue on teardown so the strict warning filter never sees a dangling resource.
    """
    q = Queue()
    ptf_handler = PortfolioHandler(q)
    ptf_handler.add_portfolio(1, "test_ptf", "default", 10000)
    handler = OrderHandler(q, ptf_handler)

    buy_signal = SignalEvent(
        time=datetime.now(UTC),
        order_type=OrderType.MARKET,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=40.0,
        quantity=100.0,
        stop_loss=0.0,
        take_profit=0.0,
        strategy_id=_STRATEGY_ID,
        portfolio_id=_PORTFOLIO_ID,
        strategy_setting={},
    )
    q.put(buy_signal)

    yield handler

    while not q.empty():
        q.get_nowait()


def test_order_handler_initialization(order_handler):
    assert isinstance(order_handler, OrderHandler)
