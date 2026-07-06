"""OkxDataProvider unit tests — confirm gate, sandbox host routing, Decimal-edge backfill.

Offline, mocked tests for the data arm's three load-bearing properties (Plan 02-04):

- **confirm gate (CONN-01 / T-02-04-CONFIRM):** driving the native business socket with the
  recorded-shape push sequence (``confirm`` ``0``..``0``..``0``..``1``), ONLY the terminal
  ``confirm=="1"`` bar reaches the closed-bar sink; every forming push is dropped. A missed
  gate silently corrupts paper-parity, so this is the gating CONN-01 assertion.
- **sandbox host routing (CONN-03 / T-02-04-MISROUTE):** the native socket URL selects
  ``wspap.okx.com`` when the injected connector's ``sandbox`` is True and ``ws.okx.com``
  when False — the ``x-simulated-trading`` header never routes WS (host, not header). A
  live misroute streaming from the LIVE venue while believing it is demo is the phase's
  highest-severity threat.
- **Decimal-edge backfill (CONN-05 / T-02-04-FLOAT):** REST ``fetch_ohlcv`` backfill returns
  ``Decimal`` OHLCV crossed via ``to_money(str(raw))`` — no float ever leaks into the bar.

The aiohttp WS is a teardown-safe fake (no real socket opens); the stream coroutine is run
to completion via ``asyncio.run`` over a finite message sequence, so no ``watch_*`` task is
left un-cancelled and no session is left unclosed — nothing escalates under the strict
``filterwarnings=["error"]`` suite (Pitfall 4). This directory is package-less (NO
``__init__.py``).
"""

import asyncio
import json
from decimal import Decimal
from typing import Any, Callable
from unittest.mock import AsyncMock

import aiohttp
import pytest

from itrader.core.money import to_money
from itrader.price_handler.providers.okx_provider import ClosedBar, OkxDataProvider


# --------------------------------------------------------------------------- fakes


class _StubConnector:
    """Minimal ``LiveConnector`` stand-in exposing only what the data arm reads directly.

    ``_stream_candles`` reads ``ws_hostname``; ``fetch_ohlcv_backfill`` reads ``client``
    and bridges through ``call`` (run the coroutine to completion inline — no background
    loop needed for the synchronous-RPC path in these offline tests). ``ws_hostname``
    defaults to the sandbox-derived global host so the legacy routing tests still pin
    wspap/ws; the region-derived host is exercised by passing it explicitly.
    """

    def __init__(
        self, sandbox: bool, client: Any = None, ws_hostname: str | None = None
    ) -> None:
        self.sandbox = sandbox
        self.client = client
        self.ws_hostname = (
            ws_hostname
            if ws_hostname is not None
            else ("wspap.okx.com" if sandbox else "ws.okx.com")
        )

    def call(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def spawn(self, coro: Any) -> Any:  # pragma: no cover - not exercised here
        raise NotImplementedError


class _FakeMsg:
    """A single WS text frame carrying a JSON-encoded OKX business push."""

    def __init__(self, data: str, msg_type: Any = aiohttp.WSMsgType.TEXT) -> None:
        self.type = msg_type
        self.data = data


class _FakeWS:
    """Async-context-manager WS double that yields a finite message sequence then stops."""

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


def _make_session_cls(
    messages: list[_FakeMsg], recorder: dict[str, Any]
) -> type:
    """Build a fake ``aiohttp.ClientSession`` class recording the ws_connect URL."""

    class _FakeSession:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        def ws_connect(self, url: str, **kwargs: Any) -> _FakeWS:
            recorder["url"] = url
            recorder["kwargs"] = kwargs
            return _FakeWS(messages)

        async def close(self) -> None:
            pass

    return _FakeSession


def _messages_from(fixture: dict) -> list[_FakeMsg]:
    return [_FakeMsg(json.dumps(push)) for push in fixture["pushes"]]


def _drive_stream(
    provider: OkxDataProvider,
    fixture: dict,
    monkeypatch: pytest.MonkeyPatch,
    *,
    symbol: str = "BTC-USDT",
    channel: str = "candle1D",
) -> dict[str, Any]:
    """Patch aiohttp with the fake session and run one full candle stream; return the recorder."""
    recorder: dict[str, Any] = {}
    monkeypatch.setattr(
        aiohttp, "ClientSession", _make_session_cls(_messages_from(fixture), recorder))
    # Drive ONE consume cycle (connect + subscribe + read the finite fixture), NOT
    # `_stream_candles` — that wraps this body in the unbounded reconnect supervisor
    # (D-19/D-20), which treats the finite fake stream's exhaustion as a server-side
    # socket close and reconnects forever (the re-delivered fixture resets the retry
    # budget so the ceiling never trips). These tests assert the consume body's
    # confirm gate / host routing / sink; the supervisor's reconnect behaviour is
    # covered separately.
    # 06-02: per-symbol supervisor key threaded as the third arg (stream_name); these
    # tests drive a single symbol so the member key is the streamed symbol itself.
    asyncio.run(provider._connect_and_consume_candles(symbol, channel, symbol))
    return recorder


# --------------------------------------------------------------- confirm gate (CONN-01)


def test_confirm_gate_only_completed_bar_reaches_sink(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the terminal confirm=="1" push reaches the sink; every forming push is dropped."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    delivered: list[ClosedBar] = []
    provider.set_bar_sink(delivered.append)

    _drive_stream(provider, okx_business_candles, monkeypatch)

    # The fixture is confirm 0,0,0,1 — exactly one completed bar flows downstream.
    assert len(delivered) == 1
    closed_row = okx_business_candles["pushes"][-1]["data"][0]
    assert closed_row[8] == "1"
    bar = delivered[0]
    assert bar["ts"] == int(closed_row[0])
    assert bar["close"] == to_money(str(closed_row[4]))
    assert bar["high"] == to_money(str(closed_row[2]))
    # D-12: the live path stamps the routing keys from the provider's own trusted
    # config (self._symbol/self._timeframe) — NOT read from the venue row.
    assert bar["symbol"] == "BTC-USDT"
    assert bar["timeframe"] == "1d"


def test_confirm_gate_forming_rows_never_reach_sink(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No confirm=="0" (forming) close value ever appears in a delivered bar."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    delivered: list[ClosedBar] = []
    provider.set_bar_sink(delivered.append)

    _drive_stream(provider, okx_business_candles, monkeypatch)

    forming_closes = {
        to_money(str(p["data"][0][4]))
        for p in okx_business_candles["pushes"]
        if p["data"][0][8] == "0"
    }
    delivered_closes = {bar["close"] for bar in delivered}
    assert delivered_closes.isdisjoint(forming_closes)


# -------------------------------------------------------------- sandbox routing (CONN-03)


def test_sandbox_true_selects_wspap_business_host(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sandbox=True routes the native socket to the demo wspap host on /ws/v5/business."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)

    recorder = _drive_stream(provider, okx_business_candles, monkeypatch)

    assert recorder["url"] == "wss://wspap.okx.com:8443/ws/v5/business"


def test_sandbox_false_selects_live_business_host(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sandbox=False routes the native socket to the live ws.okx.com host — no wspap."""
    provider = OkxDataProvider(_StubConnector(sandbox=False), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)

    recorder = _drive_stream(provider, okx_business_candles, monkeypatch)

    assert recorder["url"] == "wss://ws.okx.com:8443/ws/v5/business"
    assert "wspap" not in recorder["url"]


def test_native_host_follows_connector_ws_hostname(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The native socket host follows connector.ws_hostname (region-derived, e.g. EEA demo)."""
    provider = OkxDataProvider(
        _StubConnector(sandbox=True, ws_hostname="wseeapap.okx.com"), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)

    recorder = _drive_stream(provider, okx_business_candles, monkeypatch)

    assert recorder["url"] == "wss://wseeapap.okx.com:8443/ws/v5/business"


def test_stream_subscribes_the_business_candle_channel(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stream sends the OKX subscribe op for the candle channel + instId."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)

    # Capture the fake ws to inspect what was sent.
    recorder: dict[str, Any] = {}
    messages = _messages_from(okx_business_candles)
    sent_holder: list[Any] = []

    class _CapturingWS(_FakeWS):
        async def send_json(self, obj: Any) -> None:
            sent_holder.append(obj)

    def _session_cls(*a: Any, **k: Any) -> Any:
        class _S:
            def __init__(self, *aa: Any, **kk: Any) -> None:
                pass

            async def __aenter__(self) -> Any:
                return self

            async def __aexit__(self, *exc: Any) -> bool:
                return False

            def ws_connect(self, url: str, **kwargs: Any) -> Any:
                recorder["url"] = url
                return _CapturingWS(messages)

            async def close(self) -> None:
                pass

        return _S(*a, **k)

    monkeypatch.setattr(aiohttp, "ClientSession", _session_cls)
    # One consume cycle, not the unbounded supervisor (see `_drive_stream`).
    asyncio.run(provider._connect_and_consume_candles("BTC-USDT", "candle1D", "BTC-USDT"))

    assert sent_holder == [
        {"op": "subscribe", "args": [{"channel": "candle1D", "instId": "BTC-USDT"}]}
    ]


# ------------------------------------------------------------ Decimal-edge backfill (CONN-05)


def test_backfill_returns_decimal_edge_bars(
    fake_ccxt_client: Any,
) -> None:
    """REST fetch_ohlcv backfill returns Decimal OHLCV byte-equal to to_money(str(raw))."""
    raw = [
        ["1704067200000", "42000.0", "42500.0", "41800.0", "42100.0", "1200.5"],
        ["1704153600000", "42100.0", "43000.0", "42000.0", "42900.0", "1500.2"],
    ]
    fake_ccxt_client.fetch_ohlcv = AsyncMock(return_value=raw)
    provider = OkxDataProvider(
        _StubConnector(sandbox=True, client=fake_ccxt_client), "BTC-USDT", "1d")

    bars = provider.fetch_ohlcv_backfill("BTC-USDT", "1d")

    assert len(bars) == 2
    for got, r in zip(bars, raw):
        assert isinstance(got["open"], Decimal)
        assert got["ts"] == int(r[0])
        assert got["open"] == to_money(str(r[1]))
        assert got["high"] == to_money(str(r[2]))
        assert got["low"] == to_money(str(r[3]))
        assert got["close"] == to_money(str(r[4]))
        assert got["volume"] == to_money(str(r[5]))
        # D-12: the backfill path stamps the routing keys from the method's own
        # params (the passed symbol/timeframe), so an ad-hoc backfill routes correctly.
        assert got["symbol"] == "BTC-USDT"
        assert got["timeframe"] == "1d"


def test_backfill_decimal_no_float_leaks(fake_ccxt_client: Any) -> None:
    """No float ever leaks into a backfilled bar (every field is a Decimal / int ts)."""
    raw = [["1704067200000", "42000.0", "42500.0", "41800.0", "42100.0", "1200.5"]]
    fake_ccxt_client.fetch_ohlcv = AsyncMock(return_value=raw)
    provider = OkxDataProvider(
        _StubConnector(sandbox=True, client=fake_ccxt_client), "BTC-USDT", "1d")

    bars = provider.fetch_ohlcv_backfill("BTC-USDT", "1d")

    bar = bars[0]
    for key in ("open", "high", "low", "close", "volume"):
        assert isinstance(bar[key], Decimal)
        assert not isinstance(bar[key], float)
    assert isinstance(bar["ts"], int)


def test_backfill_passes_unified_timeframe_to_ccxt(fake_ccxt_client: Any) -> None:
    """Backfill hands ccxt the UNIFIED timeframe ("1d"), not the OKX channel token ("1D").

    Regression: ccxt's unified ``fetch_ohlcv`` maps "1d" -> OKX "1D" itself; passing the
    OKX token makes ccxt's ``parse_timeframe`` reject unit "D" ("timeframe unit D is not
    supported"), which broke ``LiveTradingSystem.start()`` warmup backfill. The
    ``_okx_interval`` token is for the native business-candle channel name only.
    """
    raw = [["1704067200000", "42000.0", "42500.0", "41800.0", "42100.0", "1200.5"]]
    fake_ccxt_client.fetch_ohlcv = AsyncMock(return_value=raw)
    provider = OkxDataProvider(
        _StubConnector(sandbox=True, client=fake_ccxt_client), "BTC-USDT", "1d")

    provider.fetch_ohlcv_backfill("BTC-USDT", "1d")

    # Positional signature: fetch_ohlcv(symbol_okx, timeframe, since, limit)
    passed_timeframe = fake_ccxt_client.fetch_ohlcv.call_args.args[1]
    assert passed_timeframe == "1d"
    assert passed_timeframe != "1D"


def test_decimal_edge_no_float_leaks_in_streamed_bar(
    okx_business_candles: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No float leaks into a streamed closed bar — every OHLCV field is a Decimal."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    delivered: list[ClosedBar] = []
    provider.set_bar_sink(delivered.append)

    _drive_stream(provider, okx_business_candles, monkeypatch)

    bar = delivered[0]
    for key in ("open", "high", "low", "close", "volume"):
        assert isinstance(bar[key], Decimal)
        assert not isinstance(bar[key], float)
    assert isinstance(bar["ts"], int)


# ------------------------------------------------------------ malformed-row validation (V5)


def test_malformed_row_is_skipped_not_indexed(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short (< 9 field) row is skipped-and-logged, never blindly indexed at confirm."""
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    delivered: list[ClosedBar] = []
    provider.set_bar_sink(delivered.append)

    bad_push = {"arg": {"channel": "candle1D", "instId": "BTC-USDT"},
                "data": [["1704067200000", "42000.0"]]}  # only 2 fields
    good_row = ["1704067200000", "42000.0", "43100.0", "41750.0",
                "43050.0", "3900.2", "1", "1", "1"]
    good_push = {"arg": {"channel": "candle1D", "instId": "BTC-USDT"},
                 "data": [good_row]}
    fixture = {"pushes": [bad_push, good_push]}

    _drive_stream(provider, fixture, monkeypatch)

    # The malformed row did not crash the loop; the well-formed completed bar still arrived.
    assert len(delivered) == 1
    assert delivered[0]["close"] == to_money("43050.0")


# ----------------------------------------- reconnect supervisor (RES-01/D-19/D-20)
#
# These exercise ``_stream_candles`` THROUGH ``_run_stream_supervisor`` — the
# unbounded reconnect wrapper the confirm-gate/routing tests deliberately bypass.
# They pin the two guarantees that were previously untested (and whose absence hid
# the full-suite hang): the D-20 never-spin-forever HALT, and the WR-03 rule that
# only a POST-snapshot payload — not the OKX subscribe-time snapshot — resets the
# retry budget. Each fake session caps its reconnects so a REGRESSION fails fast
# instead of re-introducing an infinite loop.


class _StopLoop(BaseException):
    """Test sentinel used to bound an otherwise-healthy (infinite) reconnect loop.

    Subclasses ``BaseException`` (NOT ``Exception``) so it is a harness control-flow
    signal — like ``asyncio.CancelledError`` — that propagates cleanly out of the
    supervisor rather than being caught. After D-11 (V17-07) the supervisor grew an
    ``except Exception`` fail-safe catch-all that escalates any UNCLASSIFIED error to a
    HALT; an ``Exception`` sentinel here would be mis-treated as a real venue error and
    spuriously halt (masking the non-halt behaviour this test verifies).
    """


async def _instant_sleep(*_a: Any, **_k: Any) -> None:
    """No-op ``asyncio.sleep`` so the bounded-retry backoff runs instantly."""
    return None


def _candle_row(confirm: str) -> list[str]:
    """A well-formed OKX business candle row (9 fields; index 8 == ``confirm``)."""
    return ["1", "10", "10", "10", "10", "1", "1", "1", confirm]


def _candle_push(rows: list[list[str]]) -> dict[str, Any]:
    return {"arg": {"channel": "candle1D", "instId": "BTC-USDT"}, "data": rows}


def _looping_session_cls(
    messages: list[_FakeMsg],
    calls: list[str],
    *,
    cap: int,
    raise_on_call: int | None = None,
    exc: BaseException | None = None,
) -> type:
    """Fake ``ClientSession`` whose ``ws_connect`` re-yields ``messages`` every reconnect.

    Records each connect in ``calls``. ``cap`` converts a non-terminating reconnect
    (a regressed budget gate) into a fast ``AssertionError`` rather than a hang — the
    whole point of these tests is anti-hang behaviour. Optionally raises ``exc`` on
    the ``raise_on_call``-th connect to drive the fatal / bounded-loop paths.
    """

    class _Session:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def __aenter__(self) -> "_Session":
            return self

        async def __aexit__(self, *exc_info: Any) -> bool:
            return False

        def ws_connect(self, url: str, **kwargs: Any) -> _FakeWS:
            calls.append(url)
            if len(calls) > cap:
                raise AssertionError(
                    f"reconnect exceeded cap={cap} — supervisor failed to terminate")
            if raise_on_call is not None and len(calls) == raise_on_call and exc is not None:
                raise exc
            return _FakeWS(list(messages))

        async def close(self) -> None:
            pass

    return _Session


def test_supervisor_snapshot_only_storm_trips_ceiling_and_halts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscribe-then-close storm (only the OKX snapshot each cycle) exhausts the
    retry ceiling and HALTS, then RETURNS — the D-20 never-spin-forever guarantee.

    OKX pushes exactly one in-progress snapshot on every subscribe, so a cycle that
    delivers only that snapshot must NOT reset the retry budget (no post-snapshot
    payload). After ``_reconnect_ceiling`` reconnects the supervisor escalates
    ``halt('connector-fatal')`` and the coroutine returns — it does not loop forever.
    """
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)
    halts: list[str] = []
    provider.set_halt_signal(halts.append)
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    calls: list[str] = []
    snapshot_only = [_FakeMsg(json.dumps(_candle_push([_candle_row("0")])))]
    monkeypatch.setattr(
        aiohttp, "ClientSession",
        _looping_session_cls(snapshot_only, calls, cap=provider._reconnect_ceiling + 5))

    asyncio.run(provider._stream_candles("BTC-USDT", "candle1D", "BTC-USDT"))

    # Halted exactly once with the scrubbed fixed reason after ceiling+1 attempts.
    assert halts == ["connector-fatal"]
    assert provider._reconnect_attempts["BTC-USDT"] == provider._reconnect_ceiling + 1
    assert len(calls) == provider._reconnect_ceiling + 1


def test_supervisor_post_snapshot_payload_resets_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A payload delivered AFTER the subscribe snapshot proves real streaming and
    RESETS the retry budget — a healthy, flapping stream never false-halts (WR-03).

    Each cycle delivers the snapshot AND a second candle row, so
    ``_reset_reconnect_budget`` fires and ``attempt`` never climbs to the ceiling. We
    run well past ``_reconnect_ceiling`` cycles and assert NO halt was escalated; a
    ``_StopLoop`` sentinel bounds the otherwise-healthy (infinite) loop.
    """
    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)
    halts: list[str] = []
    provider.set_halt_signal(halts.append)
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    calls: list[str] = []
    two_payloads = [
        _FakeMsg(json.dumps(_candle_push([_candle_row("0")]))),  # subscribe snapshot
        _FakeMsg(json.dumps(_candle_push([_candle_row("0")]))),  # post-snapshot payload
    ]
    stop_after = provider._reconnect_ceiling + 4  # run WELL past the ceiling
    monkeypatch.setattr(
        aiohttp, "ClientSession",
        _looping_session_cls(two_payloads, calls, cap=stop_after + 5,
                             raise_on_call=stop_after, exc=_StopLoop()))

    with pytest.raises(_StopLoop):
        asyncio.run(provider._stream_candles("BTC-USDT", "candle1D", "BTC-USDT"))

    # Ran past the ceiling with zero halts — the reset kept attempt from climbing.
    assert halts == []
    assert len(calls) == stop_after
    assert provider._reconnect_attempts["BTC-USDT"] <= 1


def test_supervisor_fatal_error_halts_immediately_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fatal auth/permission error escalates halt at once — no bounded-retry loop."""
    import ccxt

    provider = OkxDataProvider(_StubConnector(sandbox=True), "BTC-USDT", "1d")
    provider.set_bar_sink(lambda _b: None)
    halts: list[str] = []
    provider.set_halt_signal(halts.append)
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)

    calls: list[str] = []
    monkeypatch.setattr(
        aiohttp, "ClientSession",
        _looping_session_cls([], calls, cap=5, raise_on_call=1,
                             exc=ccxt.AuthenticationError("bad key")))

    asyncio.run(provider._stream_candles("BTC-USDT", "candle1D", "BTC-USDT"))

    assert halts == ["connector-fatal"]
    assert len(calls) == 1                                       # halted on first attempt
    assert provider._reconnect_attempts.get("candles", 0) == 0  # fatal skips attempt++
