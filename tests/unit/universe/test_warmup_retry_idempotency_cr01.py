"""CR-01 headline regression — warmup re-delivery must be idempotent by ``bar.time``.

The confirmed reachability path (07-09-REVIEW.md CR-01 / the design-of-record
``warmup-retry-nonidempotent-tradeable-corrupted-cr01.md``): a FIRST warmup window
shorter than the strategy ``min_period`` marks the symbol not-warm (WR-02 would mark it
FAILED) → the CR-02 next-poll FAILED-retry re-delivers a largely-overlapping warmup
window into BOTH re-warm seams (``LiveBarFeed.absorb_warmup`` AND ``Strategy.update`` via
``StrategiesHandler.on_bars_loaded``). Neither seam is timestamp-guarded on the current
code, so:

  1. ``absorb_warmup`` re-appends the same bars → duplicate ``bar.time`` in the bounded
     ring → ``window()`` returns a duplicate-corrupted trailing window;
  2. ``strategy.update`` re-feeds the overlapping bars → ``_bar_counts`` crosses
     ``min_period`` OFF DUPLICATES → ``is_warm`` flips True → the symbol becomes
     tradeable in LIVE on garbage indicator state.

This file drives that path end-to-end with REAL seams (a real ``LiveBarFeed`` + a real
``StrategiesHandler.is_warm`` over a real small-``min_period`` ``Strategy`` — NOT stubs)
so the corruption is genuine. Authored RED-FIRST (07-10 Task 1): against the CURRENT
unfixed code, variant (i) FAILS (the ring gains duplicate ``bar.time`` and ``is_warm``
flips True off duplicates). Tasks 2-4 (the ``_last_delivered`` feed guard + the
``_last_bar_time`` strategy guard + the Level-2 retry policy) turn it GREEN.

Offline / socket-free. This directory is package-less (NO ``__init__.py``); indentation
is 4-SPACE (matched to the ``tests/unit/universe`` tree). Respects
``filterwarnings=["error"]`` (no warnings expected on the idempotent post-fix path).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from queue import Queue

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.events_handler.events import BarsLoaded
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA
from itrader.strategy_handler.storage import InMemorySignalStore
from itrader.strategy_handler.strategies_handler import StrategiesHandler

pytestmark = pytest.mark.unit

_SYM = "ETH/USDC"
_TF = "1d"
_TF_DELTA = timedelta(days=1)
_TF_MS = int(_TF_DELTA.total_seconds() * 1000)
_START_MS = 1704067200000  # 2024-01-01T00:00:00Z — fixed literal, never wall-clock.
_MIN_PERIOD = 3  # SMA(window=3) → is_ready at count >= 3.


class _DepthConsumer:
    """Force a derived ``cache_capacity()`` so the ring holds the whole warmup window.

    Without a registered raw-bar consumer ``cache_capacity()`` is the newest-bar floor
    (depth 1) and the ring would evict everything but the last bar — masking the
    duplicate-append corruption this regression is meant to catch.
    """

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


class _SMA3Strategy(Strategy):
    """A minimal warmup-warmable strategy with a SINGLE SMA(3) handle (min_period == 3).

    Mirrors the real ``SMAMACDStrategy`` authoring surface (class-attr policy/direction,
    ``init`` declaring an indicator recipe) but with a tiny warmup so a 2-bar first
    window is genuinely short and a 4-bar window genuinely crosses. ``generate_signal``
    is inert — this regression only exercises warmth (``is_ready`` / ``is_warm``).
    """

    name = "SMA3"
    sizing_policy = FractionOfCash(Decimal("0.95"))
    direction = TradingDirection.LONG_ONLY

    def init(self) -> None:
        self.sma = self.indicator(SMA, "close", _MIN_PERIOD)

    def generate_signal(self, ticker: str) -> SignalIntent | None:
        return None


def _bar(ts_ms: int, *, close: str = "100.0") -> Bar:
    """One warmup ``Bar`` with a tz-aware pd.Timestamp open-time (matches BarsLoaded)."""
    return Bar(
        time=pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
        open=Decimal("100.0"),
        high=Decimal("101.0"),
        low=Decimal("99.0"),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def _bars(n: int) -> tuple[Bar, ...]:
    """N strictly-increasing (one tf apart) warmup bars, distinct closes per index."""
    return tuple(
        _bar(_START_MS + i * _TF_MS, close=str(100 + i)) for i in range(n)
    )


def _feed() -> LiveBarFeed:
    feed = LiveBarFeed(provider=None, base_timeframe=_TF_DELTA)
    feed.register_raw_bar_consumer(_DepthConsumer(10))
    feed.bind(Queue(), [_SYM])
    return feed


def _strategies_handler(feed: LiveBarFeed) -> StrategiesHandler:
    handler = StrategiesHandler(
        global_queue=Queue(),
        feed=feed,
        signal_store=InMemorySignalStore(),
    )
    strategy = _SMA3Strategy(timeframe=_TF, tickers=[_SYM])
    handler.add_strategy(strategy)
    return handler


def _warm_both_seams(
    feed: LiveBarFeed, handler: StrategiesHandler, bars: tuple[Bar, ...]
) -> None:
    """Feed a warmup window through BOTH live seams exactly as the pipeline does."""
    feed.absorb_warmup(_SYM, _TF, bars)
    handler.on_bars_loaded(
        BarsLoaded(time=bars[-1].time, symbol=_SYM, timeframe=_TF, bars=bars)
    )


def _ring_times(feed: LiveBarFeed) -> list[pd.Timestamp]:
    return [bar.time for bar in feed._ring[(_SYM, _TF)]]


def test_first_short_warmup_leaves_symbol_not_warm() -> None:
    """Precondition: a 2-bar first warmup (< min_period 3) leaves the symbol not-warm.

    This is the WR-02 MISS state that marks the symbol FAILED and triggers the CR-02
    retry — the not-yet-warm entry condition for the corruption path.
    """
    feed = _feed()
    handler = _strategies_handler(feed)

    short_bars = _bars(2)  # 2 < min_period 3
    _warm_both_seams(feed, handler, short_bars)

    assert handler.is_warm(_SYM) is False  # CR-01 precondition: not yet warm
    assert _ring_times(feed) == [b.time for b in short_bars]


def test_fully_overlapping_rewarm_no_duplicate_ring_and_not_warm() -> None:
    """CR-01 variant (i): a FULLY-overlapping re-fetch (same 2 short bars) must be a no-op.

    RED on the current code: ``absorb_warmup`` re-appends the 2 bars (ring len 4 with
    duplicate ``bar.time``) and ``strategy.update`` re-counts them (count 4 >= 3 →
    ``is_warm`` flips True → tradeable on duplicates). GREEN after Tasks 2-4: the
    re-delivered bars are dropped by the monotonic cursors, so the ring holds NO
    duplicate ``bar.time`` and ``is_warm`` stays False (the symbol stays not-tradeable
    until GENUINELY warm).
    """
    feed = _feed()
    handler = _strategies_handler(feed)
    short_bars = _bars(2)

    # First warmup (short) → not warm.
    _warm_both_seams(feed, handler, short_bars)
    assert handler.is_warm(_SYM) is False

    # CR-02 retry: the SAME 2 short bars are re-delivered (fully-overlapping re-fetch).
    _warm_both_seams(feed, handler, short_bars)

    # CR-01 headline — ring holds NO duplicate bar.time (idempotent absorb).
    times = _ring_times(feed)
    assert len(times) == 2
    assert len(set(times)) == len(times)  # all unique — no duplicate bar.time
    # CR-01 headline — is_warm did NOT flip True off duplicates (still not tradeable).
    assert handler.is_warm(_SYM) is False
    # No rewind / duplicate-corrupted trailing window: strictly increasing.
    assert times == sorted(times)
    assert all(a < b for a, b in zip(times, times[1:]))


def test_partially_overlapping_rewarm_crosses_on_genuine_bars_only() -> None:
    """CR-01 variant (ii): a PARTIALLY-overlapping re-fetch crosses on GENUINE bars.

    The retry re-delivers a LONGER window (the 2 originals + 2 genuinely-new later bars).
    Post-fix: the 2 overlapping bars are dropped, the 2 new bars are appended, the ring
    has NO duplicate ``bar.time`` (len 4, unique) and ``is_warm`` becomes True — it
    crossed ``min_period`` on GENUINE bars, not duplicates. RED on the current code (ring
    len 6 with duplicate ``bar.time``).
    """
    feed = _feed()
    handler = _strategies_handler(feed)
    short_bars = _bars(2)

    _warm_both_seams(feed, handler, short_bars)
    assert handler.is_warm(_SYM) is False

    # Retry re-fetch = the 2 originals + 2 genuinely-new later bars (4 total).
    longer_bars = _bars(4)
    _warm_both_seams(feed, handler, longer_bars)

    times = _ring_times(feed)
    assert len(times) == 4
    assert len(set(times)) == len(times)  # unique — the overlap was deduped
    assert times == sorted(times)
    assert all(a < b for a, b in zip(times, times[1:]))
    # Crossed min_period on GENUINE bars → now legitimately warm + tradeable.
    assert handler.is_warm(_SYM) is True
