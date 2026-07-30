"""ACCT-09 / D-42: ``ExecutionHandler.on_order``'s two surviving fail-closed
paths emit a distinctly-coded ``FillEvent(REFUSED)`` instead of only logging and
returning.

Before this phase a misconfigured live engine dropped 100% of its orders while
``get_status()`` reported ``RUNNING``, ``errors_count: 0`` and no halt reason —
the drop was invisible in the event stream and left the order mirror stuck in
``PENDING`` forever. Now each of the two surviving refusals (unknown portfolio;
unregistered ``(venue, account_id)`` pair) puts exactly one REFUSED fill on the
queue carrying a distinct ``ExecutionErrorCode``, so the failure is observable in
the event stream and reconciles the mirror out of ``PENDING``.

These assertions are on the EMITTED EVENT and its error code, never on log text.
"""

from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue

import pytest

from itrader.execution_handler.execution_handler import (
    DEFAULT_ACCOUNT_ID,
    ExecutionHandler,
)
from itrader.order_handler.order_handler import OrderHandler
from itrader.events_handler.events import FillEvent, OrderEvent, SignalEvent
from itrader.core.enums import FillStatus, OrderStatus, OrderType, Side
from itrader.core.enums.execution import ExecutionErrorCode
from itrader.core.exceptions.portfolio import PortfolioNotFoundError
from itrader.core.sizing import FractionOfCash, TradingDirection

from tests.support.venue_wiring import (
    backtest_exchange_registry,
    backtest_portfolio_handler,
    single_account_read_model,
)


class _StubReadModel:
    """Minimal ``PortfolioReadModel`` stand-in exposing only ``account_for``.

    A ``portfolio_id`` absent from the mapping raises ``PortfolioNotFoundError``
    (the unknown-portfolio path); a mapped value of ``None`` models a portfolio
    that names no account.
    """

    def __init__(self, mapping):
        self._mapping = mapping

    def account_for(self, portfolio_id):
        if portfolio_id not in self._mapping:
            raise PortfolioNotFoundError(portfolio_id)
        return self._mapping[portfolio_id]


class _RaisingExchange:
    """An exchange whose ``on_order`` raises — exercises the broad handler."""

    def on_order(self, event):
        raise RuntimeError("venue blew up")


def _order_for(portfolio_id, exchange="paper", order_id=1):
    return OrderEvent(
        time=datetime(2024, 1, 1),
        ticker="BTCUSDT",
        action=Side.BUY,
        price=100.0,
        quantity=2.0,
        exchange=exchange,
        strategy_id=1,
        portfolio_id=portfolio_id,
        order_type=OrderType.MARKET,
        order_id=order_id,
    )


@pytest.fixture
def handler():
    queue = Queue()
    execution_handler = ExecutionHandler(
        queue, exchange_registry=backtest_exchange_registry(queue),
        portfolio_read_model=single_account_read_model())
    yield queue, execution_handler
    while not queue.empty():
        queue.get_nowait()


def _drain_one_fill(queue) -> FillEvent:
    assert queue.qsize() == 1, "exactly one event expected on the queue"
    event = queue.get(False)
    assert isinstance(event, FillEvent)
    return event


def test_unknown_portfolio_emits_one_refused_fill_with_its_code(handler):
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", "a"): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "a"})

    execution_handler.on_order(_order_for(99))  # 99 not in mapping -> raises

    fill = _drain_one_fill(queue)
    assert fill.status is FillStatus.REFUSED
    assert fill.error_code is ExecutionErrorCode.UNKNOWN_PORTFOLIO


def test_unregistered_pair_emits_one_refused_fill_with_its_code(handler):
    queue, execution_handler = handler
    # portfolio 1 resolves to account 'c', for which no exchange is registered.
    execution_handler.exchanges = {("paper", "a"): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "c"})

    execution_handler.on_order(_order_for(1))

    fill = _drain_one_fill(queue)
    assert fill.status is FillStatus.REFUSED
    assert fill.error_code is ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT


def test_the_two_refusal_codes_differ(handler):
    """The two refusals are distinguishable by error code alone — the whole
    point, since these failures are currently invisible in ``get_status()``."""
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", "a"): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "c"})

    execution_handler.on_order(_order_for(1))
    unregistered = _drain_one_fill(queue).error_code

    execution_handler.on_order(_order_for(99))
    unknown = _drain_one_fill(queue).error_code

    assert unregistered is ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT
    assert unknown is ExecutionErrorCode.UNKNOWN_PORTFOLIO
    assert unregistered is not unknown


def test_refused_fill_money_fields_are_decimal_and_commission_zero(handler):
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", "a"): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "c"})

    order = _order_for(1)
    execution_handler.on_order(order)
    fill = _drain_one_fill(queue)

    assert isinstance(fill.price, Decimal)
    assert isinstance(fill.quantity, Decimal)
    assert isinstance(fill.commission, Decimal)
    assert fill.commission == Decimal("0")
    # the order's OWN price/quantity — never settled, no float round-trip
    assert fill.price == Decimal("100")
    assert fill.quantity == Decimal("2")


def test_on_order_does_not_raise_on_either_refusal(handler):
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", "a"): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "c"})

    # neither refusal escapes across the queue boundary
    assert execution_handler.on_order(_order_for(1)) is None
    assert execution_handler.on_order(_order_for(99)) is None


def test_account_id_none_falls_through_to_unregistered_pair_refusal(handler):
    """The dedicated ``if account_id is None`` branch is deleted; a portfolio
    naming no account still fails closed via the pair-lookup miss."""
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", DEFAULT_ACCOUNT_ID): object()}
    execution_handler._portfolio_read_model = _StubReadModel({1: None})

    execution_handler.on_order(_order_for(1))

    fill = _drain_one_fill(queue)
    assert fill.status is FillStatus.REFUSED
    assert fill.error_code is ExecutionErrorCode.UNREGISTERED_VENUE_ACCOUNT


def test_broad_except_catches_exchange_error_without_reraising(handler):
    """The broad ``except Exception`` still swallows a per-exchange failure — the
    live publish-and-continue policy is intentional and untouched."""
    queue, execution_handler = handler
    execution_handler.exchanges = {("paper", "a"): _RaisingExchange()}
    execution_handler._portfolio_read_model = _StubReadModel({1: "a"})

    # routes to the exchange, which raises; the broad handler logs and returns
    assert execution_handler.on_order(_order_for(1)) is None
    # no REFUSED fill from the broad path — it caught after routing
    assert queue.qsize() == 0


def test_refused_fill_moves_order_mirror_out_of_pending():
    """End-to-end: the REFUSED fill emitted by ``on_order`` reconciles the order
    mirror out of ``PENDING`` (REFUSED -> REJECTED)."""
    queue = Queue()
    ptf_handler = backtest_portfolio_handler(queue)
    ptf_id = ptf_handler.add_portfolio("test_ptf", "default", 10000)
    order_handler = OrderHandler(queue, ptf_handler)

    signal = SignalEvent(
        time=datetime.now(UTC),
        order_type=OrderType.MARKET,
        ticker="BTCUSDT",
        action=Side.BUY,
        price=40.0,
        quantity=100.0,
        stop_loss=0.0,
        take_profit=0.0,
        strategy_id=1,
        portfolio_id=ptf_id,
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
    )
    order_handler.on_signal(signal)

    order_event = queue.get(False)
    assert isinstance(order_event, OrderEvent)
    pf_id = order_event.portfolio_id
    pending = order_handler.get_orders_by_status(OrderStatus.PENDING, pf_id)
    assert len(pending) == 1

    # Route the order through an ExecutionHandler whose registry has no exchange
    # for the resolved account -> a REFUSED(UNREGISTERED_VENUE_ACCOUNT) fill.
    execution_handler = ExecutionHandler(
        queue, exchange_registry={},
        portfolio_read_model=_StubReadModel({pf_id: "unmapped"}))
    execution_handler.on_order(order_event)

    fill = queue.get(False)
    assert isinstance(fill, FillEvent)
    assert fill.status is FillStatus.REFUSED

    order_handler.on_fill(fill)
    assert order_handler.get_orders_by_status(OrderStatus.PENDING, pf_id) == []
    rejected = order_handler.get_orders_by_status(OrderStatus.REJECTED, pf_id)
    assert len(rejected) == 1

    while not queue.empty():
        queue.get_nowait()
