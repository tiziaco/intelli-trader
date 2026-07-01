"""Unit matrix for LiveBarFeed — FEED-01/02/04 (Phase 3 / 03-02).

Offline, socket-free: drives ``update()`` with synthetic ``ClosedBar`` dicts (the
shared ``tests/unit/price/conftest.py`` fixtures) + a real ``queue.Queue``, and
asserts on the drained ``BarEvent`` sequence. NO aiohttp, NO asyncio, NO wall-clock
(RESEARCH Pitfall 4) — every ``ts`` is a fixed epoch-ms literal so runs are
byte-reproducible.

- FEED-01: ``deque(maxlen=cache_capacity())`` ring per ``(symbol, timeframe)`` (D-09).
- FEED-02: tz-aware venue-open ``BarEvent.time``; single-ticker payload (D-04);
  ``window()`` completed-bars-only cutoff (rule 4).
- FEED-04 (Task 2): the monotonic-forward-only taxonomy — in-sequence / gap /
  duplicate / revision / stale (D-06/D-07).

Indentation is 4-SPACE (matched to the ``price_handler/feed`` tree).
"""

import queue
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

import pandas as pd
import pytest

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

pytestmark = pytest.mark.unit

_SYM = "BTC-USDT"
_TF = "1d"
_TF_DELTA = timedelta(days=1)
_TF_MS = int(_TF_DELTA.total_seconds() * 1000)
# Fixed byte-reproducible epoch-ms literal (2024-01-01T00:00:00Z) — matches the
# conftest ``closed_bar`` default so ts arithmetic is deterministic.
_START_MS = 1704067200000


class _DepthConsumer:
    """Minimal ``RawBarConsumer`` forcing a derived ``cache_capacity()`` in tests."""

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


def make_feed(
    provider: Any = None,
    capacity: Optional[int] = None,
) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    """Build a queue-bound ``LiveBarFeed``; optionally force a ring capacity."""
    feed = LiveBarFeed(provider=provider, base_timeframe=_TF_DELTA)
    if capacity is not None:
        feed.register_raw_bar_consumer(_DepthConsumer(capacity))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def drain(q: "queue.Queue[Any]") -> list[Any]:
    events: list[Any] = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 1_000_000)


# ---------------------------------------------------------------------------
# Task 1 — skeleton + read-model surface (FEED-01/02)
# ---------------------------------------------------------------------------


def test_set_provider_assigns() -> None:
    """set_provider is the ONLY public post-construction provider write path (D-01/D-13)."""
    feed, _ = make_feed(provider=None)
    assert feed._provider is None
    sentinel = object()
    feed.set_provider(sentinel)
    assert feed._provider is sentinel


def test_generate_bar_event_dormant() -> None:
    """The live TIME route is a dormant no-op returning None (D-05)."""
    feed, _ = make_feed()
    te = TimeEvent(time=pd.Timestamp(_START_MS, unit="ms", tz="UTC"))
    assert feed.generate_bar_event(te) is None


def test_build_bar_decimal_edge(closed_bar: Callable[..., Any]) -> None:
    """Bar OHLCV are the exact Decimals from the ClosedBar — no float re-cast (D-14)."""
    feed, _ = make_feed()
    cb = closed_bar(
        open="42000.5", high="42600.25", low="41000.1",
        close="42100.75", volume="1234.5",
    )
    t = pd.Timestamp(cb["ts"], unit="ms", tz="UTC")
    bar = feed._build_bar(t, cb)
    assert isinstance(bar.open, Decimal)
    assert bar.open == Decimal("42000.5")
    assert bar.close == Decimal("42100.75")
    assert bar.volume == Decimal("1234.5")
    assert bar.time == t


def test_emit_time_tz_aware(closed_bar: Callable[..., Any]) -> None:
    """An in-sequence bar emits a tz-aware venue-open BarEvent.time == Bar.time."""
    feed, q = make_feed()
    cb = closed_bar()
    feed.update(cb)
    (event,) = drain(q)
    assert isinstance(event, BarEvent)
    expected = pd.Timestamp(cb["ts"], unit="ms", tz="UTC")
    assert event.time == expected
    assert event.time.tzinfo is not None
    bar = event.bars[_SYM]
    assert bar.time == expected
    assert bar.time.tzinfo is not None


def test_newest_bar_reads_last(closed_bar_sequence: Callable[..., Any]) -> None:
    """newest_bar(sym) is None before the first bar, then the last delivered Bar."""
    feed, _ = make_feed()
    assert feed.newest_bar(_SYM) is None
    seq = closed_bar_sequence(3)
    for cb in seq:
        feed.update(cb)
    newest = feed.newest_bar(_SYM)
    assert newest is not None
    assert newest.time == pd.Timestamp(seq[-1]["ts"], unit="ms", tz="UTC")


def test_ring_maxlen_evicts(closed_bar_sequence: Callable[..., Any]) -> None:
    """With cache_capacity()==3, feeding 5 in-sequence bars leaves the newest 3 (D-09)."""
    feed, _ = make_feed(capacity=3)
    seq = closed_bar_sequence(5)
    for cb in seq:
        feed.update(cb)
    ring = feed._ring[(_SYM, _TF)]
    assert ring.maxlen == 3
    assert len(ring) == 3
    times = [b.time for b in ring]
    assert times == [
        pd.Timestamp(seq[i]["ts"], unit="ms", tz="UTC") for i in (2, 3, 4)
    ]


def test_window_lookahead_cutoff(closed_bar_sequence: Callable[..., Any]) -> None:
    """window() returns completed bars only (rule 4), tz-aware; unknown ticker raises."""
    feed, _ = make_feed(capacity=10)
    seq = closed_bar_sequence(5)
    for cb in seq:
        feed.update(cb)
    asof = pd.Timestamp(seq[-1]["ts"], unit="ms", tz="UTC")
    frame = feed.window(_SYM, _TF_DELTA, max_window=10, asof=asof)
    # base == timeframe: all 5 bars stamped <= asof are visible.
    assert len(frame) == 5
    assert frame.index.tz is not None
    # A cutoff one bar earlier hides the last (forming-relative) bar.
    asof_earlier = pd.Timestamp(seq[-2]["ts"], unit="ms", tz="UTC")
    frame2 = feed.window(_SYM, _TF_DELTA, max_window=10, asof=asof_earlier)
    assert len(frame2) == 4
    with pytest.raises(MissingPriceDataError):
        feed.window("UNKNOWN", _TF_DELTA, max_window=10, asof=asof)


# ---------------------------------------------------------------------------
# Task 2 — the monotonic guard update() + D-06 taxonomy (FEED-02/04)
# ---------------------------------------------------------------------------


def test_in_sequence_delivers(closed_bar_sequence: Callable[..., Any]) -> None:
    """t == L + tf → appended, L advanced, exactly one BarEvent per bar."""
    feed, q = make_feed(capacity=10)
    seq = closed_bar_sequence(3)
    for cb in seq:
        feed.update(cb)
    events = drain(q)
    assert len(events) == 3
    assert [e.time for e in events] == [
        pd.Timestamp(cb["ts"], unit="ms", tz="UTC") for cb in seq
    ]
    assert feed._last_delivered[(_SYM, _TF)] == pd.Timestamp(
        seq[-1]["ts"], unit="ms", tz="UTC")


def test_first_bar_delivers(closed_bar: Callable[..., Any]) -> None:
    """L is None (first bar for a key) → delivered, no gap logic."""
    feed, q = make_feed()
    feed.update(closed_bar())
    assert len(drain(q)) == 1


def test_single_ticker_payload(closed_bar_sequence: Callable[..., Any]) -> None:
    """Every emitted BarEvent carries exactly one ticker (D-04)."""
    feed, q = make_feed(capacity=10)
    for cb in closed_bar_sequence(3):
        feed.update(cb)
    for e in drain(q):
        assert list(e.bars.keys()) == [_SYM]
        assert len(e.bars) == 1


def test_duplicate_drop(closed_bar: Callable[..., Any]) -> None:
    """t == L with identical values → dropped, NO emit, no state mutation."""
    feed, q = make_feed(capacity=10)
    feed.update(closed_bar())
    drain(q)
    ring_before = list(feed._ring[(_SYM, _TF)])
    l_before = feed._last_delivered[(_SYM, _TF)]
    feed.update(closed_bar())  # same ts, same OHLCV
    assert drain(q) == []
    assert list(feed._ring[(_SYM, _TF)]) == ring_before
    assert feed._last_delivered[(_SYM, _TF)] == l_before


def test_revision_forward_only(closed_bar: Callable[..., Any]) -> None:
    """t == L with DIFFERENT values → forward-only drop, NO emit, no mutation (D-07)."""
    feed, q = make_feed(capacity=10)
    feed.update(closed_bar())
    drain(q)
    ring_before = list(feed._ring[(_SYM, _TF)])
    newest_before = feed.newest_bar(_SYM)
    l_before = feed._last_delivered[(_SYM, _TF)]
    feed.update(closed_bar(close="99999.0"))  # same ts, different close
    assert drain(q) == []
    assert list(feed._ring[(_SYM, _TF)]) == ring_before
    assert feed.newest_bar(_SYM) is newest_before
    assert feed._last_delivered[(_SYM, _TF)] == l_before


def test_stale_reject(
    closed_bar_sequence: Callable[..., Any],
    closed_bar: Callable[..., Any],
) -> None:
    """t < L → rejected, NO emit, no state mutation."""
    feed, q = make_feed(capacity=10)
    seq = closed_bar_sequence(3)
    for cb in seq:
        feed.update(cb)
    drain(q)
    ring_before = list(feed._ring[(_SYM, _TF)])
    l_before = feed._last_delivered[(_SYM, _TF)]
    newest_before = feed.newest_bar(_SYM)
    feed.update(closed_bar(seq[0]["ts"] - _TF_MS))  # older than L
    assert drain(q) == []
    assert list(feed._ring[(_SYM, _TF)]) == ring_before
    assert feed._last_delivered[(_SYM, _TF)] == l_before
    assert feed.newest_bar(_SYM) is newest_before


def test_gap_backfill_then_deliver(
    stub_provider: Any,
    closed_bar: Callable[..., Any],
) -> None:
    """t > L + tf → interior backfill fetched + replayed, THEN t delivered (contiguous)."""
    feed, q = make_feed(provider=stub_provider, capacity=10)
    feed.update(closed_bar(_START_MS))
    drain(q)
    # Jump 3 tf ahead: interior missing = 2 bars (L+tf, L+2tf); t at L+3tf.
    t_ms = _START_MS + 3 * _TF_MS
    stub_provider.backfill_bars = [
        closed_bar(_START_MS + 1 * _TF_MS),
        closed_bar(_START_MS + 2 * _TF_MS),
    ]
    feed.update(closed_bar(t_ms))
    events = drain(q)
    # 2 interior + the t bar, contiguous by one tf, none skipped.
    assert [_ms(e.time) for e in events] == [
        _START_MS + 1 * _TF_MS,
        _START_MS + 2 * _TF_MS,
        _START_MS + 3 * _TF_MS,
    ]
    # Exactly one backfill call for the interior range [L+tf .. t-tf].
    assert len(stub_provider.calls) == 1
    call = stub_provider.calls[0]
    assert call["symbol"] == _SYM
    assert call["timeframe"] == _TF
    assert call["since"] == _START_MS + _TF_MS  # (L + tf) in ms
    assert call["limit"] == 2
