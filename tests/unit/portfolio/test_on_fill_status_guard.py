from datetime import datetime
from queue import Queue
from types import SimpleNamespace

import pytest

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.events import FillEvent
from itrader.core.enums import FillStatus, Side


@pytest.fixture
def env():
    queue = Queue()
    ptf = PortfolioHandler(queue)
    pid = ptf.add_portfolio(1, "p", "default", 100000)

    def fill(status):
        return FillEvent(
            time=datetime(2024, 1, 1),
            status=FillStatus[status],
            ticker="BTCUSDT",
            action=Side.BUY,
            price=40.0,
            quantity=1.0,
            commission=0.0,
            portfolio_id=pid,
            # D-12: required linkage ids
            fill_id=uuid_compat.uuid7(),
            order_id=uuid_compat.uuid7(),
            strategy_id=1,
        )

    yield SimpleNamespace(queue=queue, ptf=ptf, pid=pid, fill=fill)
    while not queue.empty():
        queue.get_nowait()


def test_cancelled_fill_creates_no_transaction(env):
    result = env.ptf.on_fill(env.fill("CANCELLED"))
    assert not result  # ignored, no transaction
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 0
    assert len(portfolio.transactions) == 0


def test_refused_fill_creates_no_transaction(env):
    result = env.ptf.on_fill(env.fill("REFUSED"))
    assert not result  # ignored, no transaction
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 0
    assert len(portfolio.transactions) == 0


def test_executed_fill_is_processed(env):
    result = env.ptf.on_fill(env.fill("EXECUTED"))
    assert result  # processed normally
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 1
    assert len(portfolio.transactions) == 1
