from datetime import datetime
from queue import Queue
from types import SimpleNamespace

import pandas as pd
import pytest

import uuid_utils.compat as uuid_compat

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.events import FillEvent, BarEvent, PortfolioUpdateEvent
from itrader.core.enums import FillStatus, Side


def _fill(ticker, action, price, quantity, portfolio_id):
    """Construct-complete EXECUTED fill with the D-12 required linkage ids."""
    return FillEvent(
        time=datetime.now(), status=FillStatus.EXECUTED, ticker=ticker,
        action=action, price=price, quantity=quantity, commission=0,
        portfolio_id=portfolio_id, fill_id=uuid_compat.uuid7(),
        order_id=uuid_compat.uuid7(), strategy_id=1,
    )


@pytest.fixture
def env():
    """A PortfolioHandler with one funded ($1000) simulated portfolio."""
    queue = Queue()
    ptf_handler = PortfolioHandler(queue)
    portfolio_id = ptf_handler.add_portfolio(1, "test_ptf", "simulated", 1000)
    yield SimpleNamespace(queue=queue, ptf_handler=ptf_handler, portfolio_id=portfolio_id)
    while not queue.empty():
        queue.get_nowait()


def test_update_portfolios_market(env):
    # Open 2 positions, 1 long and 1 short
    buy_fill = _fill("BTCUSDT", Side.BUY, 40, 1, env.portfolio_id)
    sell_fill = _fill("ETHUSDT", Side.SELL, 20, 1, env.portfolio_id)
    env.ptf_handler.on_fill(buy_fill)
    env.ptf_handler.on_fill(sell_fill)
    # Create a simulated BarEvent
    bars_dict = {
        "BTCUSDT": pd.DataFrame(
            {"open": [30], "high": [60], "low": [20], "close": [50], "volume": [1000]}),
        "ETHUSDT": pd.DataFrame(
            {"open": [20], "high": [50], "low": [10], "close": [40], "volume": [500]}),
    }
    bar_event = BarEvent(time=datetime.now(), bars=bars_dict)

    # Update portfolios market value
    env.ptf_handler.update_portfolios_market_value(bar_event)
    portfolio = env.ptf_handler.get_portfolio(env.portfolio_id)

    # Assert if the portfolio has been created
    assert env.ptf_handler.get_portfolio_count() == 1
    # Assert the portfolio's metrics - Updated to reflect correct financial logic
    assert portfolio.cash == 980  # $1000 - $40 (BTC buy) + $20 (ETH short) = $980
    assert portfolio.total_market_value == 10  # BTC: $50 (long), ETH: -$40 (short) = $10
    assert portfolio.total_equity == 990  # $980 cash + $10 market value = $990
    assert portfolio.total_pnl == -10  # Total P&L
    assert portfolio.total_realised_pnl == 0
    assert portfolio.total_unrealised_pnl == -10  # BTC: +$10, ETH: -$20 = -$10
    # TODO: the short position is not correctly updated. To be fixed!


def test_generate_portfolios_update_event(env):
    # Open 1 long positions
    buy_fill = _fill("BTCUSDT", Side.BUY, 40, 1, env.portfolio_id)
    env.ptf_handler.on_fill(buy_fill)

    update_event = env.ptf_handler.generate_portfolios_update_event()
    portfolios = update_event.portfolios
    portfolios_id = list(portfolios.keys())

    assert isinstance(update_event, PortfolioUpdateEvent)
    assert isinstance(portfolios, dict)
    assert len(portfolios) == 1
    assert portfolios_id == [str(env.portfolio_id)]
    # Assert the portfolio's metrics
    assert portfolios.get(str(env.portfolio_id)).get("available_cash") == 960
    assert portfolios.get(str(env.portfolio_id)).get("reserved_cash") == 0


def test_update_event_available_cash_is_reservation_adjusted(env):
    """WR-07 regression: the serialized available_cash is the reservation-
    adjusted buying power (total - reserved), not the total balance."""
    from decimal import Decimal

    portfolio = env.ptf_handler.get_portfolio(env.portfolio_id)
    portfolio.cash_manager.reserve_cash(Decimal("100.00"), "pending order", "ORDER_X")

    update_event = env.ptf_handler.generate_portfolios_update_event()
    snapshot = update_event.portfolios[str(env.portfolio_id)]

    assert snapshot["cash"] == 1000
    assert snapshot["available_cash"] == 900
    assert snapshot["reserved_cash"] == 100
