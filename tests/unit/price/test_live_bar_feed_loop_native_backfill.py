"""D-17 (V17-15) — loop-native gap backfill (kills the connector-loop self-deadlock).

The mid-session gap backfill is triggered on the CONNECTOR LOOP THREAD: the native candle
coroutine calls ``feed.update(closed_bar)`` synchronously inside its running asyncio loop, and
a detected gap fans out to ``LiveBarFeed._backfill_gap`` → ``OkxDataProvider.fetch_ohlcv_backfill``
→ ``connector.call(client.fetch_ohlcv(...)).result(timeout=...)``. A blocking ``.result()`` on the
loop thread self-deadlocks (30s stall → livelock, RESEARCH Pitfall 4 / AUD-4c): the coroutine it
is waiting for can only run on the very loop it just blocked.

D-17 makes the loop-triggered gap path LOOP-NATIVE — it hands the gap range to a dedicated
backfill coroutine spawned on the connector loop that ``await``s the client fetch DIRECTLY,
NEVER through the ``connector.call(...).result()`` bridge. The engine-thread ``warmup`` path
(off the loop, safe) keeps the synchronous ``fetch_ohlcv_backfill`` unchanged.

Harness: a connector stub owning a REAL asyncio loop on a daemon thread (mirrors
``OkxConnector``'s loop-on-a-daemon-thread), instrumented so any ``call()`` reached from the loop
thread is flagged as the self-deadlock signature — and refuses to actually hang the suite. The
gap bar is driven from the loop thread inside a coroutine, exactly as the candle consumer does.

Indentation is 4-SPACE (matched to the ``price_handler/feed`` tree). No live socket, no aiohttp.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

import pandas as pd
import pytest

from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
from itrader.price_handler.providers.okx_provider import OkxDataProvider

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


class _FakeClient:
    """ccxt-shaped client whose ``fetch_ohlcv`` is an awaitable returning canned rows.

    Rows are the raw ccxt ``[ts, o, h, l, c, v]`` shape. ``since`` filters at/after (the real
    OKX behaviour); ``limit`` is a per-page size, so a full page keeps paginating.
    """

    def __init__(self, rows: list[list[Any]], fail: bool = False) -> None:
        self._rows = rows
        self._fail = fail
        self.calls: list[tuple[Any, ...]] = []

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str,
        since: int | None = None, limit: int | None = None,
    ) -> list[list[Any]]:
        self.calls.append((symbol, timeframe, since, limit))
        if self._fail:
            raise RuntimeError("simulated venue REST failure")
        rows = [r for r in self._rows if since is None or r[0] >= since]
        if limit is not None:
            rows = rows[:limit]
        return rows


class _LoopConnector:
    """``LiveConnector`` stub owning a REAL asyncio loop on a daemon thread.

    Instrumented for D-17: ``call()`` reached FROM the loop thread is the self-deadlock
    signature — it flags ``call_from_loop_thread`` and raises instead of hanging the suite (a
    real ``.result()`` there would block the loop forever). Off the loop thread ``call()`` bridges
    normally via ``run_coroutine_threadsafe``.
    """

    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.sandbox = True
        self.ws_hostname = "wspap.okx.com"
        self.call_from_loop_thread = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="test-okx-loop")
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def call(self, coro: Any) -> Any:
        if threading.current_thread() is self._thread:
            self.call_from_loop_thread = True
            coro.close()
            raise AssertionError(
                "connector.call(...).result() invoked on the loop thread "
                "(would self-deadlock, D-17 / Pitfall 4)")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=5)

    def spawn(self, coro: Any) -> Any:  # pragma: no cover - not used here
        raise NotImplementedError

    def run_on_loop(self, fn: Callable[[], Any]) -> Any:
        """Run a sync ``fn`` on the loop thread inside a coroutine.

        Mirrors production: ``feed.update()`` is called synchronously INSIDE the running candle
        coroutine, so a running loop is present on the calling thread.
        """
        async def _coro() -> Any:
            return fn()

        return asyncio.run_coroutine_threadsafe(_coro(), self._loop).result(timeout=5)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


def _row(ts_ms: int) -> list[Any]:
    return [ts_ms, "42000.0", "42500.0", "41800.0", "42100.0", "1200.5"]


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


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.value // 1_000_000)


def _drain_until(q: "queue.Queue[Any]", expected: int, timeout: float = 5.0) -> list[Any]:
    """Block on ``q.get(timeout=...)`` until ``expected`` events arrive or the deadline passes."""
    events: list[Any] = []
    deadline = time.monotonic() + timeout
    while len(events) < expected:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            events.append(q.get(timeout=remaining))
        except queue.Empty:
            break
    return events


def _make_feed(provider: Any) -> "tuple[LiveBarFeed, queue.Queue[Any]]":
    feed = LiveBarFeed(provider=provider, base_timeframe=_TF_DELTA)
    feed.register_raw_bar_consumer(_DepthConsumer(10))
    q: "queue.Queue[Any]" = queue.Queue()
    feed.bind(q, [_SYM])
    return feed, q


def test_loop_triggered_gap_backfill_is_loop_native_no_result_bridge() -> None:
    """A gap detected on the connector loop thread backfills WITHOUT a ``call().result()`` bridge.

    RED (pre-D-17): the loop-triggered gap path calls ``connector.call(...)`` on the loop thread
    (the self-deadlock signature). GREEN: the interior bars + trigger are delivered via a
    loop-native awaited fetch, and ``connector.call`` is never reached from the loop thread.
    """
    # Interior for the gap [L+tf .. t-tf] with t at L+3tf → two interior bars.
    client = _FakeClient(rows=[_row(_START_MS + 1 * _TF_MS), _row(_START_MS + 2 * _TF_MS)])
    connector = _LoopConnector(client)
    try:
        provider = OkxDataProvider(connector, _SYM, _TF)
        feed, q = _make_feed(provider)

        # Prime L on the loop thread (first in-sequence bar).
        connector.run_on_loop(lambda: feed.update(_closed_bar(_START_MS)))
        _drain_until(q, expected=1)

        # Drive the GAP bar from the loop thread (t = L + 3tf → interior = L+tf, L+2tf).
        t_ms = _START_MS + 3 * _TF_MS
        connector.run_on_loop(lambda: feed.update(_closed_bar(t_ms)))

        # Loop-native backfill resolves asynchronously on the loop: 2 interior + the trigger.
        events = _drain_until(q, expected=3)
        assert [_ms(e.time) for e in events] == [
            _START_MS + 1 * _TF_MS,
            _START_MS + 2 * _TF_MS,
            _START_MS + 3 * _TF_MS,
        ]
        # The whole point of D-17: no blocking call().result() bridge on the loop thread.
        assert connector.call_from_loop_thread is False
        # And the loop-native await DID reach the client fetch directly.
        assert client.calls, "loop-native backfill never awaited client.fetch_ohlcv"
        # L lands on the trigger, no rewind.
        assert feed._last_delivered[(_SYM, _TF)] == pd.Timestamp(t_ms, unit="ms", tz="UTC")
    finally:
        connector.close()


def test_loop_native_gap_backfill_failure_escalates_halt() -> None:
    """A dead loop-native gap-backfill coroutine escalates to the halt entrypoint (D-11 shape).

    The spawned backfill task must be supervised: an unexpected fetch failure escalates to the
    injected halt signal ('connector-fatal') rather than dying silently on the loop.
    """
    client = _FakeClient(rows=[], fail=True)
    connector = _LoopConnector(client)
    halts: list[str] = []
    try:
        provider = OkxDataProvider(connector, _SYM, _TF)
        provider.set_halt_signal(halts.append)
        feed, q = _make_feed(provider)

        connector.run_on_loop(lambda: feed.update(_closed_bar(_START_MS)))
        _drain_until(q, expected=1)

        t_ms = _START_MS + 3 * _TF_MS
        connector.run_on_loop(lambda: feed.update(_closed_bar(t_ms)))

        # Give the supervised task time to fail + escalate.
        deadline = time.monotonic() + 5.0
        while not halts and time.monotonic() < deadline:
            time.sleep(0.01)
        assert halts == ["connector-fatal"]
        # No blocking bridge on the loop thread even on the failure path.
        assert connector.call_from_loop_thread is False
    finally:
        connector.close()
