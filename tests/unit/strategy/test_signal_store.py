"""Signal-store capture tests (Plan 05-03, SIG-01/SIG-02, D-07..D-12).

These drive the REAL ``StrategiesHandler`` wired to a queue, a stub feed, and an
injected ``InMemorySignalStore``. They assert the per-intent, pre-fan-out
capture contract (D-09): exactly ONE ``SignalRecord`` per non-None intent
regardless of how many portfolios the intent fans out to, ZERO records for a
None intent, the record's fields mirror the intent/event, and the store's
query API (``by_strategy`` / ``by_ticker``) filters correctly.

Patterns mirror ``test_strategy.py`` (the ``_StubFeed`` + minimal concrete
strategy + queue-draining fixture). 4-space indentation (tests house style).
"""

from datetime import UTC, datetime
from decimal import Decimal
from queue import Queue

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import Side
from itrader.core.sizing import (
    FractionOfCash,
    SignalIntent,
    TradingDirection,
)
from itrader.events_handler.events import BarEvent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.config import BaseStrategyConfig
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler


_TICKER = "BTCUSDT"
_OTHER_TICKER = "ETHUSDT"
_PORTFOLIO_A = 1
_PORTFOLIO_B = 2
_PORTFOLIO_C = 3
_EVENT_TIME = datetime(2024, 1, 2, tzinfo=UTC)


def _stub_frame() -> pd.DataFrame:
    """A one-row frame — enough for a warmup=0 stub strategy to fire."""
    idx = pd.date_range("2024-01-01", periods=1, freq="D")
    return pd.DataFrame({"close": [100.0]}, index=idx)


class _StubFeed:
    """BarFeed stand-in whose window() returns a fixed synthetic frame."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def window(self, ticker, timeframe, max_window, asof) -> pd.DataFrame:
        return self._frame


class _AlwaysBuyStrategy(Strategy):
    """Minimal concrete strategy that always signals BUY (capture probe)."""

    def __init__(self, ticker: str = _TICKER) -> None:
        config = BaseStrategyConfig(
            timeframe="1d",
            tickers=[ticker],
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
        )
        super().__init__("always_buy", config)
        # warmup=0 (no gating); wide-enough max_window for the stub frame.
        self.max_window = 1

    def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
        return self.buy(ticker)


class _NeverSignalStrategy(Strategy):
    """Minimal concrete strategy that never signals (None-intent probe)."""

    def __init__(self, ticker: str = _TICKER) -> None:
        config = BaseStrategyConfig(
            timeframe="1d",
            tickers=[ticker],
            sizing_policy=FractionOfCash(Decimal("0.95")),
            direction=TradingDirection.LONG_ONLY,
        )
        super().__init__("never_signal", config)
        self.max_window = 1

    def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
        return None


def _bar_event(time=_EVENT_TIME, ticker=_TICKER) -> BarEvent:
    return BarEvent(time=time, bars={
        ticker: Bar(time=time, open=Decimal("100"), high=Decimal("110"),
                    low=Decimal("90"), close=Decimal("105"), volume=Decimal("1000")),
    })


@pytest.fixture
def store_env():
    """A real StrategiesHandler wired to a queue, stub feed, and signal store.

    Drains the queue on teardown so nothing bleeds across tests under
    ``filterwarnings=["error"]``.
    """
    q = Queue()
    store = InMemorySignalStore()
    handler = StrategiesHandler(q, _StubFeed(_stub_frame()), store)

    yield handler, q, store

    while not q.empty():
        q.get_nowait()


def test_store_injected_as_attribute(store_env):
    """The handler holds the injected store as ``self.signal_store`` (D-12)."""
    handler, _q, store = store_env
    assert handler.signal_store is store


def test_one_record_per_intent_regardless_of_portfolio_count(store_env):
    """D-09: capture once before fan-out — 3 portfolios still yield 1 record."""
    handler, _q, store = store_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    strategy.subscribe_portfolio(_PORTFOLIO_B)
    strategy.subscribe_portfolio(_PORTFOLIO_C)
    handler.add_strategy(strategy)

    handler.calculate_signals(_bar_event())

    records = store.get_all()
    assert len(records) == 1  # one intent -> one record, NOT one-per-portfolio
    assert isinstance(records[0], SignalRecord)
    # D-09: the record carries no portfolio_id.
    assert not hasattr(records[0], "portfolio_id")


def test_none_intent_writes_no_record(store_env):
    """A None intent writes ZERO records (capture is after the None continue)."""
    handler, _q, store = store_env
    strategy = _NeverSignalStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)

    handler.calculate_signals(_bar_event())

    assert store.get_all() == []


def test_record_fields_mirror_intent_and_event(store_env):
    """The record's (strategy_id, ticker, time, action) + config snapshot match."""
    handler, _q, store = store_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)
    event = _bar_event()

    handler.calculate_signals(event)

    record = store.get_all()[0]
    assert record.strategy_id == strategy.strategy_id
    assert record.ticker == _TICKER
    assert record.time == event.time
    assert record.action is Side.BUY
    # D-11: config is the strategy's frozen config, stored by reference.
    assert record.config is strategy.config
    # SIG-02: the snapshot is serializable to a dict at the read edge.
    assert isinstance(record.config.model_dump(), dict)
    # A fresh SignalId was defaulted (D-10).
    assert record.signal_id is not None


def test_by_strategy_and_by_ticker_filter(store_env):
    """SIG-02: query API filters by strategy id and by ticker (no cross-bleed)."""
    handler, _q, store = store_env
    strat_btc = _AlwaysBuyStrategy(ticker=_TICKER)
    strat_eth = _AlwaysBuyStrategy(ticker=_OTHER_TICKER)
    strat_btc.subscribe_portfolio(_PORTFOLIO_A)
    strat_eth.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strat_btc)
    handler.add_strategy(strat_eth)

    # One bar event carrying both tickers so both strategies fire once.
    event = BarEvent(time=_EVENT_TIME, bars={
        _TICKER: Bar(time=_EVENT_TIME, open=Decimal("100"), high=Decimal("110"),
                     low=Decimal("90"), close=Decimal("105"), volume=Decimal("1000")),
        _OTHER_TICKER: Bar(time=_EVENT_TIME, open=Decimal("50"), high=Decimal("55"),
                           low=Decimal("45"), close=Decimal("52"), volume=Decimal("500")),
    })
    handler.calculate_signals(event)

    assert len(store.get_all()) == 2

    btc_records = store.by_ticker(_TICKER)
    assert len(btc_records) == 1
    assert btc_records[0].ticker == _TICKER

    eth_records = store.by_ticker(_OTHER_TICKER)
    assert len(eth_records) == 1
    assert eth_records[0].ticker == _OTHER_TICKER

    btc_by_strategy = store.by_strategy(strat_btc.strategy_id)
    assert len(btc_by_strategy) == 1
    assert btc_by_strategy[0].strategy_id == strat_btc.strategy_id
    # No cross-strategy bleed (T-05-05).
    assert all(r.strategy_id == strat_btc.strategy_id for r in btc_by_strategy)
