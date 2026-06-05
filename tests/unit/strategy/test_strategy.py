from datetime import datetime
from queue import Queue

import pandas as pd
import pytest

from itrader.strategy_handler.base import Strategy
from itrader.events_handler.event import SignalEvent, BarEvent


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
    assert event.action == "BUY"
    assert event.ticker == _TICKER
    assert event.stop_loss == 40
    assert event.take_profit == 50


def test_sell_signal(strategy):
    """Generate a SELL signal with the ``sell()`` method of the Strategy object."""
    strat, q = strategy
    strat.sell("SOLUSDT", 40, 50)

    event: SignalEvent = q.get(False)

    assert isinstance(event, SignalEvent)
    assert event.strategy_id == strat.strategy_id
    assert event.action == "SELL"
    assert event.ticker == _TICKER
    assert event.stop_loss == 40
    assert event.take_profit == 50
