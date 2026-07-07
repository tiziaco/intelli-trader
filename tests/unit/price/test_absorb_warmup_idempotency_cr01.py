"""LiveBarFeed.absorb_warmup — the CR-01-feed ``_last_delivered`` idempotency guard (07-10 Task 2).

``absorb_warmup`` used to do an unconditional ``ring.append(bar)`` with NO timestamp dedup,
so a CR-02 next-poll FAILED-retry re-delivering a largely-overlapping warmup window
appended DUPLICATE ``bar.time`` bars into the bounded ring (CR-01). The fix reuses the
EXISTING ``_last_delivered`` cursor ``_deliver`` already honors: a re-delivered bar whose
``pd.Timestamp(bar.time) <= cursor`` is dropped BEFORE ``ring.append`` — ``==`` (duplicate)
silently, strict ``<`` (out-of-order) with a ``warning``.

Covered <behavior> cases:
  (i)    two overlapping absorbs -> ring has NO duplicate bar.time, only the genuinely-new
         bars are appended, the ring stays strictly increasing;
  (ii)   a strictly-older re-delivered bar is DROPPED and a warning is captured;
  (iii-a) a same-timestamp BYTE-IDENTICAL duplicate is dropped with NO warning captured;
  (iii-b) a same-timestamp bar with DIFFERENT OHLCV is a forward-only revision (WR-01):
          dropped with NO state mutation but a "Revision dropped" WARNING is captured;
  (iii-c) an off-grid warmup bar (last < bt < last + tf, WR-02) is dropped with an
          "Off-grid warmup bar" WARNING and does NOT advance the _last_delivered cursor;
  (iv)   a first clean absorb appends ALL bars unchanged (regression vs test_absorb_warmup).

Offline / socket-free (the package ``stub_provider`` fixture; a ``_DepthConsumer`` forces a
ring capacity that holds the whole window). This directory is package-less (NO
``__init__.py``); indentation is 4-SPACE. Warn-capture tests REQUIRE ``poetry run pytest``
(not ``make test``, which disables logs).
"""

from __future__ import annotations

import logging
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


def _make_feed(stub_provider: Any) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    feed = LiveBarFeed(provider=stub_provider, base_timeframe=_TF_DELTA)
    feed.register_raw_bar_consumer(_DepthConsumer(10))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def _warmup_bars(n: int) -> tuple[Bar, ...]:
    return tuple(_bar(_START_MS + i * _TF_MS, close=str(42100 + i)) for i in range(n))


def _ring_times(feed: LiveBarFeed) -> list[pd.Timestamp]:
    return [bar.time for bar in feed._ring[(_SYM, _TF)]]


# --- (i) overlapping re-absorb -> no duplicate bar.time ----------------------


def test_overlapping_reabsorb_no_duplicate_only_new_bars_appended(
    stub_provider: Any,
) -> None:
    feed, _q = _make_feed(stub_provider)
    first = _warmup_bars(2)
    feed.absorb_warmup(_SYM, _TF, first)

    # A partially-overlapping re-fetch: the 2 originals + 2 genuinely-new later bars.
    second = _warmup_bars(4)
    feed.absorb_warmup(_SYM, _TF, second)

    times = _ring_times(feed)
    # Only the 2 genuinely-new bars were appended (the overlap was deduped).
    assert len(times) == 4
    assert len(set(times)) == len(times)  # no duplicate bar.time
    assert times == sorted(times)
    assert all(a < b for a, b in zip(times, times[1:]))  # strictly increasing
    # L advanced to the newest genuinely-new bar.
    assert feed._last_delivered[(_SYM, _TF)] == second[-1].time


def test_fully_overlapping_reabsorb_is_a_noop(stub_provider: Any) -> None:
    feed, _q = _make_feed(stub_provider)
    bars = _warmup_bars(3)
    feed.absorb_warmup(_SYM, _TF, bars)

    # Re-deliver the SAME window (fully-overlapping retry) — every bar is a duplicate.
    feed.absorb_warmup(_SYM, _TF, bars)

    assert _ring_times(feed) == [b.time for b in bars]  # unchanged, no duplicates


# --- (ii) strictly-older bar -> drop + WARNING -------------------------------


def test_strictly_older_bar_drops_and_warns(
    stub_provider: Any, caplog: pytest.LogCaptureFixture
) -> None:
    feed, _q = _make_feed(stub_provider)
    feed.absorb_warmup(_SYM, _TF, _warmup_bars(3))  # L = bar[2].time
    before = _ring_times(feed)

    older = _bar(_START_MS - _TF_MS)  # strictly < L
    with caplog.at_level(logging.WARNING):
        feed.absorb_warmup(_SYM, _TF, (older,))

    # Dropped — no state mutation.
    assert _ring_times(feed) == before
    # A warning WAS emitted (out-of-order warmup bar).
    assert any(
        "Out-of-order warmup bar" in rec.getMessage() for rec in caplog.records
    )


# --- (iii-a) same-timestamp BYTE-IDENTICAL duplicate -> drop, NO warning ------


def test_same_timestamp_duplicate_drops_silently(
    stub_provider: Any, caplog: pytest.LogCaptureFixture
) -> None:
    feed, _q = _make_feed(stub_provider)
    bars = _warmup_bars(3)
    feed.absorb_warmup(_SYM, _TF, bars)
    before = _ring_times(feed)

    # BYTE-IDENTICAL to the bar already ringed at that ts (_warmup_bars(3)[2] has
    # close=str(42100+2)="42102"): a benign overlap re-fetch, NOT a revision.
    duplicate = _bar(_START_MS + 2 * _TF_MS, close="42102")  # == L, same OHLCV
    with caplog.at_level(logging.WARNING):
        feed.absorb_warmup(_SYM, _TF, (duplicate,))

    # Dropped silently — ring unchanged, NO warning captured.
    assert _ring_times(feed) == before
    assert not [rec for rec in caplog.records if rec.levelno >= logging.WARNING]


# --- (iii-b) same-timestamp DIFFERENT OHLCV -> forward-only revision WARN -----


def test_same_timestamp_revision_warns(
    stub_provider: Any, caplog: pytest.LogCaptureFixture
) -> None:
    feed, _q = _make_feed(stub_provider)
    feed.absorb_warmup(_SYM, _TF, _warmup_bars(3))  # L = bar[2].time, close="42102"
    before = _ring_times(feed)

    # Same ts as L but DIFFERENT close — a genuine venue-side revision (D-07).
    revision = _bar(_START_MS + 2 * _TF_MS, close="99999")
    with caplog.at_level(logging.WARNING):
        feed.absorb_warmup(_SYM, _TF, (revision,))

    # Forward-only: dropped with NO state mutation (indicator state never rewound).
    assert _ring_times(feed) == before
    assert feed._last_delivered[(_SYM, _TF)] == before[-1]
    # A "Revision dropped" WARNING surfaces the conflicting venue data.
    assert any(
        "Revision dropped" in rec.getMessage() for rec in caplog.records
    )


# --- (iii-c) off-grid warmup bar (last < bt < last + tf) -> drop + WARN --------


def test_off_grid_warmup_bar_dropped_and_warns(
    stub_provider: Any, caplog: pytest.LogCaptureFixture
) -> None:
    feed, _q = _make_feed(stub_provider)
    bars = _warmup_bars(3)
    feed.absorb_warmup(_SYM, _TF, bars)  # L at _START_MS + 2*_TF_MS
    before = _ring_times(feed)

    # Strictly between L and L + tf — an off-grid timestamp that would set L off
    # the tf-grid and make every subsequent live update() spuriously trip the gap.
    off_grid = _bar(_START_MS + 2 * _TF_MS + _TF_MS // 2)
    with caplog.at_level(logging.WARNING):
        feed.absorb_warmup(_SYM, _TF, (off_grid,))

    # Dropped — ring unchanged AND the cursor did NOT advance off-grid.
    assert _ring_times(feed) == before
    assert feed._last_delivered[(_SYM, _TF)] == bars[2].time
    assert any(
        "Off-grid warmup bar" in rec.getMessage() for rec in caplog.records
    )


# --- (iv) first clean absorb appends all bars unchanged ----------------------


def test_first_clean_absorb_appends_all_bars_unchanged(stub_provider: Any) -> None:
    feed, q = _make_feed(stub_provider)
    bars = _warmup_bars(4)

    feed.absorb_warmup(_SYM, _TF, bars)

    # Byte-identical to the pre-fix clean-warmup contract: all bars in the ring,
    # L at the newest, newest_bar set, queue empty (no tradeable BarEvent).
    assert _ring_times(feed) == [b.time for b in bars]
    assert feed._last_delivered[(_SYM, _TF)] == bars[-1].time
    assert feed._newest_bars[_SYM] == bars[-1]
    assert q.qsize() == 0
