"""Run-end EXPIRE sweep + final drain is provably NON-CASCADING (LIFE-01, D-08).

The run-end bookend in ``BacktestRunner._run_backtest`` invokes
``order_handler.expire_all_resting()`` then ONE final
``event_handler.process_events()`` drain. T-06-06: that drain must be
NON-CASCADING — it may emit FillEvent(EXPIRED) (cleared through the exchange) and
the mirror reconciliation, but it must NOT re-enter the signal/new-order path:
no ``SignalEvent`` and no new ``OrderEvent(NEW)`` may be produced.

This is structurally guaranteed by the routes literal (ORDER -> on_order ONLY;
FILL -> portfolio + reconcile ONLY; EXPIRE emits no SIGNAL / no new ORDER), and
this test pins it end-to-end: a real engine with one order resting at run end is
swept + drained through the actual handlers, with a spy on the queue recording
every event that flows through. The spy asserts that across the sweep + drain
NO SignalEvent and NO OrderEvent(command == NEW) are ever enqueued.

Indentation: 4 SPACES (``tests/`` convention).
"""

import datetime as _dt
from decimal import Decimal

import pytest

from itrader.trading_system.backtest_trading_system import build_backtest_system
from itrader.trading_system.system_spec import SystemSpec
from itrader.order_handler.order import Order
from itrader.events_handler.events import SignalEvent, OrderEvent
from itrader.core.enums import Side, OrderCommand, OrderStatus, FillStatus
from itrader.events_handler.events import FillEvent

pytestmark = pytest.mark.integration

_GOLDEN_CSV = "data/BTCUSD_1d_ohlcv_2018_2026.csv"


def _btcusd_spec() -> SystemSpec:
    """A minimal single-ticker (BTCUSD) spec with one funded portfolio."""
    from tests.e2e.scenario_spec import PortfolioSpec  # local: spec helper
    return SystemSpec(
        start="2018-01-01",
        end="2026-06-03",
        timeframe="1d",
        ticker="BTCUSD",
        starting_cash=100_000,
        data={"BTCUSD": _GOLDEN_CSV},
        strategies=[],
        portfolios=[PortfolioSpec(name="pf", cash=100_000)],
    )


def test_run_end_sweep_then_drain_does_not_cascade():
    """Sweep + final drain emits FillEvent(EXPIRED) but NO SignalEvent and NO
    new OrderEvent(NEW) — the drain is provably non-cascading (T-06-06)."""
    system = build_backtest_system(_btcusd_spec())
    exchange = system.execution_handler.exchanges["simulated"]
    exchange.connect()

    portfolio = system.portfolio_handler.get_active_portfolios()[0]
    portfolio_id = portfolio.portfolio_id

    # Rest one far-from-market BUY LIMIT order at "run end": store the mirror and
    # submit it into the matching engine so it is genuinely resting.
    order = Order.new_limit_order(
        time=_dt.datetime(2018, 1, 2), ticker="BTCUSD", action=Side.BUY,
        price=Decimal("1.0"), quantity=Decimal("1.0"), exchange="simulated",
        strategy_id=1, portfolio_id=portfolio_id,
    )
    system.order_handler.order_manager.order_storage.add_order(order)
    resting_event = OrderEvent.new_order_event(order, command=OrderCommand.NEW)
    exchange.matching_engine.submit(resting_event)
    assert exchange.matching_engine.has_order(order.id)

    # Spy on the queue: record every event enqueued during sweep + drain.
    recorded: list = []
    real_put = system.global_queue.put

    def _spy_put(event, *args, **kwargs):
        recorded.append(event)
        return real_put(event, *args, **kwargs)

    system.global_queue.put = _spy_put  # type: ignore[method-assign]
    try:
        # The exact run-end bookend from BacktestRunner._run_backtest.
        system.order_handler.expire_all_resting()
        system.event_handler.process_events()
    finally:
        system.global_queue.put = real_put  # type: ignore[method-assign]

    # NON-CASCADE: no SignalEvent and no new OrderEvent(NEW) anywhere in the run-
    # end traffic. (OrderEvent(EXPIRE) IS expected — that is the sweep arm.)
    signals = [e for e in recorded if isinstance(e, SignalEvent)]
    new_orders = [
        e for e in recorded
        if isinstance(e, OrderEvent) and e.command == OrderCommand.NEW
    ]
    assert signals == []
    assert new_orders == []

    # Sanity: the EXPIRE arm did fire (OrderEvent(EXPIRE) + FillEvent(EXPIRED)),
    # so this is a real non-cascade, not a no-op.
    expire_orders = [
        e for e in recorded
        if isinstance(e, OrderEvent) and e.command == OrderCommand.EXPIRE
    ]
    expired_fills = [
        e for e in recorded
        if isinstance(e, FillEvent) and e.status == FillStatus.EXPIRED
    ]
    assert len(expire_orders) == 1
    assert len(expired_fills) == 1

    # The resting order is cleared and the mirror reconciled to EXPIRED.
    assert not exchange.matching_engine.has_order(order.id)
    stored = system.order_handler.get_order_by_id(order.id, portfolio_id)
    assert stored.status == OrderStatus.EXPIRED
