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
import json
import queue
from datetime import UTC, datetime
from typing import Any, Callable, Optional
from unittest.mock import MagicMock

import aiohttp
import ccxt
import pytest

from itrader.core.enums import ErrorSeverity, EventType, SystemStatus
from itrader.events_handler.events import ErrorEvent
from itrader.execution_handler.exchanges.okx import OkxExchange
from itrader.price_handler.providers.okx_provider import OkxDataProvider
from itrader.trading_system.live_trading_system import LiveTradingSystem

_SECRET = "OKX_API_SECRET-supersecret-0xDEADBEEF"


# --- scripted consume double -------------------------------------------------


class _StopSupervisor(BaseException):
    """Harness control-flow sentinel: breaks the supervisor loop cleanly in a test.

    Subclasses ``BaseException`` (NOT ``Exception``) so it is a control-flow signal —
    like ``asyncio.CancelledError`` — that the supervisor does NOT catch: it propagates
    out, ending the ``asyncio.run`` without hanging on the forever reconnect loop. After
    D-11 (V17-07) the supervisor grew an ``except Exception`` fail-safe catch-all that
    escalates any UNCLASSIFIED error to a HALT; an ``Exception`` sentinel here would be
    mis-treated as a real venue error and spuriously halt (masking the non-halt / clean
    loop-break behaviour these tests verify).
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


class _SubscribeCloseStorm:
    """Models an OKX subscribe-then-close storm (server-side churn, WR-03).

    Each supervisor iteration signals a healthy *subscribe* (via ``on_healthy``) and then
    the connection drops WITHOUT ever delivering a payload. Pre-WR-03 the subscribe reset
    the retry budget (``_on_stream_healthy`` zeroed ``_reconnect_attempts``), pinning
    ``attempt`` at 1 forever so the D-20 ceiling could never trip and the loop reconnected
    endlessly. A hard ``cap`` raises ``_StopSupervisor`` so the pre-fix forever-loop cannot
    hang the strict suite.

    ``drop='transient'`` -> raise ``ccxt.NetworkError`` (the order-arm consume never
    returns cleanly; a drop raises). ``drop='clean'`` -> return cleanly (the provider arm
    treats a clean return as a server-closed socket and reconnects).
    """

    def __init__(
        self, on_healthy: Callable[[str], None], *, drop: str, cap: int = 50
    ) -> None:
        self._on_healthy = on_healthy
        self._drop = drop
        self._cap = cap
        self.calls = 0

    async def __call__(self, stream_name: str) -> None:
        self.calls += 1
        if self.calls > self._cap:
            raise _StopSupervisor()          # safety valve: never hang the pre-fix loop
        self._on_healthy(stream_name)        # subscribe ack — NO payload delivered
        if self._drop == "transient":
            raise ccxt.NetworkError("socket closed right after subscribe")
        return                                # 'clean' — server closed the socket


class _SnapshotThenCloseSession:
    """Fake ``aiohttp.ClientSession`` modelling OKX's candle SNAPSHOT-on-subscribe (WR-03).

    Verified against the OKX demo venue: subscribing ``candle{tf}`` pushes the subscribe ACK
    plus an in-progress-candle SNAPSHOT (one row, ``confirm='0'``) within ~30ms, BEFORE any
    real streaming, then — in a server-side churn storm — the socket closes. Each ``__call__``
    (one ``aiohttp.ClientSession()`` per supervisor reconnect) yields ``[ACK, snapshot]`` then
    ends iteration (clean socket close). A shared ``cap`` raises ``_StopSupervisor`` so the
    PRE-fix forever-loop (snapshot resets the budget every cycle -> ceiling never trips) cannot
    hang the strict suite; POST-fix the snapshot no longer resets, so the ceiling trips first.
    """

    def __init__(self, state: dict[str, int], *, cap: int = 50) -> None:
        self._state = state
        self._cap = cap
        self._msgs = [
            {"event": "subscribe", "arg": {"channel": "candle1D", "instId": "BTC-USDT"}},
            # one in-progress snapshot row (>=9 fields, confirm='0' at index 8) — dropped by
            # the confirm gate, but it IS a delivered `data` payload on subscribe.
            {"arg": {"channel": "candle1D", "instId": "BTC-USDT"},
             "data": [["1700000000000", "1", "2", "0.5", "1.5", "10", "10", "10", "0"]]},
        ]

    def __call__(self) -> "_SnapshotThenCloseSession":
        return self

    async def __aenter__(self) -> "_SnapshotThenCloseSession":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    def ws_connect(self, url: str, **kwargs: Any) -> "_SnapshotThenCloseSession":
        self._state["connects"] = self._state.get("connects", 0) + 1
        if self._state["connects"] > self._cap:
            raise _StopSupervisor()          # safety valve: never hang the pre-fix loop
        return self

    async def send_json(self, payload: Any) -> None:
        return None

    def __aiter__(self) -> "_SnapshotThenCloseSession":
        self._it = iter(self._msgs)
        return self

    async def __anext__(self) -> Any:
        try:
            raw = next(self._it)
        except StopIteration:
            raise StopAsyncIteration      # socket closed -> supervisor reconnects
        msg = MagicMock()
        msg.type = aiohttp.WSMsgType.TEXT
        msg.data = json.dumps(raw)
        return msg


def _drive_storm(coro: Any) -> None:
    """Run a supervisor coroutine, swallowing the pre-fix safety-valve stop.

    Pre-WR-03 a subscribe-then-close storm never halts, so the storm double's ``cap``
    raises ``_StopSupervisor`` to break the forever loop. Swallowing it lets the assertion
    (``halt`` fired) report the defect as a clean failure rather than an error.
    """
    try:
        asyncio.run(coro)
    except _StopSupervisor:
        pass


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


# --- WR-03: subscribe-then-close storm exhausts the ceiling and halts ---------


def test_okx_exchange_subscribe_close_storm_exhausts_ceiling_and_halts(
    okx_exchange: OkxExchange,
) -> None:
    """A subscribe-then-close storm exhausts the retry ceiling and HALTS (WR-03/D-20).

    A subscribe is not proof of health — only a delivered payload may reset the retry
    budget. Pre-fix ``_on_stream_healthy`` reset the budget on every subscribe, pinning
    ``attempt`` at 1 so the ceiling could never trip and the supervisor reconnected
    forever (silently defeating the D-20 never-spin-forever HALT guarantee).
    """
    halt = _Recorder()
    okx_exchange.set_halt_signal(halt)
    okx_exchange._reconnect_ceiling = 3

    storm = _SubscribeCloseStorm(okx_exchange._on_stream_healthy, drop="transient")
    _drive_storm(okx_exchange._run_stream_supervisor(storm, "fills"))

    assert halt.calls == ["connector-fatal"]   # ceiling tripped despite the subscribe storm
    assert storm.calls == 4                     # attempts 1..3 retried, attempt 4 > ceiling -> halt


def test_okx_provider_subscribe_close_storm_exhausts_ceiling_and_halts(
    okx_provider: OkxDataProvider,
) -> None:
    """The candle arm halts on a subscribe-then-close storm too (mirror of the order arm)."""
    halt = _Recorder()
    okx_provider.set_halt_signal(halt)
    okx_provider._reconnect_ceiling = 3

    storm = _SubscribeCloseStorm(okx_provider._on_stream_healthy, drop="clean")
    _drive_storm(okx_provider._run_stream_supervisor(storm, "candles"))

    assert halt.calls == ["connector-fatal"]
    assert storm.calls == 4


def test_okx_provider_snapshot_on_subscribe_storm_exhausts_ceiling_and_halts(
    okx_provider: OkxDataProvider,
    monkeypatch: Any,
) -> None:
    """A subscribe-then-close storm HALTS even though OKX pushes a SNAPSHOT on subscribe (WR-03).

    The offline ``_SubscribeCloseStorm`` above models a subscribe with NO payload; ONLINE the
    OKX candle channel ALWAYS delivers an in-progress-candle snapshot (confirm='0', ~30ms) on
    subscribe — verified against the demo venue. That snapshot is a delivered ``data`` payload,
    so plain payload-gating would reset the retry budget every reconnect cycle and the D-20
    ceiling could never trip on the candle arm. This drives the REAL
    ``_connect_and_consume_candles`` against a fake WS that reproduces the snapshot-then-close
    shape (the path the scripted-consume harness cannot reach).

    RED before the ``payload_seen`` fix: the snapshot resets the budget, ``attempt`` is pinned
    at 1 forever, the loop reconnects endlessly until the ``cap`` safety valve fires and NO halt
    is recorded. GREEN after: the snapshot no longer resets, so the ceiling trips -> HALT.
    """
    halt = _Recorder()
    okx_provider.set_halt_signal(halt)
    okx_provider._reconnect_ceiling = 3

    state: dict[str, int] = {}
    session = _SnapshotThenCloseSession(state)
    monkeypatch.setattr(
        "itrader.price_handler.providers.okx_provider.aiohttp.ClientSession", session)

    async def _consume(_stream_name: str) -> None:
        await okx_provider._connect_and_consume_candles("BTC-USDT", "candle1D", _stream_name)

    _drive_storm(okx_provider._run_stream_supervisor(_consume, "candles"))

    assert halt.calls == ["connector-fatal"]   # ceiling tripped despite snapshot-on-subscribe
    assert state["connects"] == 4              # attempts 1..3 retried, attempt 4 > ceiling -> halt


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


# --- WR-06: the ERROR route is terminal-safe (no error->error recursion) ------


class _RaisingSink:
    """An alert sink whose egress is down — .alert() always raises."""

    def __init__(self) -> None:
        self.calls = 0

    def alert(self, event: Any) -> None:
        self.calls += 1
        raise RuntimeError("alert egress down")


def test_error_route_consumer_failure_does_not_recurse(monkeypatch: Any) -> None:
    """WR-06: a failure WHILE consuming an ErrorEvent must be terminal — no recursion.

    If the ERROR-route consumer (``_log_error_event`` / its injected alert sink) raises,
    the live publish-and-continue seam MUST NOT publish a fresh ErrorEvent routed straight
    back to the same failing consumer. That is an unbounded error->error feedback loop that
    floods the engine-thread queue (and, when the failure repeats on the re-consumed event,
    livelocks a single ``process_events()`` drain forever).

    Drives a CRITICAL ErrorEvent through ``process_events()`` with the live
    ``_publish_and_continue`` policy bound (as ``start()`` binds it) and a raising alert sink.
    The sink fires exactly once (the original event); the failure is logged and swallowed; and
    crucially NO fresh ErrorEvent is enqueued by the failure path.
    """
    system = _live_system(monkeypatch)
    # Bind the live handler-failure policy exactly as start() does (line ~1071),
    # without launching the daemon thread.
    system.event_handler._on_handler_error = system._publish_and_continue  # type: ignore[method-assign]
    sink = _RaisingSink()
    system.event_handler._alert_sink = sink

    # The original CRITICAL ErrorEvent — enqueued BEFORE we start recording puts,
    # so only republished (recursion) events are captured.
    system.global_queue.put(ErrorEvent(
        time=datetime.now(UTC),
        source="test",
        error_type="Boom",
        error_message="original failure",
        severity=ErrorSeverity.CRITICAL,
    ))

    republished: list[Any] = []
    orig_put = system.global_queue.put

    def recording_put(item: Any, *args: Any, **kwargs: Any) -> None:
        republished.append(item)
        orig_put(item, *args, **kwargs)

    monkeypatch.setattr(system.global_queue, "put", recording_put)

    system.event_handler.process_events()   # must TERMINATE (no livelock)

    # The sink was invoked exactly once — for the original CRITICAL event.
    assert sink.calls == 1
    # No error->error recursion: the failing ErrorEvent must NOT spawn a fresh ErrorEvent.
    assert republished == []
    # Queue fully drained; nothing left circulating.
    assert system.global_queue.empty()


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


# --- WR-04: resume snapshots venue truth before clearing the pause ------------


def test_resume_snapshots_before_clearing_pause(monkeypatch: Any) -> None:
    """Resume takes a fresh REST snapshot BEFORE clearing the pause; a raise stays paused (WR-04).

    Proves the honest resume path: ``_maybe_resume_after_reconnect`` refreshes venue
    truth via ``VenueAccount.snapshot()`` and only then clears the pause — and a snapshot
    that RAISES leaves the pause in place and re-sets the resume flag (never resume blind).
    A blind mid-session ``VenueReconciler.reconcile()`` would spuriously HALT on legitimate
    positions from filled non-bracket orders, so resume deliberately snapshots only.
    """
    system = _live_system(monkeypatch)
    venue = MagicMock(name="venue_account")
    system._venue_account = venue

    # Happy path: pause, flag a resume, drain it — snapshot runs, pause clears.
    system.pause_submission("paused-on-disconnect")
    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    venue.snapshot.assert_called_once()
    assert system.get_status()["paused"] is False

    # Failure path: a snapshot that raises leaves the system paused and re-sets the flag.
    system.pause_submission("paused-on-disconnect")
    venue.snapshot.reset_mock()
    venue.snapshot.side_effect = RuntimeError("venue unreachable")
    system._pending_stream_resume.set()
    system._maybe_resume_after_reconnect()
    venue.snapshot.assert_called_once()
    assert system.get_status()["paused"] is True          # never resume blind
    assert system._pending_stream_resume.is_set()          # retried on next iteration


# --- WR-01: concurrent halt fires exactly one CRITICAL alert ------------------


def test_concurrent_halt_fires_single_alert(monkeypatch: Any) -> None:
    """N concurrent halt() callers fire exactly ONE CRITICAL alert; first reason wins (WR-01).

    The atomic single-lock check-and-set guarantees only the winning caller flips the
    status and emits. Reverting halt() to the old two-acquisition form (guard on
    ``self._status`` but flip in a separate ``_update_status`` lock) makes multiple
    callers pass the guard and this test FAIL (many CRITICAL ErrorEvents enqueued).
    """
    import threading

    system = _live_system(monkeypatch)

    n = 32
    reasons = [f"drift-{i}" for i in range(n)]
    barrier = threading.Barrier(n)

    def _halt(reason: str) -> None:
        barrier.wait()                                     # maximise the race window
        system.halt(reason)

    threads = [threading.Thread(target=_halt, args=(r,)) for r in reasons]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly ONE CRITICAL EngineHalted ErrorEvent was enqueued despite N callers.
    critical_halts = []
    while not system.global_queue.empty():
        ev = system.global_queue.get_nowait()
        if (
            getattr(ev, "type", None) == EventType.ERROR
            and getattr(ev, "severity", None) == ErrorSeverity.CRITICAL
            and getattr(ev, "error_type", None) == "EngineHalted"
        ):
            critical_halts.append(ev)

    assert len(critical_halts) == 1
    # First halt wins — the winning reason is one of the racers and matches halt_reason.
    assert system._halt_reason in reasons
    assert f"reason={system._halt_reason}" in critical_halts[0].error_message
    assert system.get_status()["status"] == SystemStatus.HALTED.value
