"""Intent-contract tests for the pure-alpha Strategy ABC (07-04, D-12/D-22/M5-09).

The strategy is a pure function: ``generate_signal(ticker, bars) ->
SignalIntent | None`` — no queue, no event construction, no portfolio
knowledge. The handler (``StrategiesHandler.calculate_signals``) owns
stamping, policy attachment, per-portfolio fan-out, and enqueueing.

Covered behaviors:

- pure-function tests on ``SMA_MACD_strategy.generate_signal`` with
  hand-engineered synthetic OHLC frames (D-22): a bullish SMA/MACD
  crossover returns ``SignalIntent(action=Side.BUY)``; a too-short frame
  returns ``None``.
- handler-side fan-out: one subscribed portfolio -> exactly one
  ``SignalEvent`` stamped from the bar event; two portfolios -> two events.
- the D-08 registration guard: ``add_strategy`` rejects a LONG_SHORT
  strategy loudly (margin milestone required).
- the WR-12 sparse-ticker guard: a missing bar for the ticker produces no
  signal and no raise.
"""

from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue

import numpy as np
import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import OrderType, Side
from itrader.core.money import to_money
from itrader.core.sizing import (
    FractionOfCash,
    SignalIntent,
    TradingDirection,
)
from itrader.events_handler.events import BarEvent, SignalEvent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.SMA_MACD_strategy import SMA_MACD_strategy
from itrader.strategy_handler.strategies_handler import StrategiesHandler


_TICKER = "BTCUSDT"
_PORTFOLIO_A = 1
_PORTFOLIO_B = 2
# Midnight-aligned, tz-aware 1d tick: the check_timeframe seam is
# midnight-relative on the UTC grid and expects tz-aware times (D-06).
_EVENT_TIME = datetime(2024, 1, 2, tzinfo=UTC)


# --- synthetic frames (D-22: hand-engineered, construction documented) -------


def _bullish_crossover_frame() -> pd.DataFrame:
    """A 120-bar daily close frame engineered for the SMA_MACD BUY trigger.

    Construction (verified numerically against the ta library):

    - a steady linear uptrend (100 -> 220 over 120 bars) keeps the short
      SMA (50) above the long SMA (100) at the last bar — the trend filter
      passes;
    - a shallow dip over the last ~8 bars (−14 linear) drives the MACD
      histogram (6/12/3) negative at bar -2;
    - a sharp +30 bounce on the final bar flips the histogram back >= 0 at
      bar -1 — the (hist[-1] >= 0 and hist[-2] < 0) bullish crossover.
    """
    base = np.linspace(100.0, 220.0, 120)
    prices = base.copy()
    prices[-9:-1] = prices[-9] - np.linspace(0, 14, 8)  # the dip
    prices[-1] = prices[-2] + 30  # the bounce that crosses the histogram
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    return pd.DataFrame({"close": prices}, index=idx)


def _short_frame() -> pd.DataFrame:
    """A frame shorter than SMA_MACD's max_window (100) — must return None."""
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame({"close": np.linspace(100.0, 110.0, 10)}, index=idx)


# --- pure-function intent tests (D-22) ---------------------------------------


def test_bullish_crossover_returns_buy_intent():
    """A synthetic bullish SMA/MACD crossover frame yields a BUY SignalIntent."""
    strategy = SMA_MACD_strategy(timeframe="1d", tickers=[_TICKER])

    intent = strategy.generate_signal(_TICKER, _bullish_crossover_frame())

    assert isinstance(intent, SignalIntent)
    assert intent.action is Side.BUY
    assert intent.ticker == _TICKER
    # No explicit SL/TP declared by SMA_MACD — the handler stamps the
    # legacy to_money(0) defaults at SignalEvent construction.
    assert intent.stop_loss is None
    assert intent.take_profit is None
    # Full exit is the structural default (D-07).
    assert intent.exit_fraction == Decimal("1")


def test_too_short_frame_returns_none():
    """A frame shorter than max_window yields no intent (pure no-op)."""
    strategy = SMA_MACD_strategy(timeframe="1d", tickers=[_TICKER])

    assert strategy.generate_signal(_TICKER, _short_frame()) is None


def test_golden_declarations_are_typed():
    """SMA_MACD declares the golden typed policy (D-03/D-08/D-10)."""
    strategy = SMA_MACD_strategy(timeframe="1d", tickers=[_TICKER])

    assert strategy.sizing_policy == FractionOfCash(Decimal("0.95"))
    assert strategy.direction is TradingDirection.LONG_ONLY
    assert strategy.allow_increase is False


def test_buy_sell_sugar_builds_intents():
    """buy()/sell() are thin sugar: SignalIntent only, to_money entry for SL/TP."""
    strategy = SMA_MACD_strategy(timeframe="1d", tickers=[_TICKER])

    buy = strategy.buy(_TICKER, sl=40.5, tp=50.25)
    sell = strategy.sell(_TICKER)

    assert buy.action is Side.BUY
    # D-04 string path: to_money(40.5) == Decimal("40.5"), no float artifact.
    assert buy.stop_loss == to_money(40.5)
    assert buy.take_profit == to_money(50.25)
    assert sell.action is Side.SELL
    assert sell.stop_loss is None and sell.take_profit is None


# --- handler-side fan-out (real StrategiesHandler + queue + stub feed) -------


class _AlwaysBuyStrategy(Strategy):
    """Minimal concrete strategy that always signals BUY (fan-out probe)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("sizing_policy", FractionOfCash(Decimal("0.95")))
        super().__init__("always_buy", "1d", [_TICKER], **kwargs)
        self.max_window = 1

    def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
        return self.buy(ticker)


class _StubFeed:
    """BarFeed stand-in whose window() returns a fixed synthetic frame."""

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def window(self, ticker, timeframe, max_window, asof) -> pd.DataFrame:
        return self._frame


def _bar_event(time=_EVENT_TIME, ticker=_TICKER) -> BarEvent:
    return BarEvent(time=time, bars={
        ticker: Bar(time=time, open=Decimal("100"), high=Decimal("110"),
                    low=Decimal("90"), close=Decimal("105"), volume=Decimal("1000")),
    })


@pytest.fixture
def handler_env():
    """A real StrategiesHandler wired to a queue and a stub feed.

    Drains the queue on teardown (test_on_signal.py precedent) so nothing
    bleeds across tests under ``filterwarnings=["error"]``.
    """
    q = Queue()
    handler = StrategiesHandler(q, _StubFeed(_short_frame()))

    yield handler, q

    while not q.empty():
        q.get_nowait()


def test_fan_out_single_portfolio_stamps_event(handler_env):
    """One subscribed portfolio -> exactly one SignalEvent, stamped handler-side."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)
    event = _bar_event()

    handler.calculate_signals(event)

    signal: SignalEvent = q.get(False)
    assert q.empty()  # exactly one
    assert isinstance(signal, SignalEvent)
    # The handler stamps time/price from the bar event (relocated construction).
    assert signal.time == event.time
    assert signal.price == to_money(event.bars[_TICKER].close)
    # Absent SL/TP preserves the legacy default exactly: to_money(0).
    assert signal.stop_loss == Decimal("0")
    assert signal.take_profit == Decimal("0")
    # Typed policy/direction attached from the strategy object (D-01).
    assert signal.sizing_policy == FractionOfCash(Decimal("0.95"))
    assert signal.direction is TradingDirection.LONG_ONLY
    assert signal.allow_increase is False
    assert signal.exit_fraction == Decimal("1")
    assert signal.action is Side.BUY
    assert signal.order_type is OrderType.MARKET
    assert signal.ticker == _TICKER
    assert signal.portfolio_id == _PORTFOLIO_A
    assert signal.strategy_id == strategy.strategy_id
    # The order/risk layer sizes the signal (D-10) — quantity stays None.
    assert signal.quantity is None


def test_fan_out_two_portfolios_two_events(handler_env):
    """Two subscribed portfolios -> two SignalEvents (fan-out preserved)."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    strategy.subscribe_portfolio(_PORTFOLIO_B)
    handler.add_strategy(strategy)

    handler.calculate_signals(_bar_event())

    signals = []
    while not q.empty():
        signals.append(q.get(False))
    assert len(signals) == 2
    assert [s.portfolio_id for s in signals] == [_PORTFOLIO_A, _PORTFOLIO_B]
    # Same intent fanned out — identical stamping on both events.
    assert {s.action for s in signals} == {Side.BUY}
    assert {s.strategy_id for s in signals} == {strategy.strategy_id}


def test_sparse_ticker_guard_skips_silently(handler_env):
    """WR-12: a bar missing for the ticker -> no signal, no raise."""
    handler, q = handler_env
    strategy = _AlwaysBuyStrategy()
    strategy.subscribe_portfolio(_PORTFOLIO_A)
    handler.add_strategy(strategy)
    # The bar event carries a DIFFERENT ticker — the strategy's is absent.
    event = _bar_event(ticker="ETHUSDT")

    handler.calculate_signals(event)  # must not raise

    assert q.empty()


def test_long_short_registration_rejected(handler_env):
    """D-08: registering a LONG_SHORT strategy raises the documented error."""
    handler, _q = handler_env
    strategy = _AlwaysBuyStrategy(direction=TradingDirection.LONG_SHORT)

    with pytest.raises(ValueError, match="LONG_SHORT requires the margin"):
        handler.add_strategy(strategy)

    assert handler.strategies == []
