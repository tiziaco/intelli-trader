"""OkxDataProvider dynamic subscribe/unsubscribe — the D-05 per-symbol registry (06-02).

Offline, socket-free tests for the data arm's dynamic subscription surface (Arm B data
plane, UNIV-02). The provider grows a ``{symbol: asyncio.Task}`` registry, an idempotent
``subscribe(symbol)`` that spawns ONE supervised ``candle{tf}`` coroutine on the connector
loop, and an ``unsubscribe(symbol)`` that cancels the task via the connector's existing
cooperative-cancel teardown (no new teardown code).

The connector is a recording fake whose ``spawn`` records the coroutine's bound arguments,
then ``close()``s the un-started coroutine so nothing is left un-awaited under the strict
``filterwarnings=["error"]`` suite (a never-awaited coroutine raises ``RuntimeWarning`` →
suite failure). No aiohttp session ever opens. This directory is package-less (NO
``__init__.py``). Indentation is 4-SPACE (matched to the ``price_handler/providers`` tree).
"""

from __future__ import annotations

from typing import Any

import pytest

from itrader.price_handler.providers.okx_provider import OkxDataProvider


class _DummyTask:
    """A cancellable stand-in for the ``asyncio.Task`` ``spawn`` returns."""

    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> bool:
        self.cancel_calls += 1
        return True


class _RecordingConnector:
    """Minimal ``LiveConnector`` stand-in recording every ``spawn`` and its coroutine args.

    ``spawn`` reads the un-started coroutine's frame locals (``symbol_okx``/``channel``) so a
    test can assert the normalized instId + channel token, then ``close()``s the coroutine
    (never-awaited-safe under the strict suite) and returns a fresh cancellable ``_DummyTask``.
    """

    def __init__(self) -> None:
        self.spawn_args: list[dict[str, Any]] = []
        self.tasks: list[_DummyTask] = []

    def spawn(self, coro: Any) -> _DummyTask:
        frame = coro.cr_frame
        self.spawn_args.append(dict(frame.f_locals) if frame is not None else {})
        coro.close()
        task = _DummyTask()
        self.tasks.append(task)
        return task


@pytest.fixture
def provider() -> OkxDataProvider:
    """A provider bound to the recording connector; single-symbol wiring default unused."""
    connector = _RecordingConnector()
    return OkxDataProvider(connector, symbol="BTC/USDT", timeframe="1d")


def _connector(provider: OkxDataProvider) -> _RecordingConnector:
    """Reach the recording connector the provider was constructed with."""
    conn = provider._connector
    assert isinstance(conn, _RecordingConnector)
    return conn


def test_subscribe_spawns_once_and_registers_task(provider: OkxDataProvider) -> None:
    provider.subscribe("ETH/USDC")

    conn = _connector(provider)
    assert len(conn.spawn_args) == 1
    assert provider._streams["ETH/USDC"] is conn.tasks[0]


def test_subscribe_is_idempotent(provider: OkxDataProvider) -> None:
    provider.subscribe("ETH/USDC")
    provider.subscribe("ETH/USDC")

    conn = _connector(provider)
    assert len(conn.spawn_args) == 1  # second subscribe is a no-op
    assert list(provider._streams) == ["ETH/USDC"]


def test_subscribe_normalizes_symbol_and_computes_channel(provider: OkxDataProvider) -> None:
    provider.subscribe("ETH/USDC")

    args = _connector(provider).spawn_args[0]
    assert args["symbol_okx"] == "ETH-USDC"   # _to_okx_symbol normalization
    assert args["channel"] == "candle1D"      # "candle" + OKX interval token for "1d"


def test_unsubscribe_pops_and_cancels_once(provider: OkxDataProvider) -> None:
    provider.subscribe("ETH/USDC")
    task = provider._streams["ETH/USDC"]

    provider.unsubscribe("ETH/USDC")

    assert "ETH/USDC" not in provider._streams
    assert isinstance(task, _DummyTask)
    assert task.cancel_calls == 1


def test_unsubscribe_of_never_subscribed_is_noop(provider: OkxDataProvider) -> None:
    # No exception, no cancel, registry untouched.
    provider.unsubscribe("DOGE/USDC")

    assert provider._streams == {}


def test_subscribe_after_unsubscribe_respawns(provider: OkxDataProvider) -> None:
    provider.subscribe("ETH/USDC")
    provider.unsubscribe("ETH/USDC")
    provider.subscribe("ETH/USDC")

    conn = _connector(provider)
    assert len(conn.spawn_args) == 2  # re-spawned after removal
    assert provider._streams["ETH/USDC"] is conn.tasks[1]
