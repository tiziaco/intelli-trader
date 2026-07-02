"""Reconnect supervisor + failure classification for the OKX stream loops (RES-01/D-19/D-20).

The venue stream consume-loops (``OkxExchange._stream_fills``/``_stream_orders`` and
``OkxDataProvider._stream_candles``) had NO reconnect today (a code-verified gap): a socket
drop killed the task silently. This suite proves the bounded-retry reconnect supervisor that
now wraps each consume-loop:

Task 1 (supervisor + classification):
- a **transient** error (``ccxt.NetworkError``/``RequestTimeout``/``DDoSProtection``)
  reconnects with exponential backoff and the stream SURVIVES (publish-and-continue);
- a **fatal** error (``ccxt.AuthenticationError``/``PermissionDenied``) escalates to the
  injected halt entrypoint (HALTED, reason ``'connector-fatal'``) — never retried;
- the **retry ceiling exhausted** escalates the same halt — never spins forever (D-20);
- the CRITICAL alert that the halt emits carries NO secret substring (Pitfall 16, T-05-27).

Task 2 (pause-on-disconnect / resume-after-reconcile, D-19):
- a sustained disconnect PAUSES new order submission (existing state untouched);
- a reconnect + a fresh REST snapshot/reconcile RESUMES submission and clears the pause;
- a sub-second blip (recovers on the first retry, within the debounce) does NOT pause.

Driven offline: the supervisor is exercised directly with a scripted consume coroutine on a
per-test ``asyncio.run`` loop (created + closed cleanly so nothing escapes into the strict
``filterwarnings=["error"]`` suite). No real sockets. Folder-derived ``unit`` marker.
"""

import asyncio
import queue
from typing import Any, Callable, Optional
from unittest.mock import MagicMock

import ccxt
import pytest

from itrader.core.enums import ErrorSeverity, EventType, SystemStatus
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.price_handler.providers.okx_provider import OkxDataProvider
from itrader.trading_system.live_trading_system import LiveTradingSystem

_SECRET = "OKX_API_SECRET-supersecret-0xDEADBEEF"


# --- scripted consume double -------------------------------------------------


class _StopSupervisor(Exception):
    """Unclassified sentinel: breaks the supervisor loop cleanly in a test.

    Neither transient nor fatal, so the supervisor does not catch it — it propagates out,
    ending the ``asyncio.run`` without hanging on the forever reconnect loop.
    """


class _ScriptedConsume:
    """A consume coroutine driven by a step script (one step per connection attempt).

    Each ``__call__`` is one supervisor iteration:
    - ``"transient"`` -> raise ``ccxt.NetworkError`` (reconnect);
    - ``"fatal"`` -> raise ``ccxt.AuthenticationError`` carrying a secret in its message;
    - ``"ok"`` -> signal healthy (reset backoff / resume) then return cleanly;
    - ``"ok_stop"`` -> signal healthy then raise ``_StopSupervisor`` (break a
      reconnect-on-clean-return supervisor, e.g. the provider's).
    """

    def __init__(
        self, steps: list[str], on_healthy: Optional[Callable[[str], None]] = None
    ) -> None:
        self._steps = list(steps)
        self._i = 0
        self.calls = 0
        self._on_healthy = on_healthy

    async def __call__(self, stream_name: str) -> None:
        step = self._steps[self._i] if self._i < len(self._steps) else "transient"
        self._i += 1
        self.calls += 1
        if step == "transient":
            raise ccxt.NetworkError("transient socket blip")
        if step == "fatal":
            raise ccxt.AuthenticationError(f"auth rejected: {_SECRET}")
        # "ok" / "ok_stop": reconnected successfully.
        if self._on_healthy is not None:
            self._on_healthy(stream_name)
        if step == "ok_stop":
            raise _StopSupervisor()
        return


def _fast(component: Any) -> None:
    """Shrink the debounce/backoff so the supervisor test runs instantly."""
    component._reconnect_debounce_s = 0.0
    component._reconnect_backoff_base_s = 0.0
    component._reconnect_backoff_cap_s = 0.0


class _Recorder:
    """Records the reasons / stream names a supervisor callback is fired with."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, value: str) -> None:
        self.calls.append(value)


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def okx_exchange() -> OkxExchange:
    exchange = OkxExchange(queue.Queue(), MagicMock(name="connector"))
    _fast(exchange)
    return exchange


@pytest.fixture
def okx_provider() -> OkxDataProvider:
    provider = OkxDataProvider(MagicMock(name="connector"), symbol="BTC/USDT", timeframe="1d")
    _fast(provider)
    return provider


# --- transient -> reconnect + survive (D-19/D-20) ----------------------------


def test_okx_exchange_transient_error_reconnects_and_survives(okx_exchange: OkxExchange) -> None:
    """A sustained transient drop reconnects; the stream survives and never halts."""
    halt = _Recorder()
    down = _Recorder()
    up = _Recorder()
    okx_exchange.set_halt_signal(halt)
    okx_exchange.set_stream_state_listener(down, up)

    # transient (blip attempt 1), transient (attempt 2 -> pause), then reconnect.
    consume = _ScriptedConsume(
        ["transient", "transient", "ok"], on_healthy=okx_exchange._on_stream_healthy)
    asyncio.run(okx_exchange._run_stream_supervisor(consume, "fills"))

    assert halt.calls == []                      # never halted on a transient
    assert down.calls == ["fills"]               # paused once past the debounce
    assert up.calls == ["fills"]                 # resumed on reconnect
    assert "fills" not in okx_exchange._streams_down


def test_okx_provider_transient_error_reconnects_and_survives(
    okx_provider: OkxDataProvider,
) -> None:
    """The candle stream reconnects a transient drop and survives (mirror of the order arm)."""
    halt = _Recorder()
    down = _Recorder()
    up = _Recorder()
    okx_provider.set_halt_signal(halt)
    okx_provider.set_stream_state_listener(down, up)

    consume = _ScriptedConsume(
        ["transient", "transient", "ok_stop"], on_healthy=okx_provider._on_stream_healthy)
    with pytest.raises(_StopSupervisor):
        asyncio.run(okx_provider._run_stream_supervisor(consume, "candles"))

    assert halt.calls == []
    assert down.calls == ["candles"]
    assert up.calls == ["candles"]


# --- fatal error -> HALTED (D-20) --------------------------------------------


def test_okx_exchange_fatal_error_halts(okx_exchange: OkxExchange) -> None:
    """A fatal auth error escalates to the halt entrypoint with reason 'connector-fatal'."""
    halt = _Recorder()
    okx_exchange.set_halt_signal(halt)

    consume = _ScriptedConsume(["fatal"])
    asyncio.run(okx_exchange._run_stream_supervisor(consume, "fills"))

    assert halt.calls == ["connector-fatal"]
    assert consume.calls == 1                     # fatal is never retried


def test_okx_provider_fatal_error_halts(okx_provider: OkxDataProvider) -> None:
    halt = _Recorder()
    okx_provider.set_halt_signal(halt)

    consume = _ScriptedConsume(["fatal"])
    asyncio.run(okx_provider._run_stream_supervisor(consume, "candles"))

    assert halt.calls == ["connector-fatal"]
    assert consume.calls == 1


# --- retry ceiling exhausted -> HALTED (D-20) --------------------------------


def test_okx_exchange_retry_ceiling_exhausted_halts(okx_exchange: OkxExchange) -> None:
    """Endless transient drops exhaust the retry ceiling and halt — never spin forever."""
    halt = _Recorder()
    okx_exchange.set_halt_signal(halt)
    okx_exchange._reconnect_ceiling = 3

    consume = _ScriptedConsume(["transient"] * 20)   # always transient
    asyncio.run(okx_exchange._run_stream_supervisor(consume, "fills"))

    assert halt.calls == ["connector-fatal"]
    # attempts 1..3 retried, attempt 4 > ceiling -> halt (bounded, never unbounded).
    assert consume.calls == 4


def test_okx_provider_retry_ceiling_exhausted_halts(okx_provider: OkxDataProvider) -> None:
    halt = _Recorder()
    okx_provider.set_halt_signal(halt)
    okx_provider._reconnect_ceiling = 3

    consume = _ScriptedConsume(["transient"] * 20)
    asyncio.run(okx_provider._run_stream_supervisor(consume, "candles"))

    assert halt.calls == ["connector-fatal"]
    assert consume.calls == 4


# --- no secret leaks into the CRITICAL alert (Pitfall 16, T-05-27) ------------


def _live_system(monkeypatch: Any) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    return LiveTradingSystem(exchange="binance")


class _RecordingSink:
    def __init__(self) -> None:
        self.received: list[Any] = []

    def alert(self, event: Any) -> None:
        self.received.append(event)


def test_fatal_alert_carries_no_secret_substring(monkeypatch: Any) -> None:
    """The CRITICAL alert emitted on a fatal connector error carries no secret.

    The exception message deliberately embeds a secret; the supervisor passes only the
    fixed reason 'connector-fatal' to halt() (never str(exc)), so the ErrorEvent egress
    cannot leak it (T-05-27).
    """
    system = _live_system(monkeypatch)
    sink = _RecordingSink()
    system.event_handler._alert_sink = sink

    exchange = OkxExchange(system.global_queue, MagicMock(name="connector"))
    _fast(exchange)
    exchange.set_halt_signal(system.halt)

    consume = _ScriptedConsume(["fatal"])         # raises AuthenticationError with _SECRET
    asyncio.run(exchange._run_stream_supervisor(consume, "fills"))

    # Drain the CRITICAL halt ErrorEvent through the ERROR route -> alert sink.
    system.event_handler.process_events()
    assert len(sink.received) == 1
    event = sink.received[0]
    assert event.severity == ErrorSeverity.CRITICAL
    emitted = " ".join(
        str(getattr(event, f))
        for f in ("source", "error_type", "error_message", "operation")
    )
    assert _SECRET not in emitted
    assert "supersecret" not in emitted


# --- Task 2: pause-on-disconnect / resume-after-reconcile (D-19) --------------


def test_blip_within_debounce_does_not_pause(okx_exchange: OkxExchange) -> None:
    """A single transient that recovers on the first retry does NOT pause (D-19 debounce)."""
    down = _Recorder()
    up = _Recorder()
    okx_exchange.set_stream_state_listener(down, up)

    # One transient (attempt 1, within the debounce), then reconnect.
    consume = _ScriptedConsume(
        ["transient", "ok"], on_healthy=okx_exchange._on_stream_healthy)
    asyncio.run(okx_exchange._run_stream_supervisor(consume, "fills"))

    assert down.calls == []                        # a blip never pauses
    assert up.calls == []                          # never went down -> no resume


def test_pause_submission_suppresses_new_orders_but_not_bar_fill(monkeypatch: Any) -> None:
    """pause_submission quiesces NEW SIGNAL/ORDER while BAR/FILL continue (freeze-in-place)."""
    system = _live_system(monkeypatch)
    system.pause_submission("paused-on-disconnect")
    system.event_handler._dispatch = MagicMock()

    for etype in (EventType.ORDER, EventType.SIGNAL):
        ev = MagicMock()
        ev.type = etype
        system._dispatch_live(ev)
    system.event_handler._dispatch.assert_not_called()

    for etype in (EventType.BAR, EventType.FILL):
        ev = MagicMock()
        ev.type = etype
        system._dispatch_live(ev)
    assert system.event_handler._dispatch.call_count == 2


def test_get_status_surfaces_paused_state_distinctly(monkeypatch: Any) -> None:
    """The paused-on-disconnect state is surfaced distinctly on get_status (not HALTED)."""
    system = _live_system(monkeypatch)
    assert system.get_status()["paused"] is False

    system.pause_submission("paused-on-disconnect")
    status = system.get_status()
    assert status["paused"] is True
    assert status["paused_reason"] == "paused-on-disconnect"
    # Distinct from a terminal halt — the engine is not HALTED, just quiesced.
    assert status["status"] != SystemStatus.HALTED.value


def test_resume_after_reconnect_snapshots_then_clears_pause(monkeypatch: Any) -> None:
    """The engine-thread resume takes a fresh REST snapshot then clears the pause (D-19)."""
    system = _live_system(monkeypatch)
    venue = MagicMock(name="venue_account")
    system._venue_account = venue
    system.pause_submission("paused-on-disconnect")

    # The connector-loop reconnect callback only flags a resume (no blocking I/O).
    system._on_venue_stream_up("fills")
    assert system.get_status()["paused"] is True   # not resumed on the connector thread
    venue.snapshot.assert_not_called()

    # The engine thread performs the fresh REST snapshot + reconcile, then resumes.
    system._maybe_resume_after_reconnect()
    venue.snapshot.assert_called_once()            # don't trade when you can't see the venue
    assert system.get_status()["paused"] is False


def test_pause_does_not_fire_while_halted(monkeypatch: Any) -> None:
    """A terminal halt supersedes a reversible pause — pause_submission is a no-op then."""
    system = _live_system(monkeypatch)
    system.halt("connector-fatal")
    system.pause_submission("paused-on-disconnect")
    status = system.get_status()
    assert status["status"] == SystemStatus.HALTED.value
    assert status["paused"] is False
