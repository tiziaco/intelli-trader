"""Strategy.update — the CR-01-strategy ``_last_bar_time`` idempotency cursor (07-10 Task 3).

``Strategy.update`` used to unconditionally increment ``_bar_counts``, append to
``_recent_closes``, and advance the O(1) indicator handles — so a CR-02 next-poll
FAILED-retry re-warming an overlapping window through ``StrategiesHandler.on_bars_loaded``
(or a live reconnect resend of a duplicate bar) inflated the count past ``min_period`` OFF
DUPLICATES and advanced the recurrences over repeated values (garbage indicator state → a
symbol tradeable on corruption, CR-01). The fix adds a per-symbol ``_last_bar_time`` cursor
and rejects ``bar.time <= last`` BEFORE any state mutation — ``==`` (duplicate) silently,
strict ``<`` (out-of-order) with a ``warning``.

Covered <behavior> cases:
  (i)   duplicate bar.time -> is_ready / bar_count / recent_closes / latest_bar unchanged,
        NO warning captured;
  (ii)  strictly-older bar.time -> warning captured + state unchanged;
  (iii) monotonic bars advance normally and eventually is_ready True;
  (iv)  evaluate(ticker, window) called TWICE with the same window succeeds both times
        (the second replay is NOT rejected — proving _reset_ticker cleared the cursor); a
        reset() then re-feed reproduces a fresh run.

Indentation is 4-SPACE (matched to tests/unit/strategy/). Warn-capture REQUIRES ``poetry
run pytest`` (not ``make test``, which disables logs).
"""

from __future__ import annotations

import logging
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA

pytestmark = pytest.mark.unit

_TICKER = "ETH/USDC"
_START_MS = 1704067200000  # 2024-01-01T00:00:00Z
_TF_MS = 86_400_000  # 1 day
_MIN_PERIOD = 3


class _SMA3Strategy(Strategy):
    """A minimal strategy with a SINGLE SMA(3) handle (min_period == 3)."""

    name = "SMA3"
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", _MIN_PERIOD)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return None


def _strategy() -> _SMA3Strategy:
    return _SMA3Strategy(timeframe="1d", tickers=[_TICKER])


def _bar(ts_ms: int, *, close: str = "100.0") -> Bar:
    return Bar(
        time=pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
        open=Decimal("100.0"),
        high=Decimal("101.0"),
        low=Decimal("99.0"),
        close=Decimal(close),
        volume=Decimal("10"),
    )


# --- (i) duplicate bar.time -> silent no-op ----------------------------------


def test_duplicate_bar_time_is_a_silent_noop(caplog: pytest.LogCaptureFixture) -> None:
    strat = _strategy()
    strat.update(_TICKER, _bar(_START_MS, close="100"))
    strat.update(_TICKER, _bar(_START_MS + _TF_MS, close="101"))

    count_before = strat.bar_count(_TICKER)
    closes_before = strat.recent_closes(_TICKER)
    latest_before = strat.latest_bar(_TICKER)
    ready_before = strat.is_ready(_TICKER)

    with caplog.at_level(logging.WARNING):
        # Re-deliver the SAME (t1) bar — a duplicate.
        strat.update(_TICKER, _bar(_START_MS + _TF_MS, close="999"))

    # State entirely unchanged — the duplicate was rejected before any mutation.
    assert strat.bar_count(_TICKER) == count_before
    assert strat.recent_closes(_TICKER) == closes_before
    assert strat.latest_bar(_TICKER) is latest_before
    assert strat.is_ready(_TICKER) == ready_before
    # No warning for a benign duplicate.
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]


# --- (ii) strictly-older bar.time -> warning + drop --------------------------


def test_strictly_older_bar_time_warns_and_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    strat = _strategy()
    for i in range(_MIN_PERIOD):  # 3 monotonic bars -> ready
        strat.update(_TICKER, _bar(_START_MS + i * _TF_MS, close=str(100 + i)))
    assert strat.is_ready(_TICKER) is True

    count_before = strat.bar_count(_TICKER)
    closes_before = strat.recent_closes(_TICKER)

    with caplog.at_level(logging.WARNING):
        strat.update(_TICKER, _bar(_START_MS - _TF_MS, close="50"))  # older than last

    # Dropped — state unchanged.
    assert strat.bar_count(_TICKER) == count_before
    assert strat.recent_closes(_TICKER) == closes_before
    assert strat.is_ready(_TICKER) is True
    # A warning WAS emitted (out-of-order bar).
    assert any("Out-of-order bar" in rec.getMessage() for rec in caplog.records)


# --- (iii) monotonic bars advance normally -----------------------------------


def test_monotonic_bars_advance_and_reach_ready() -> None:
    strat = _strategy()
    assert strat.is_ready(_TICKER) is False  # no bar yet

    for i in range(_MIN_PERIOD):
        strat.update(_TICKER, _bar(_START_MS + i * _TF_MS, close=str(100 + i)))

    assert strat.bar_count(_TICKER) == _MIN_PERIOD
    assert strat.is_ready(_TICKER) is True
    assert len(strat.recent_closes(_TICKER)) == _MIN_PERIOD


# --- (iv) evaluate() replay + reset() clear the cursor -----------------------


def _window(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"close": np.linspace(100.0, 100.0 + n, n)}, index=idx)


def test_second_evaluate_replay_of_same_window_succeeds() -> None:
    """A second evaluate() of the SAME window is not rejected (the cursor was cleared)."""
    strat = _strategy()
    window = _window(5)

    strat.evaluate(_TICKER, window)
    assert strat.is_ready(_TICKER) is True
    first_count = strat.bar_count(_TICKER)

    # Second replay of the SAME window — _reset_ticker cleared the cursor, so every
    # bar is accepted again (NOT rejected on `bar.time <= last`).
    strat.evaluate(_TICKER, window)
    assert strat.is_ready(_TICKER) is True
    assert strat.bar_count(_TICKER) == first_count  # replay rebuilt identical state


def test_reset_clears_cursor_and_refeed_is_fresh() -> None:
    """reset() clears the cursor so a re-feed of the same timestamps reproduces a fresh run."""
    strat = _strategy()
    for i in range(_MIN_PERIOD):
        strat.update(_TICKER, _bar(_START_MS + i * _TF_MS, close=str(100 + i)))
    assert strat.is_ready(_TICKER) is True

    strat.reset()
    assert strat.bar_count(_TICKER) == 0
    assert strat.is_ready(_TICKER) is False

    # Re-feed the SAME timestamps — not rejected (cursor cleared), fresh run.
    strat.update(_TICKER, _bar(_START_MS, close="100"))
    assert strat.bar_count(_TICKER) == 1
