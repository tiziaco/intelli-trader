"""Integration matrix for LiveBarFeed warmup + reconnect backfill — FEED-03 / D-08.

Phase 3 / 03-03: both backfill entry points route through the SAME ``update()``
replay path built in 03-02 — there is NO bulk ``warmup_from`` fast-path (LX-09, the
parity audit). Offline, socket-free: a local programmable ``_StubProvider`` mints
the REST backfill list, a local ``ClosedBar`` builder advances ``ts`` by exactly one
timeframe, and a real ``queue.Queue`` collects the emitted ``BarEvent``s. NO aiohttp,
NO asyncio, NO wall-clock — every ``ts`` is a fixed epoch-ms literal (byte-reproducible).

- FEED-03 warmup: ``warmup(sym, tf, depth=K)`` fetches K bars ONCE and replays each
  through ``update()`` (K contiguous BarEvents; depth ``K = cache_capacity() + margin``).
- Pitfall-1 guard: after warming 100+margin bars an SMA(100) handle reaches ``is_ready``.
- D-08 reconnect: a completed-bar BOUNDARY crossing (``latest > L``) REST-backfills
  ``[L+tf .. latest]`` via the same ``update()`` path; a re-sent bar hits the duplicate
  branch (no double-delivery); ``latest == L`` is a no-op.

Indentation is 4-SPACE (matched to the ``price_handler/feed`` tree).
"""

from __future__ import annotations

import queue
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest

from itrader.events_handler.events import BarEvent
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.strategy_handler.indicators import SMA, IndicatorHandle

_SYM = "BTC-USDT"
_TF = "1d"
_TF_DELTA = timedelta(days=1)
_TF_MS = int(_TF_DELTA.total_seconds() * 1000)
# Fixed byte-reproducible epoch-ms literal (2024-01-01T00:00:00Z), never wall-clock.
_START_MS = 1704067200000
# The additive warmup safety margin the feed applies (RESEARCH: fixed +N, not a
# multiplier); mirrored here so the depth assertion is explicit.
_MARGIN = 5


# ---------------------------------------------------------------------------
# Local offline fixtures (this dir has no shared price conftest; keep self-contained)
# ---------------------------------------------------------------------------


def _make_closed_bar(
    ts_ms: int = _START_MS,
    *,
    symbol: str = _SYM,
    timeframe: str = _TF,
    open: str = "42000.0",
    high: str = "42500.0",
    low: str = "41800.0",
    close: str = "42100.0",
    volume: str = "1200.5",
) -> dict[str, Any]:
    """Build one synthetic ``ClosedBar`` — Decimal OHLCV + the D-12 routing keys."""
    return {
        "ts": int(ts_ms),
        "open": Decimal(str(open)),
        "high": Decimal(str(high)),
        "low": Decimal(str(low)),
        "close": Decimal(str(close)),
        "volume": Decimal(str(volume)),
        "symbol": symbol,
        "timeframe": timeframe,
    }


def _sequence(
    n: int,
    *,
    start_ts: int = _START_MS,
    symbol: str = _SYM,
    timeframe: str = _TF,
) -> list[dict[str, Any]]:
    """N consecutive ``ClosedBar``s advancing ``ts`` by exactly one timeframe."""
    step_ms = int(to_timedelta(timeframe).total_seconds() * 1000)
    # Vary the close monotonically so the SMA(100) readiness test sees real inputs.
    return [
        _make_closed_bar(
            start_ts + i * step_ms,
            symbol=symbol,
            timeframe=timeframe,
            close=str(42000.0 + i),
        )
        for i in range(n)
    ]


class _StubProvider:
    """Socket-free stand-in for ``OkxDataProvider.fetch_ohlcv_backfill`` (call-logging)."""

    def __init__(self) -> None:
        self.backfill_bars: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []

    def fetch_ohlcv_backfill(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "since": since, "limit": limit}
        )
        return list(self.backfill_bars)


class _DepthConsumer:
    """Minimal ``RawBarConsumer`` forcing a derived ``cache_capacity()`` (D-09/D-13)."""

    def __init__(self, depth: int) -> None:
        self._depth = depth

    @property
    def required_history_depth(self) -> int:
        return self._depth


def _make_feed(
    provider: Any,
    capacity: int | None = None,
) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    feed = LiveBarFeed(provider=provider, base_timeframe=_TF_DELTA)
    if capacity is not None:
        feed.register_raw_bar_consumer(_DepthConsumer(capacity))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def _drain(q: "queue.Queue[Any]") -> list[Any]:
    events: list[Any] = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 1_000_000)


# ---------------------------------------------------------------------------
# FEED-03 — warmup one-by-one replay through the shared update() path
# ---------------------------------------------------------------------------


def test_warmup_replays_one_by_one() -> None:
    """warmup(depth=K) fetches K bars ONCE and replays EACH via update() — no bulk path."""
    provider = _StubProvider()
    feed, q = _make_feed(provider, capacity=10)
    k = 8
    provider.backfill_bars = _sequence(k)

    # Spy on update() to prove one-by-one replay (K invocations, no bulk shortcut).
    update_calls = {"n": 0}
    original_update = feed.update

    def _counting_update(cb: Any) -> None:
        update_calls["n"] += 1
        original_update(cb)

    feed.update = _counting_update  # type: ignore[method-assign]

    feed.warmup(_SYM, _TF, depth=k)

    # Exactly one fetch, for K bars.
    assert len(provider.calls) == 1
    assert provider.calls[0]["limit"] == k
    # update() invoked once per replayed bar (no bulk fast-path).
    assert update_calls["n"] == k
    # K contiguous BarEvents (one per replayed bar), one tf apart, none skipped.
    events = _drain(q)
    assert len(events) == k
    assert all(isinstance(e, BarEvent) for e in events)
    assert [_ms(e.time) for e in events] == [_START_MS + i * _TF_MS for i in range(k)]
    # No bulk state-building path exists on the feed (LX-09 parity audit).
    assert not hasattr(feed, "warmup_from")


def test_warmup_depth_is_capacity_plus_margin() -> None:
    """depth=None resolves to cache_capacity() + margin (fixed additive, D-10)."""
    provider = _StubProvider()
    feed, _q = _make_feed(provider, capacity=100)
    provider.backfill_bars = []  # depth resolution is all we assert here

    feed.warmup(_SYM, _TF)  # no explicit depth

    assert len(provider.calls) == 1
    assert provider.calls[0]["limit"] == 100 + _MARGIN


def test_warmup_makes_indicator_ready() -> None:
    """After warming 100+margin bars, an SMA(100) handle reaches is_ready (Pitfall-1 guard)."""
    provider = _StubProvider()
    feed, q = _make_feed(provider, capacity=100)
    depth = 100 + _MARGIN
    provider.backfill_bars = _sequence(depth)

    feed.warmup(_SYM, _TF)

    events = _drain(q)
    assert len(events) == depth
    # Drive an SMA(100) handle off the warmed closes — it must reach readiness.
    handle = IndicatorHandle(SMA, "close", (100,))
    for e in events:
        handle.update(float(e.bars[_SYM].close))
    assert handle.is_ready is True


# ---------------------------------------------------------------------------
# D-08 — reconnect boundary backfill through the same update() gap path
# ---------------------------------------------------------------------------


def test_reconnect_boundary_backfills() -> None:
    """latest > L → REST-backfill [L+tf .. latest] via update(); a re-sent bar dedups."""
    provider = _StubProvider()
    feed, q = _make_feed(provider, capacity=10)
    feed.update(_make_closed_bar(_START_MS))  # L = _START_MS
    _drain(q)

    latest_ms = _START_MS + 3 * _TF_MS
    provider.backfill_bars = [
        _make_closed_bar(_START_MS + 1 * _TF_MS, close="42001.0"),
        _make_closed_bar(_START_MS + 2 * _TF_MS, close="42002.0"),
        _make_closed_bar(_START_MS + 3 * _TF_MS, close="42003.0"),
    ]

    feed.backfill_on_resume(_SYM, _TF, latest_completed_ts=latest_ms)

    events = _drain(q)
    # [L+tf .. latest] inclusive of the boundary bar — 3 contiguous BarEvents.
    assert [_ms(e.time) for e in events] == [
        _START_MS + 1 * _TF_MS,
        _START_MS + 2 * _TF_MS,
        _START_MS + 3 * _TF_MS,
    ]
    # One backfill call for the range [L+tf .. latest].
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["symbol"] == _SYM
    assert call["timeframe"] == _TF
    assert call["since"] == _START_MS + _TF_MS  # (L + tf) in ms
    assert call["limit"] == 3

    # The resumed stream re-sends the boundary bar → duplicate branch drops it.
    feed.update(_make_closed_bar(_START_MS + 3 * _TF_MS, close="42003.0"))
    assert _drain(q) == []


def test_reconnect_no_boundary_noop() -> None:
    """latest == L → no backfill, no emit (no completed-bar boundary crossed)."""
    provider = _StubProvider()
    feed, q = _make_feed(provider, capacity=10)
    feed.update(_make_closed_bar(_START_MS))  # L = _START_MS
    _drain(q)

    feed.backfill_on_resume(_SYM, _TF, latest_completed_ts=_START_MS)

    assert _drain(q) == []
    assert provider.calls == []


def test_reconnect_cold_start_noop() -> None:
    """L is None (no bar delivered yet) → reconnect is a no-op (warmup owns cold start)."""
    provider = _StubProvider()
    feed, q = _make_feed(provider, capacity=10)

    feed.backfill_on_resume(_SYM, _TF, latest_completed_ts=_START_MS + 3 * _TF_MS)

    assert _drain(q) == []
    assert provider.calls == []
