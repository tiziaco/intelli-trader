"""OkxDataProvider.spawn_warmup — async REST warmup → ONE BarsLoaded/BarsLoadFailed (07-03, WR-02).

Offline, socket-free tests for the async half of the WR-02 warmup pipeline (D-03/D-04). The
provider fetches warmup bars over REST on the connector loop and hands them back to the engine
thread as ONE bulk-transport event:

  1. success → exactly ONE ``BarsLoaded(symbol, timeframe, bars, time)`` with ``bars`` non-empty
     and ``time`` == the newest fetched bar's open-time (business time, Pitfall 5);
  2. a raised fetch error → exactly ONE ``BarsLoadFailed`` whose ``reason`` is the SCRUBBED
     exception TYPE name and does NOT leak the raised message (T-05-27 / Security V5);
  3. scheduling goes through ``connector.spawn`` (threadsafe), never ``create_task``;
  4. ``spawn_warmup`` mutates NO feed state (the bar sink is never invoked — pure I/O + queue.put).

The connector is a socket-free fake whose ``spawn`` drives the warmup coroutine to completion via
``asyncio.run`` (so ``BarsLoaded``/``BarsLoadFailed`` reach the queue) and returns a handle
supporting ``add_done_callback``. The ccxt client is a fake ``async fetch_ohlcv``. No aiohttp, no
real socket — nothing is left un-awaited under the strict ``filterwarnings=["error"]`` suite. This
directory is package-less (NO ``__init__.py``); indentation is 4-SPACE.
"""

from __future__ import annotations

import asyncio
import queue
from typing import Any

import pandas as pd
import pytest

from itrader.events_handler.events import BarsLoaded, BarsLoadFailed
from itrader.price_handler.providers.okx_provider import OkxDataProvider

pytestmark = pytest.mark.unit

_SYM = "BTC/USDT"
_TF = "1d"
_START_MS = 1704067200000  # 2024-01-01T00:00:00Z — fixed literal, never wall-clock.
_DAY_MS = 86_400_000


def _rows(n: int) -> list[list[Any]]:
    """N ccxt OHLCV rows ``[ts, o, h, l, c, v]`` advancing ts by one day."""
    return [
        [_START_MS + i * _DAY_MS, 42000.0 + i, 42500.0 + i, 41800.0 + i,
         42100.0 + i, 1200.0 + i]
        for i in range(n)
    ]


class _FakeClient:
    """Socket-free ccxt client double: ``async fetch_ohlcv`` returns canned rows or raises."""

    def __init__(self, rows: list[list[Any]], exc: BaseException | None = None) -> None:
        self._rows = rows
        self._exc = exc
        self.calls: list[tuple[Any, ...]] = []

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str,
        since: int | None = None, limit: int | None = None,
    ) -> list[list[Any]]:
        self.calls.append((symbol, timeframe, since, limit))
        if self._exc is not None:
            raise self._exc
        # First page (since is None) returns the canned rows; a paginating follow-up
        # (since advanced) returns empty so the bounded fetch terminates.
        return self._rows if since is None else []


class _DoneHandle:
    """A stand-in for the ``asyncio.Task`` ``spawn`` returns — records the done-callback."""

    def __init__(self) -> None:
        self.callbacks: list[Any] = []

    def add_done_callback(self, cb: Any) -> None:
        self.callbacks.append(cb)


class _WarmupConnector:
    """Socket-free ``LiveConnector`` double whose ``spawn`` drives the warmup coroutine to done."""

    def __init__(self, client: _FakeClient) -> None:
        self._client = client
        self.sandbox = True
        self.ws_hostname = "wspap.okx.com"
        self.spawn_calls = 0

    @property
    def client(self) -> _FakeClient:
        return self._client

    def spawn(self, coro: Any) -> _DoneHandle:
        # Offline: run the warmup coroutine to completion synchronously so the emitted
        # BarsLoaded/BarsLoadFailed lands on the queue (nothing left un-awaited).
        self.spawn_calls += 1
        asyncio.run(coro)
        return _DoneHandle()

    def call(self, coro: Any) -> Any:  # pragma: no cover - not used by spawn_warmup
        return asyncio.run(coro)


def _provider(client: _FakeClient) -> "tuple[OkxDataProvider, queue.Queue[Any], _WarmupConnector]":
    conn = _WarmupConnector(client)
    provider = OkxDataProvider(conn, symbol=_SYM, timeframe=_TF)
    q: "queue.Queue[Any]" = queue.Queue()
    provider.set_global_queue(q)
    return provider, q, conn


def test_spawn_warmup_success_emits_one_bars_loaded() -> None:
    provider, q, _conn = _provider(_FakeClient(_rows(3)))

    provider.spawn_warmup(_SYM, _TF, limit=105)

    assert q.qsize() == 1
    ev = q.get_nowait()
    assert isinstance(ev, BarsLoaded)
    assert ev.symbol == _SYM
    assert ev.timeframe == _TF
    assert len(ev.bars) == 3
    # time == the newest fetched bar's open-time (business time, Pitfall 5).
    newest = pd.Timestamp(_START_MS + 2 * _DAY_MS, unit="ms", tz="UTC")
    assert ev.bars[-1].time == newest
    assert ev.time == ev.bars[-1].time


def test_spawn_warmup_failure_emits_one_scrubbed_bars_load_failed() -> None:
    secret = "sk-live-super-secret-token-do-not-leak"
    provider, q, _conn = _provider(_FakeClient([], exc=RuntimeError(secret)))

    provider.spawn_warmup(_SYM, _TF, limit=105)

    assert q.qsize() == 1
    ev = q.get_nowait()
    assert isinstance(ev, BarsLoadFailed)
    assert ev.symbol == _SYM
    # reason is the exception TYPE name only — the raised message is scrubbed out (T-05-27).
    assert ev.reason == "RuntimeError"
    assert secret not in ev.reason


def test_spawn_warmup_empty_fetch_emits_scrubbed_failure() -> None:
    provider, q, _conn = _provider(_FakeClient([]))  # fetch returns no rows

    provider.spawn_warmup(_SYM, _TF, limit=105)

    assert q.qsize() == 1
    ev = q.get_nowait()
    assert isinstance(ev, BarsLoadFailed)
    assert ev.reason == "MissingPriceDataError"  # empty warmup window → scrubbed failure


def test_spawn_warmup_schedules_via_connector_spawn() -> None:
    provider, _q, conn = _provider(_FakeClient(_rows(2)))

    provider.spawn_warmup(_SYM, _TF, limit=105)

    # Scheduling went through connector.spawn (threadsafe), not create_task.
    assert conn.spawn_calls == 1


def test_spawn_warmup_mutates_no_feed_state() -> None:
    provider, _q, _conn = _provider(_FakeClient(_rows(3)))
    delivered: list[Any] = []
    provider.set_bar_sink(delivered.append)

    provider.spawn_warmup(_SYM, _TF, limit=105)

    # Pure I/O + one queue.put — the bar sink (feed.update) is never touched.
    assert delivered == []


def test_spawn_warmup_unbound_queue_raises_state_error() -> None:
    from itrader.core.exceptions import StateError

    conn = _WarmupConnector(_FakeClient(_rows(1)))
    provider = OkxDataProvider(conn, symbol=_SYM, timeframe=_TF)  # no set_global_queue

    with pytest.raises(StateError):
        provider.spawn_warmup(_SYM, _TF, limit=105)
    assert conn.spawn_calls == 0  # never scheduled without a bound queue
