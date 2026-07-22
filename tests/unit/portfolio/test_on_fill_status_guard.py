from datetime import datetime
from queue import Queue
from types import SimpleNamespace

import pytest

import uuid_utils.compat as uuid_compat

from itrader.events_handler.events import FillEvent
from itrader.core.enums import FillStatus, Side
from tests.support.venue_wiring import backtest_portfolio_handler


@pytest.fixture
def env():
    queue = Queue()
    ptf = backtest_portfolio_handler(queue)
    pid = ptf.add_portfolio("p", "default", 100000)

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


# D-10 (Plan 05-05): on_fill is raise/None — no bool channel. The guard's
# observable behavior is whether a transaction/position was created.


def test_cancelled_fill_creates_no_transaction(env):
    assert env.ptf.on_fill(env.fill("CANCELLED")) is None  # ignored
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 0
    assert len(portfolio.transactions) == 0


def test_refused_fill_creates_no_transaction(env):
    assert env.ptf.on_fill(env.fill("REFUSED")) is None  # ignored
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 0
    assert len(portfolio.transactions) == 0


def test_executed_fill_is_processed(env):
    assert env.ptf.on_fill(env.fill("EXECUTED")) is None  # processed normally
    portfolio = env.ptf.get_portfolio(env.pid)
    assert len(portfolio.positions) == 1
    assert len(portfolio.transactions) == 1


# W1-07: the non-EXECUTED guard is hoisted ABOVE the _operation_context /
# correlation-id allocation. This is the one PERF-02 item with an observable
# side-effect the byte-exact oracle does NOT see, so pin it directly: a
# non-EXECUTED fill must NOT enter the operation context (no correlation-id
# allocated), while the EXECUTED path still does.
@pytest.mark.parametrize("status", ["CANCELLED", "REFUSED"])
def test_non_executed_fill_skips_operation_context(env, monkeypatch, status):
    calls = []
    original = env.ptf._operation_context

    def spy(operation_name):
        calls.append(operation_name)
        return original(operation_name)

    monkeypatch.setattr(env.ptf, "_operation_context", spy)

    assert env.ptf.on_fill(env.fill(status)) is None
    assert calls == []  # guard hoisted above the context — never entered


def test_executed_fill_enters_operation_context(env, monkeypatch):
    calls = []
    original = env.ptf._operation_context

    def spy(operation_name):
        calls.append(operation_name)
        return original(operation_name)

    monkeypatch.setattr(env.ptf, "_operation_context", spy)

    assert env.ptf.on_fill(env.fill("EXECUTED")) is None
    assert calls == ["on_fill"]  # EXECUTED path still enters the context
