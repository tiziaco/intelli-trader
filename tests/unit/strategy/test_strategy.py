from datetime import datetime
from queue import Queue

import pandas as pd
import pytest

from itrader.strategy_handler.base import Strategy
from itrader.events_handler.events import SignalEvent, BarEvent
from itrader.core.enums import OrderType, Side


_PORTFOLIO_NAME = "test_pf"
_TICKER = "SOLUSDT"


class _ConcreteStrategy(Strategy):
    """
    Minimal concrete Strategy used to exercise the shared base behaviour
    (buy/sell/init). ``Strategy`` is now a real ABC enforcing ``calculate_signal``
    (02-05, #20), so the base cannot be instantiated directly.
    """

    def calculate_signal(self, ticker: str, bars: pd.DataFrame) -> None:
        return None


@pytest.fixture
def strategy():
    """A subscribed concrete Strategy with its own queue and a seeded last_event.

    Yields the (strategy, queue) pair; the queue closes on teardown so the strict
    ``filterwarnings=["error"]`` filter never promotes a leaked-resource warning.
    """
    q = Queue()
    strat = _ConcreteStrategy("test_strategy", "1h", [_TICKER], global_queue=q)
    strat.subscribe_portfolio(_PORTFOLIO_NAME)

    bars_dict = {
        _TICKER: pd.DataFrame(
            {"open": [100], "high": [110], "low": [90], "close": [105], "volume": [1000]}
        )
    }
    strat.last_event = BarEvent(time=datetime.now(), bars=bars_dict)

    yield strat, q

    # Drain any residual events so nothing dangles into the next test.
    while not q.empty():
        q.get_nowait()


def test_strategy_instance(strategy):
    """Test the correct initialization of the Strategy instance."""
    strat, _q = strategy
    assert isinstance(strat, Strategy)
    assert isinstance(strat.global_queue, Queue)
    assert strat.is_active is True
    assert strat.order_type == "market"
    assert strat.subscribed_portfolios == [_PORTFOLIO_NAME]
    assert strat.tickers == [_TICKER]


def test_buy_signal(strategy):
    """Generate a BUY signal with the ``buy()`` method of the Strategy object."""
    strat, q = strategy
    strat.buy("SOLUSDT", 40, 50)

    event: SignalEvent = q.get(False)

    assert isinstance(event, SignalEvent)
    assert event.strategy_id == strat.strategy_id
    assert event.action is Side.BUY
    assert event.order_type is OrderType.MARKET
    assert event.ticker == _TICKER
    assert event.stop_loss == 40
    assert event.take_profit == 50


def test_signal_money_fields_are_decimal(strategy):
    """D-22: strategy float prices enter the SignalEvent via to_money — the
    event carries Decimal money fields (price/stop_loss/take_profit), equal to
    Decimal(str(float)) of the strategy's float inputs (numerically inert)."""
    from decimal import Decimal
    from itrader.core.money import to_money

    strat, q = strategy
    strat.buy("SOLUSDT", 40.5, 50.25)

    event: SignalEvent = q.get(False)

    assert isinstance(event.price, Decimal)
    assert isinstance(event.stop_loss, Decimal)
    assert isinstance(event.take_profit, Decimal)
    # last close in the fixture bar is 105 (float) -> to_money string path
    assert event.price == to_money(105.0)
    assert event.stop_loss == to_money(40.5)
    assert event.take_profit == to_money(50.25)
    # quantity stays None (D-10) — the order/risk layer sizes the signal
    assert event.quantity is None


def test_sell_signal(strategy):
    """Generate a SELL signal with the ``sell()`` method of the Strategy object."""
    strat, q = strategy
    strat.sell("SOLUSDT", 40, 50)

    event: SignalEvent = q.get(False)

    assert isinstance(event, SignalEvent)
    assert event.strategy_id == strat.strategy_id
    assert event.action is Side.SELL
    assert event.order_type is OrderType.MARKET
    assert event.ticker == _TICKER
    assert event.stop_loss == 40
    assert event.take_profit == 50
