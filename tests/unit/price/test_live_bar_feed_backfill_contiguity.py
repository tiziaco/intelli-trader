"""Loop-native gap backfill fails loud on a non-contiguous page (D-29 / WR-05).

The loop-native gap backfill (``LiveBarFeed._spawn_loop_native_gap_backfill`` ->
``_replay_and_deliver``) clamped the replayed interior only at the UPPER end and assumed the
venue page begins exactly at ``first_missing``. An UNDER-RETURNING page (one that omits the
earliest missing bar / starts one ``tf`` late) made the first replayed ``update(cb)`` re-enter
the gap branch and spawn ANOTHER loop-native backfill recursively, mid-replay (WR-05).

The fix (D-29):
- symmetric LOW clamp (drop replayed bars below ``since_ms``, mirroring the upper ``> last_ms``
  break);
- FAIL LOUD (typed ``MalformedDataError``) when the first in-range replayed bar is not exactly
  ``first_missing`` — the raise escalates through the provider's supervised-backfill error path
  to a connector halt rather than re-entering the gap branch;
- a ``_replaying_backfill`` re-entrancy guard: if ``update()`` detects a gap WHILE a replay is
  in progress it fails loud instead of spawning a nested backfill — the structural stop,
  independent of page shape.

These drive the PRODUCTION PREMISE (an under-returning page), not the happy-path replay: the
happy path is already covered by ``test_live_bar_feed_loop_native_backfill.py``.

A stub provider whose ``spawn_gap_backfill`` synchronously invokes the replay callback drives
the loop-native path; the whole thing runs inside ``asyncio.run`` so ``update()`` sees a running
loop (``_loop_native_backfill_available()`` is True) with no socket. 4-SPACE indentation.
"""

from __future__ import annotations

import asyncio
import queue
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

import pandas as pd
import pytest

from itrader.core.exceptions import MalformedDataError
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed

pytestmark = pytest.mark.unit

_SYM = "BTC-USDT"
_TF = "1d"
_TF_DELTA = timedelta(days=1)
_TF_MS = int(_TF_DELTA.total_seconds() * 1000)
_START_MS = 1704067200000  # 2024-01-01T00:00:00Z — fixed literal, never wall-clock.


class _DepthConsumer:
    """Force a derived ``cache_capacity()`` so the ring is large enough for the test."""

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


class _SyncSpawnProvider:
    """Provider stub whose ``spawn_gap_backfill`` synchronously invokes the replay callback.

    Mirrors the loop-native seam without a socket: the awaited fetch is pre-resolved to a
    canned page, and the callback is invoked inline (so a raise inside it propagates to the
    caller — mirroring production, where it fails the backfill task -> ``_on_gap_backfill_done``
    -> ``_halt_signal('connector-fatal')``). ``spawn_calls`` counts spawns to prove no nested
    backfill.
    """

    def __init__(self, page: list[dict[str, Any]]) -> None:
        self._page = page
        self.spawn_calls = 0

    def fetch_ohlcv_backfill(
        self, symbol: str, timeframe: str, limit: int | None = None,
    ) -> list[dict[str, Any]]:  # pragma: no cover - not exercised on the loop-native path
        return []

    def spawn_gap_backfill(
        self, sym: str, tf_str: str, since_ms: int, limit: int,
        on_bars: Callable[[list[dict[str, Any]]], None],
    ) -> None:
        self.spawn_calls += 1
        on_bars(self._page)


def _closed_bar(ts_ms: int) -> dict[str, Any]:
    return {
        "ts": int(ts_ms),
        "open": Decimal("42000.0"),
        "high": Decimal("42500.0"),
        "low": Decimal("41800.0"),
        "close": Decimal("42100.0"),
        "volume": Decimal("1200.5"),
        "symbol": _SYM,
        "timeframe": _TF,
    }


def _make_feed(provider: Any) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    feed = LiveBarFeed(provider=provider, base_timeframe=_TF_DELTA)
    feed.register_raw_bar_consumer(_DepthConsumer(10))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def _drive_gap(feed: LiveBarFeed, gap_multiple: int) -> None:
    """Prime L then drive a gap bar at ``L + gap_multiple*tf`` inside a running loop."""

    async def _run() -> None:
        feed.update(_closed_bar(_START_MS))  # prime L (first in-sequence bar)
        feed.update(_closed_bar(_START_MS + gap_multiple * _TF_MS))  # gap -> spawn -> replay

    asyncio.run(_run())


def test_under_returning_page_fails_loud_no_nested_spawn() -> None:
    """A page that OMITS first_missing fails loud + spawns no nested backfill (D-29 Case A).

    Gap t = L+3tf → first_missing = L+tf, last_missing = L+2tf, since_ms = L+tf. The page
    starts at L+2tf (omits first_missing). RED: current ``_replay_and_deliver`` calls
    ``update()`` on L+2tf → gap branch → a SECOND ``spawn_gap_backfill`` (recursion). GREEN: a
    typed ``MalformedDataError`` is raised and spawn is called exactly once.
    """
    # Under-returning: omit L+tf, start at L+2tf (still within the interior).
    page = [_closed_bar(_START_MS + 2 * _TF_MS)]
    provider = _SyncSpawnProvider(page)
    feed, _q = _make_feed(provider)

    with pytest.raises(MalformedDataError):
        _drive_gap(feed, gap_multiple=3)

    assert provider.spawn_calls == 1  # no nested/recursive backfill


def test_reentrancy_guard_blocks_nested_spawn_on_interior_hole() -> None:
    """A contiguous-first but interior-hole page trips the _replaying_backfill guard (D-29).

    Gap t = L+4tf → first_missing = L+tf, last_missing = L+3tf, since_ms = L+tf,
    last_ms = L+3tf. The page starts contiguous (L+tf) but omits L+2tf, so replaying L+3tf
    after L+tf creates a fresh gap mid-replay. The ``_replaying_backfill`` guard fails loud
    (typed error) instead of spawning a nested backfill — the shape-independent structural stop.
    """
    page = [_closed_bar(_START_MS + 1 * _TF_MS), _closed_bar(_START_MS + 3 * _TF_MS)]
    provider = _SyncSpawnProvider(page)
    feed, _q = _make_feed(provider)

    with pytest.raises(MalformedDataError):
        _drive_gap(feed, gap_multiple=4)

    assert provider.spawn_calls == 1
    # The guard clears after the failed replay (try/finally) — no leaked state.
    assert feed._replaying_backfill is False


def test_well_formed_page_unregressed() -> None:
    """A well-formed page (starts exactly at first_missing) still replays + delivers (D-29 Case B).

    Gap t = L+3tf → interior = L+tf, L+2tf; a contiguous page replays both then delivers t —
    three BarEvents, exactly one spawn, L lands on the trigger. No regression from the fix.
    """
    page = [_closed_bar(_START_MS + 1 * _TF_MS), _closed_bar(_START_MS + 2 * _TF_MS)]
    provider = _SyncSpawnProvider(page)
    feed, q = _make_feed(provider)

    _drive_gap(feed, gap_multiple=3)

    delivered = []
    while not q.empty():
        delivered.append(q.get_nowait())
    # The primed L bar + two interior backfill bars + the trigger t.
    assert [int(e.time.value // 1_000_000) for e in delivered] == [
        _START_MS,
        _START_MS + 1 * _TF_MS,
        _START_MS + 2 * _TF_MS,
        _START_MS + 3 * _TF_MS,
    ]
    assert provider.spawn_calls == 1
    assert feed._last_delivered[(_SYM, _TF)] == pd.Timestamp(
        _START_MS + 3 * _TF_MS, unit="ms", tz="UTC")
    assert feed._replaying_backfill is False
