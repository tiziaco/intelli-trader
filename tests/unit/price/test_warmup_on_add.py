"""OkxDataProvider per-symbol supervisor keys + snapshot gating (06-02, Pitfall 2 / WR-03).

Offline, socket-free tests for the data arm's per-symbol reconnect/health state (Arm B data
plane). With N dynamic candle channels the supervisor state (``_reconnect_attempts`` /
``_streams_down`` / ``_on_stream_healthy`` / ``_reset_reconnect_budget``) MUST key on the
member symbol, NOT the shared literal ``"candles"`` — otherwise one symbol's drop marks all
streams down and one symbol's payload resets all budgets (Pitfall 2), defeating the D-20 HALT
ceiling.

Two facets are asserted:
  (a) two symbols' down-state and reconnect budgets are INDEPENDENT, and
      ``is_streaming_healthy()`` reflects any-symbol-down semantics;
  (b) the ``_connect_and_consume_candles`` stream path threads the per-symbol ``stream_name``
      (clears only that symbol's down-state / budget) and the ``confirm='0'`` snapshot row is
      dropped by ``_process_row`` with NO new dedup logic.

The aiohttp WS is a teardown-safe fake (no real socket opens); the consume body is run to
completion via ``asyncio.run`` over a finite message sequence, so nothing is left un-cancelled
or unclosed under the strict ``filterwarnings=["error"]`` suite (Pitfall 4). This directory is
package-less (NO ``__init__.py``). Indentation is 4-SPACE.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
import pytest

from itrader.price_handler.providers.okx_provider import ClosedBar, OkxDataProvider


# --------------------------------------------------------------------------- fakes


class _StubConnector:
    """Minimal ``LiveConnector`` stand-in exposing only what the stream path reads."""

    def __init__(self, sandbox: bool = True) -> None:
        self.sandbox = sandbox
        self.client: Any = None
        self.ws_hostname = "wspap.okx.com" if sandbox else "ws.okx.com"

    def spawn(self, coro: Any) -> Any:  # pragma: no cover - not exercised here
        coro.close()
        raise NotImplementedError

    def call(self, coro: Any) -> Any:  # pragma: no cover - not exercised here
        return asyncio.run(coro)


class _FakeMsg:
    """A single WS text frame carrying a JSON-encoded OKX business push."""

    def __init__(self, data: str) -> None:
        self.type = aiohttp.WSMsgType.TEXT
        self.data = data


class _FakeWS:
    """Async-context-manager WS double yielding a finite message sequence then stopping."""

    def __init__(self, messages: list[_FakeMsg]) -> None:
        self._messages = messages
        self.sent: list[Any] = []

    async def __aenter__(self) -> "_FakeWS":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def send_json(self, obj: Any) -> None:
        self.sent.append(obj)

    def __aiter__(self) -> Any:
        async def _gen() -> Any:
            for m in self._messages:
                yield m

        return _gen()


def _make_session_cls(messages: list[_FakeMsg]) -> type:
    class _FakeSession:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        def ws_connect(self, url: str, **kwargs: Any) -> _FakeWS:
            return _FakeWS(messages)

        async def close(self) -> None:
            pass

    return _FakeSession


def _row(ts: int, confirm: str) -> list[str]:
    """A well-formed 9-field OKX business candle row with the given confirm flag."""
    return [str(ts), "42000", "42500", "41800", "42100", "1200", "0", "0", confirm]


def _snapshot_then_payload_messages() -> list[_FakeMsg]:
    """A confirm='0' snapshot push followed by a confirm='1' closed-bar push."""
    return [
        _FakeMsg(json.dumps({"data": [_row(1704067200000, "0")]})),  # snapshot on subscribe
        _FakeMsg(json.dumps({"data": [_row(1704067200000, "1")]})),  # first real closed bar
    ]


@pytest.fixture
def provider() -> OkxDataProvider:
    return OkxDataProvider(_StubConnector(sandbox=True), symbol="BTC/USDC", timeframe="1d")


# ------------------------------------------------- (a) independent per-symbol down-state


def test_down_state_is_independent_per_symbol(provider: OkxDataProvider) -> None:
    assert provider.is_streaming_healthy()  # nothing down yet

    provider._mark_stream_down("BTC/USDC")

    assert not provider.is_streaming_healthy()          # any-symbol-down => unhealthy
    assert "ETH/USDC" not in provider._streams_down     # the other symbol is unaffected

    provider._on_stream_healthy("BTC/USDC")             # A recovers
    assert provider.is_streaming_healthy()              # all up => healthy again


def test_reset_reconnect_budget_is_per_symbol(provider: OkxDataProvider) -> None:
    provider._reconnect_attempts["BTC/USDC"] = 3
    provider._reconnect_attempts["ETH/USDC"] = 2

    provider._reset_reconnect_budget("BTC/USDC")

    assert provider._reconnect_attempts["BTC/USDC"] == 0   # A reset
    assert provider._reconnect_attempts["ETH/USDC"] == 2   # B untouched


def test_is_streaming_healthy_any_symbol_down(provider: OkxDataProvider) -> None:
    provider._mark_stream_down("BTC/USDC")
    provider._mark_stream_down("ETH/USDC")
    assert not provider.is_streaming_healthy()

    provider._on_stream_healthy("BTC/USDC")
    assert not provider.is_streaming_healthy()  # ETH still down

    provider._on_stream_healthy("ETH/USDC")
    assert provider.is_streaming_healthy()      # both up


# --------------------------------- (b) stream path threads the per-symbol key (not "candles")


def test_stream_path_uses_per_symbol_key(
    provider: OkxDataProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Driving the consume body for ETH clears ONLY ETH's down-state + budget, not BTC's."""
    provider.set_bar_sink(lambda _b: None)
    # Pre-seed BOTH symbols as down with distinct reconnect budgets.
    provider._streams_down.update({"ETH-USDC", "BTC-USDC"})
    provider._reconnect_attempts["ETH-USDC"] = 3
    provider._reconnect_attempts["BTC-USDC"] = 5

    monkeypatch.setattr(
        aiohttp, "ClientSession", _make_session_cls(_snapshot_then_payload_messages()))
    # 3-arg per-symbol signature: stream_name keyed on the member symbol "ETH-USDC".
    asyncio.run(provider._connect_and_consume_candles("ETH-USDC", "candle1D", "ETH-USDC"))

    # _on_stream_healthy(stream_name) cleared ONLY ETH; BTC's down-state persists.
    assert "ETH-USDC" not in provider._streams_down
    assert "BTC-USDC" in provider._streams_down
    # A post-snapshot payload reset ONLY ETH's budget; BTC's is untouched.
    assert provider._reconnect_attempts["ETH-USDC"] == 0
    assert provider._reconnect_attempts["BTC-USDC"] == 5


def test_confirm_zero_snapshot_row_is_dropped(provider: OkxDataProvider) -> None:
    """The confirm='0' snapshot row is dropped by _process_row (no new dedup logic)."""
    delivered: list[ClosedBar] = []
    provider.set_bar_sink(delivered.append)

    provider._process_row(_row(1704067200000, "0"))   # forming/snapshot
    assert delivered == []                             # dropped at the confirm gate

    provider._process_row(_row(1704067200000, "1"))   # terminal closed bar
    assert len(delivered) == 1                         # contrast: the gate lets confirm='1' through
