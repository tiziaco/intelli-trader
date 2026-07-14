"""A6 (D-11 / V17-07) RED gate — a stream supervisor must FAIL SAFE, never die silently.

CONF-A spine (D-19), Wave-1 slice 3. This is an EXPECTED-FAILING regression test: it
pins the V17-07 silent-task-death bug and turns GREEN only once the D-11 stream catch-all
lands in Phase 05.3. It MUST be RED against current code — that is the success condition of
a CONF-A spine plan, NOT a broken build.

The bug (V17-07)
----------------
The reconnect supervisor (``OkxExchange._run_stream_supervisor`` / the mirror on
``OkxDataProvider``) classifies exactly two exception families:

- **transient** (``ccxt.NetworkError`` / ``RequestTimeout`` / ``DDoSProtection`` [+ the
  provider's aiohttp/connection set]) -> reconnect with backoff;
- **fatal** (``ccxt.AuthenticationError`` / ``PermissionDenied``) -> halt.

Anything ELSE — a plain ``ccxt.ExchangeError`` (the base venue error), a
``json.JSONDecodeError`` from the provider's UNGUARDED ``json.loads`` at
``okx_provider.py:274`` (OUTSIDE the per-message guard), a ``KeyError``/``TypeError`` from a
malformed payload — falls straight THROUGH the try/except and propagates out of the consume
loop, so the ``asyncio`` task dies with NO reconnect and NO halt. The venue stream is now
dead and the engine never notices (fills/candles stop; state silently freezes).

Worse: ``VenueAccount._stream_account`` / ``_stream_positions`` (``venue.py:160``/``:175``)
are BARE ``while True`` loops with NO supervisor AT ALL — a single ``NetworkError`` kills the
balance/position cache writer outright and the cache freezes forever.

The fix (D-11, Phase 05.3)
--------------------------
A catch-all arm on every supervisor: an UNEXPECTED (unclassified) exception escalates to the
injected halt entrypoint (fail-safe HALT, never silent death), the provider's ``json.loads``
is guarded per-message, and the two ``VenueAccount`` streams are wrapped in the same
bounded-retry supervisor so a transient drop survives / escalates rather than dying.

Security (V7 / T-05-27): the escalation must carry only ``type(exc).__name__`` — NEVER
``str(exc)`` — so a venue error embedding a secret/request-context cannot leak into the
CRITICAL alert egress. The order-arm case embeds a secret in the exception message and
asserts it is scrubbed.

Import-clean, fully offline: scripted consume doubles + fake aiohttp sessions on a per-test
``asyncio.run`` loop (created + closed cleanly, Pitfall 4, ``filterwarnings=["error"]``). No
network, no credentials. Folder-derived ``unit`` marker.
"""

import asyncio
import json
from queue import Queue
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import ccxt
import pytest

from itrader.core.enums import ErrorSeverity
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.portfolio_handler.account.venue import VenueAccount
from itrader.price_handler.providers.okx_provider import OkxDataProvider
from itrader.trading_system.live_trading_system import LiveTradingSystem

_SECRET = "OKX_API_SECRET-supersecret-0xDEADBEEF"


# --- doubles -----------------------------------------------------------------


class _StopLoop(Exception):
    """Unclassified sentinel: breaks an otherwise-infinite loop cleanly in a test.

    Neither transient nor fatal, so the supervisor does not catch it — it propagates out,
    ending the ``asyncio.run`` without hanging on a forever reconnect / stream loop.
    """


class _RaiseConsume:
    """A supervisor consume coroutine that raises a fixed exception on the first call."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls = 0

    async def __call__(self, stream_name: str) -> None:
        self.calls += 1
        raise self._exc


class _GarbageJsonSession:
    """Fake ``aiohttp.ClientSession`` that delivers ONE garbage-JSON text frame on subscribe.

    Drives the REAL ``OkxDataProvider._connect_and_consume_candles`` through its unguarded
    ``json.loads(msg.data)`` site (``okx_provider.py:274``): the frame is not valid JSON, so
    ``json.loads`` raises ``json.JSONDecodeError``. Today the supervisor does not classify it
    -> the task dies. One object plays both the session and the ws (mirrors the existing
    reconnect-resilience fakes).
    """

    def __init__(self, *, cap: int = 50) -> None:
        self._cap = cap
        self.connects = 0

    def __call__(self) -> "_GarbageJsonSession":
        return self

    async def __aenter__(self) -> "_GarbageJsonSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def ws_connect(self, url: str, **kwargs: Any) -> "_GarbageJsonSession":
        self.connects += 1
        if self.connects > self._cap:
            raise _StopLoop()  # safety valve: never hang if a fix loops instead of raising
        return self

    async def send_json(self, payload: Any) -> None:
        return None

    def __aiter__(self) -> "_GarbageJsonSession":
        self._yielded = False
        return self

    async def __anext__(self) -> Any:
        if self._yielded:
            raise StopAsyncIteration  # socket closed after the one garbage frame
        self._yielded = True
        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.TEXT
        msg.data = "{not-valid-json"  # garbage -> json.loads raises JSONDecodeError
        return msg


class _Recorder:
    """Records the reasons a supervisor halt/state callback is fired with."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, value: str) -> None:
        self.calls.append(value)


class _RecordingSink:
    """Captures alert egress so the halt CRITICAL ErrorEvent can be inspected for secrets."""

    def __init__(self) -> None:
        self.received: list[Any] = []

    def alert(self, event: Any) -> None:
        self.received.append(event)


def _fast(component: Any) -> None:
    """Shrink the debounce/backoff so a supervisor test runs instantly."""
    component._supervisor._reconnect_debounce_s = 0.0
    component._supervisor._reconnect_backoff_base_s = 0.0
    component._supervisor._reconnect_backoff_cap_s = 0.0


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    return LiveTradingSystem.for_exchange("binance")


# --- (1a) order arm: an unclassified venue error must HALT, not die silently --


def test_supervisor_catchall_order_arm_unexpected_error_halts(monkeypatch: Any) -> None:
    """An unexpected ``ccxt.ExchangeError`` in the consume loop must escalate to a HALT (A6).

    RED today: ``ExchangeError`` is neither transient nor fatal, so it falls through the
    supervisor and the task dies silently — no CRITICAL halt alert is ever emitted. GREEN
    after D-11 (Phase 05.3) adds the catch-all. The exception embeds a secret; the halt
    escalation must scrub it (V7 / T-05-27).
    """
    system = _live_system(monkeypatch)
    sink = _RecordingSink()
    system.event_handler._alert_sink = sink

    exchange = OkxExchange(system.global_queue, MagicMock(name="connector"))
    _fast(exchange)
    exchange.set_halt_signal(system.halt)

    consume = _RaiseConsume(ccxt.ExchangeError(f"venue rejected order: {_SECRET}"))
    try:
        # Today the unclassified error propagates out and the task dies silently.
        asyncio.run(exchange._supervisor.run(consume, "fills"))
    except ccxt.ExchangeError:
        pass  # RED: unclassified error kills the task; GREEN: the supervisor halts instead.

    # Drain the CRITICAL halt ErrorEvent through the ERROR route -> alert sink.
    system.event_handler.process_events()
    critical = [
        e for e in sink.received
        if getattr(e, "severity", None) == ErrorSeverity.CRITICAL
    ]
    assert len(critical) == 1, (
        "A6/V17-07: an unexpected ccxt.ExchangeError in the stream consume loop was NOT "
        "escalated to a halt — the supervisor classifies only the NetworkError/Auth "
        "families, so an unclassified error falls through and the task dies silently. "
        "D-11 (Phase 05.3) must add a fail-safe catch-all that HALTS."
    )
    # Secret-scrub (V7 / T-05-27): the escalation carries the exception TYPE only.
    emitted = " ".join(
        str(getattr(critical[0], f))
        for f in ("source", "error_type", "error_message", "operation")
    )
    assert _SECRET not in emitted
    assert "supersecret" not in emitted


# --- (1b) provider arm: garbage JSON must HALT, not die silently --------------


def test_supervisor_catchall_provider_garbage_json_halts(monkeypatch: Any) -> None:
    """A garbage-JSON frame through the provider's unguarded ``json.loads`` must HALT (A6).

    RED today: ``json.JSONDecodeError`` is not classified by the supervisor -> it propagates
    out of ``_connect_and_consume_candles`` and the candle task dies silently (paper-parity
    starves for bars). GREEN after D-11 guards ``json.loads`` per-message / adds the catch-all.
    """
    provider = OkxDataProvider(
        MagicMock(name="connector"), symbol="BTC/USDT", timeframe="1d")
    _fast(provider)
    halt = _Recorder()
    provider.set_halt_signal(halt)

    session = _GarbageJsonSession()
    monkeypatch.setattr(
        "itrader.price_handler.providers.okx_provider.aiohttp.ClientSession", session)

    async def _consume(_stream_name: str) -> None:
        await provider._connect_and_consume_candles("BTC-USDT", "candle1D")

    try:
        asyncio.run(provider._supervisor.run(_consume, "candles"))
    except (json.JSONDecodeError, _StopLoop):
        pass  # RED: the unguarded json.loads raises and the task dies; GREEN: it halts.

    assert halt.calls == ["connector-fatal"], (
        "A6/V17-07: a garbage-JSON frame through the provider's UNGUARDED json.loads "
        "(okx_provider.py:274, outside the per-message guard) killed the candle task "
        "silently instead of halting — the supervisor does not classify JSONDecodeError. "
        "D-11 (Phase 05.3) must guard json.loads per-message / add the fail-safe catch-all."
    )


# --- (2) VenueAccount streams: a NetworkError must not kill the cache writer ---


def test_supervisor_catchall_venue_stream_survives_networkerror() -> None:
    """``VenueAccount._stream_account`` must survive a single ``NetworkError`` (A6).

    RED today: ``_stream_account`` is a BARE ``while True`` with NO supervisor — the first
    ``NetworkError`` kills the balance-cache writer outright, so the post-blip balance is
    never written and the cache freezes at ``None``. GREEN after D-11 wraps it in the same
    bounded-retry supervisor: the transient drop is survived and the recovered balance lands.

    NOTE (Phase 05.3 implementer — assertion premise invalidated by commit 30cfb73):
    the ``_venue_balance == 123.45`` assertion below no longer expresses stream survival.
    The cash-double-count fix made the balance stream (``_write_balance_stream``) write
    POSITIONS ONLY — ``_venue_balance`` is now written SOLELY by ``snapshot()`` (single-
    channel cash, D-01). So even AFTER D-11 adds the reconnect supervisor, this test will
    STILL fail on the ``_venue_balance`` check, because the stream deliberately never writes
    the cash baseline anymore. When you implement D-11, RE-EXPRESS the survival assertion
    another way (e.g. assert a positions write after recovery, or spy the recovery
    iteration) — do NOT resurrect a stream-side ``_venue_balance`` write to satisfy it.
    """
    client = MagicMock(name="ccxt_pro_client")
    good_balance = {"total": {"USDT": 123.45}, "free": {"USDT": 100.0}}
    # blip -> recovered balance -> stop. Today the loop dies on the blip and never reaches
    # the recovered balance; a supervised loop survives it and writes 123.45.
    client.watch_balance = AsyncMock(
        name="watch_balance",
        side_effect=[ccxt.NetworkError("socket blip"), good_balance, _StopLoop()],
    )
    connector = MagicMock(name="connector")
    connector.client = client

    venue = VenueAccount(connector, quote_currency="USDT")
    try:
        asyncio.run(venue._stream_account())
    except Exception:
        # RED: the bare while-True dies on the NetworkError (task death is modelled here).
        # GREEN: the supervisor breaks on the _StopLoop sentinel after the recovery write.
        pass

    # D-11 re-expression (per docstring / 30cfb73): the balance stream deliberately no
    # longer writes _venue_balance (cash is snapshot()-only, single-channel), so stream
    # SURVIVAL is asserted via the recovery iteration rather than a cache value. A bare
    # `while True` dies on the first NetworkError -> watch_balance is called exactly ONCE
    # and never reaches the recovered frame. The supervised loop retries the transient
    # blip, consumes the recovered good_balance, and only stops on the unclassified
    # _StopLoop -> watch_balance is called all THREE times (blip, recovery, stop).
    assert client.watch_balance.call_count == 3, (
        "A6/V17-07: VenueAccount._stream_account is a bare `while True` with no reconnect "
        "supervisor — a single NetworkError killed the balance-cache writer silently "
        f"(watch_balance called {client.watch_balance.call_count}x, never reaching the "
        "post-blip recovery). D-11 (Phase 05.3) must wrap the venue streams in the "
        "bounded-retry supervisor so a transient drop survives / an unknown error escalates."
    )
