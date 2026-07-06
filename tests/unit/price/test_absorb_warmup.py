"""LiveBarFeed.absorb_warmup — the non-emitting silent ring/L absorb (07-03, WR-02 / D-03 / OQ1).

Offline, socket-free tests for the warmup-before-subscribe ``L`` contract (RESEARCH OQ1). A
freshly-added universe symbol's ``BarsLoaded`` window is absorbed into the ring + last-delivered
stamp ``L`` WITHOUT putting a tradeable ``BarEvent`` on the queue, so:

  1. the ring is warmed + ``L`` is set from the historical window, with the queue left EMPTY;
  2. ``window()`` / ``newest_bar()`` reflect the absorbed history (the feed read-model is warm);
  3. the first subsequent live ``update()`` lands on the in-sequence branch (``t == L + tf``);
  4. a duplicate of the newest absorbed bar is DROPPED — proof ``L`` was set (a cold feed would
     have delivered it as a fresh first bar).

The feed is driven with the package ``_StubProvider`` (no socket); the input ``Bar`` tuple is
built directly (``BarsLoaded`` hands pre-built ``Bar``s, so ``absorb_warmup`` skips ``_build_bar``).
This directory is package-less (NO ``__init__.py``); indentation is 4-SPACE.
"""

from __future__ import annotations

import queue
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

pytestmark = pytest.mark.unit

_SYM = "BTC-USDT"
_TF = "1d"
_TF_DELTA = timedelta(days=1)
_TF_MS = int(_TF_DELTA.total_seconds() * 1000)
_START_MS = 1704067200000  # 2024-01-01T00:00:00Z — fixed literal, never wall-clock.


class _DepthConsumer:
    """Force a derived ``cache_capacity()`` so the ring holds the whole warmup window."""

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


def _bar(ts_ms: int, *, close: str = "42100.0") -> Bar:
    """Build one pre-built warmup ``Bar`` with a tz-aware pd.Timestamp open-time."""
    return Bar(
        time=pd.Timestamp(ts_ms, unit="ms", tz="UTC"),
        open=Decimal("42000.0"),
        high=Decimal("42500.0"),
        low=Decimal("41800.0"),
        close=Decimal(close),
        volume=Decimal("1200.5"),
    )


def _closed_bar(ts_ms: int, *, close: str = "42100.0") -> dict[str, Any]:
    """A ``ClosedBar`` dict for the live ``update()`` path (post-warmup live bars)."""
    return {
        "ts": int(ts_ms),
        "open": Decimal("42000.0"),
        "high": Decimal("42500.0"),
        "low": Decimal("41800.0"),
        "close": Decimal(close),
        "volume": Decimal("1200.5"),
        "symbol": _SYM,
        "timeframe": _TF,
    }


def _make_feed(stub_provider: Any) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    feed = LiveBarFeed(provider=stub_provider, base_timeframe=_TF_DELTA)
    feed.register_raw_bar_consumer(_DepthConsumer(10))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def _warmup_bars(n: int) -> tuple[Bar, ...]:
    return tuple(_bar(_START_MS + i * _TF_MS) for i in range(n))


def test_absorb_warmup_warms_ring_and_L_without_emitting(stub_provider: Any) -> None:
    feed, q = _make_feed(stub_provider)
    bars = _warmup_bars(3)

    feed.absorb_warmup(_SYM, _TF, bars)

    # (1) queue stays EMPTY — no tradeable BarEvent during warmup (D-03b).
    assert q.qsize() == 0
    # Ring holds all absorbed bars; L == newest absorbed bar's time.
    assert list(feed._ring[(_SYM, _TF)]) == list(bars)
    assert feed._last_delivered[(_SYM, _TF)] == bars[-1].time
    assert feed._newest_bars[_SYM] == bars[-1]


def test_absorb_warmup_window_and_newest_bar_reflect_history(stub_provider: Any) -> None:
    feed, _q = _make_feed(stub_provider)
    bars = _warmup_bars(4)

    feed.absorb_warmup(_SYM, _TF, bars)

    # (2) newest_bar + window reflect the absorbed history (read-model is warm).
    assert feed.newest_bar(_SYM) == bars[-1]
    asof = bars[-1].time  # visible at the newest absorbed bar's tick
    frame = feed.window(_SYM, _TF_DELTA, max_window=10, asof=asof)
    assert len(frame) == 4
    assert float(bars[-1].close) == pytest.approx(frame["close"].iloc[-1])


def test_first_live_update_lands_in_sequence_after_absorb(stub_provider: Any) -> None:
    feed, q = _make_feed(stub_provider)
    bars = _warmup_bars(3)
    feed.absorb_warmup(_SYM, _TF, bars)
    newest_ts = _START_MS + 2 * _TF_MS

    # (3) the next in-sequence live bar (t == L + tf) delivers exactly one BarEvent and
    # advances L by one tf — the L-continuity proof (it was NOT a fresh first delivery).
    feed.update(_closed_bar(newest_ts + _TF_MS))

    assert q.qsize() == 1
    assert feed._last_delivered[(_SYM, _TF)] == pd.Timestamp(
        newest_ts + _TF_MS, unit="ms", tz="UTC")
    # Ring grew by exactly the one live bar (maxlen 10 not hit).
    assert len(feed._ring[(_SYM, _TF)]) == 4


def test_duplicate_of_newest_after_absorb_is_dropped_not_first_delivery(
    stub_provider: Any,
) -> None:
    feed, q = _make_feed(stub_provider)
    bars = _warmup_bars(3)
    feed.absorb_warmup(_SYM, _TF, bars)
    newest_ts = _START_MS + 2 * _TF_MS

    # (4) a re-send of the newest absorbed bar (t == L, identical OHLCV) hits the
    # duplicate branch and is DROPPED — a cold feed (L unset) would have delivered it as a
    # fresh first bar, so this proves absorb_warmup set L.
    feed.update(_closed_bar(newest_ts))

    assert q.qsize() == 0
    assert len(feed._ring[(_SYM, _TF)]) == 3  # unchanged — no delivery
