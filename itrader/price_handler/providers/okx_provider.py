"""OkxDataProvider — the data arm: native ``/business`` confirm-gated candle stream +
REST ``fetch_ohlcv`` backfill (CONN-01 / CONN-03 / CONN-05, D-01/D-03/D-04/D-05).

This is CONN-01, the phase's *confirm-flag escape hatch*. ccxt's unified ``watch_ohlcv``
drops the OKX ``confirm`` field (``parse_ohlcv`` returns only ``[ts,o,h,l,c,v]``, ccxt
#21885), so there is no way to tell a forming bar from a closed one through the unified
API. The only place the closed-bar flag survives is OKX's **native business candle
channel** (``wss://{host}:8443/ws/v5/business``), whose row layout is::

    [ ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm ]
       0   1  2  3  4   5      6         7          8      <- confirm at index 8

``confirm == "0"`` is a forming/in-progress push (repeated up to ~1/sec on the same
``ts``); ``confirm == "1"`` is the terminal closed bar. ``OkxDataProvider`` GATES on
``confirm == "1"`` and hands ONLY completed bars to the Phase-3 ``LiveBarFeed`` seam;
forming pushes are dropped (D-05, LX-08). A missed gate silently corrupts paper-parity —
the phase's single most likely correctness failure.

Sandbox routing (D-02 correction, CONN-03): the native socket host is driven off the
injected connector's ``sandbox`` bool — ``wspap.okx.com`` when ``sandbox`` is True,
``ws.okx.com`` otherwise. The ccxt ``x-simulated-trading`` header is REST-only and never
reaches any WebSocket; OKX WS demo is selected purely by the demo *host*. A native socket
hard-coded to the live host would stream from the LIVE venue while believing it is demo
(the phase's highest-severity threat), so the host keys off the same single bool as the
rest of the connector.

Decimal edge (CONN-05): OKX sends numeric *strings*, so every candle/backfill field
crosses the Decimal boundary via ``to_money(str(x))`` — never ``Decimal(float)`` and never
a bulk float cast of the frame. Business time: the bar-open ``ts`` (ms) is kept verbatim from the
venue, never the process wall-clock (Phase 3 owns ``BarEvent`` construction from it).

Dependency injection (D-04): the data arm types against the ``LiveConnector`` session
Protocol only (imported from the ccxt-free ``itrader.connectors.base`` module, not the
barrel — IN-01) — it NEVER imports the
concrete session class / its module (grep-guarded in verify). It reads
``connector.sandbox`` for the host, drives REST
backfill through the shared ``connector.client``, and launches the candle loop on the
connector's asyncio loop via ``connector.spawn`` (D-01/D-03 — data is a separate client /
lifecycle axis from the order arm).

Indentation: this file is 4-SPACE (matched to the ``providers/base.py`` seam and the
Phase-3 ``price_handler/feed/`` tree) — NOT the tabs of the quarantined ``ccxt_provider``.
Type discipline: this module is deliberately absent from ``pyproject.toml``
``[[tool.mypy.overrides]]`` — ``mypy --strict`` applies (it is the highest type-risk file
in the phase: raw aiohttp WS JSON row indexing with no analog).
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any, Awaitable, Callable, TypedDict

import aiohttp

from itrader.connectors.base import LiveConnector
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger


class ClosedBar(TypedDict):
    """A single completed OHLCV bar handed to the Phase-3 feed seam (Decimal edge held).

    ``ts`` is the venue bar-open timestamp in milliseconds (business time, kept verbatim —
    never wall-clock). The OHLCV fields are already across the Decimal boundary via
    ``to_money``; ``BarEvent`` construction from this dict is Phase-3's concern.
    """

    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    symbol: str        # D-12 (Phase-3 add) — routing key
    timeframe: str     # D-12 (Phase-3 add) — routing key


# OKX business-channel interval tokens (the channel name is ``"candle" + token``). OKX
# uppercases hour/day/week/month tokens (``1H``/``1D``/``1W``/``1M``) but lowercases
# minutes (``1m``). The month token ``1M`` collides with the minute intent of a naive
# ``.lower()``, so the map is looked up verbatim (no case-folding). Already-OKX tokens
# pass through their own key.
_OKX_INTERVALS: dict[str, str] = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "2d": "2D", "3d": "3D", "1w": "1W", "1M": "1M", "3M": "3M",
    "1H": "1H", "2H": "2H", "4H": "4H", "6H": "6H", "12H": "12H",
    "1D": "1D", "2D": "2D", "3D": "3D", "1W": "1W",
}

# The confirm flag lives at index 8; a well-formed business row therefore has >= 9 fields.
_CONFIRM_INDEX = 8
_MIN_ROW_FIELDS = 9

# Default REST backfill page size (OKX/ccxt cap); pagination advances by ``since``.
_BACKFILL_PAGE = 1000

# 05-08 (RES-01/D-19/D-20) reconnect-supervisor tuning — mirrors the OKX order arm
# (okx.py); named module constants documented [ASSUMED] and tunable from sandbox
# behaviour (research A3). The native candle socket has NO reconnect today (a code-
# verified gap): a drop kills the task silently. The supervisor reconnects a transient
# drop with exponential backoff after a debounce (a blip does not pause, D-19) and
# halts on the retry ceiling (D-20).
_STREAM_RECONNECT_DEBOUNCE_SECONDS = 0.25    # A3 [ASSUMED] sub-second blip -> no pause
_STREAM_RECONNECT_BACKOFF_BASE_SECONDS = 1.0  # A3 [ASSUMED] first backoff step
_STREAM_RECONNECT_BACKOFF_CAP_SECONDS = 30.0  # A3 [ASSUMED] exponential backoff ceiling
_STREAM_RECONNECT_RETRY_CEILING = 6           # A3 [ASSUMED] retries exhausted -> HALT (D-20)


class OkxDataProvider:
    """Independent OKX data arm: native confirm-gated candle stream + REST backfill.

    Constructed with the injected ``LiveConnector`` session (typed against the Protocol,
    D-04 — never the concrete session class) plus the ``symbol``/``timeframe`` it
    streams. It reads ``connector.sandbox`` for the native socket host, drives REST
    ``fetch_ohlcv`` backfill through ``connector.client``, and launches the candle loop on
    the connector loop via ``connector.spawn``. Completed bars are pushed to a sink the
    Phase-3 ``LiveBarFeed`` registers via :meth:`set_bar_sink` — the live streaming seam is
    NEW (the offline ``PriceProvider`` is never on the run path and is deliberately not
    subclassed here; Phase 3 co-shapes this seam).
    """

    def __init__(
        self, connector: LiveConnector, symbol: str, timeframe: str
    ) -> None:
        """Bind the injected session + the stream config; open no socket here.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol (D-04). The provider reads ``sandbox``
            for the native host, ``client`` for REST backfill, and ``spawn`` to launch the
            candle loop — it never imports the concrete session class.
        symbol : str
            The instrument to stream, e.g. ``"BTC/USDT"`` or ``"BTC-USDT"`` (normalised to
            the OKX ``instId`` form ``BTC-USDT``).
        timeframe : str
            The bar timeframe, e.g. ``"1d"`` — mapped to the OKX interval token (``1D``).
        """
        self.logger = get_itrader_logger().bind(component="OkxDataProvider")
        # D-04: the injected session Protocol, NOT the concretion.
        self._connector = connector
        self._symbol = symbol
        self._timeframe = timeframe
        # Phase-3 registers the closed-bar sink; until then closed bars are dropped-and-logged.
        self._bar_sink: Callable[[ClosedBar], None] | None = None
        self._stream_handle: Any = None

        # 05-08 (RES-01/D-19/D-20): reconnect-supervisor state (mirrors the OKX order
        # arm). The native candle loop runs under a bounded-retry supervisor — a
        # transient socket drop reconnects with exponential backoff instead of the task
        # dying silently, a sustained drop pauses new submission (D-19), and the retry
        # ceiling bounds the loop -> HALT on exhaustion (D-20).
        self._reconnect_attempts: dict[str, int] = {}
        self._streams_down: set[str] = set()
        self._reconnect_debounce_s = _STREAM_RECONNECT_DEBOUNCE_SECONDS
        self._reconnect_backoff_base_s = _STREAM_RECONNECT_BACKOFF_BASE_SECONDS
        self._reconnect_backoff_cap_s = _STREAM_RECONNECT_BACKOFF_CAP_SECONDS
        self._reconnect_ceiling = _STREAM_RECONNECT_RETRY_CEILING
        # Injected seams (composition root, 05-08 Task 2): the 05-04 halt entrypoint
        # (fatal / exhausted -> HALTED + CRITICAL alert) and the pause/resume-on-
        # disconnect callbacks (D-19). None until wired at the live root.
        self._halt_signal: Callable[[str], None] | None = None
        self._on_stream_down: Callable[[str], None] | None = None
        self._on_stream_up: Callable[[str], None] | None = None

    # --- symbol / interval helpers -------------------------------------------

    @staticmethod
    def _to_okx_symbol(symbol: str) -> str:
        """Normalise a symbol to the OKX ``instId`` form (``BTC-USDT``)."""
        upper = symbol.upper()
        if "-" in upper:
            return upper
        if "/" in upper:
            return upper.replace("/", "-")
        return upper

    def _okx_interval(self, timeframe: str) -> str:
        """Map a timeframe to its OKX interval token (``"1d"`` -> ``"1D"``)."""
        token = _OKX_INTERVALS.get(timeframe)
        if token is None:
            raise ValueError(f"Unsupported OKX timeframe: {timeframe!r}")
        return token

    # --- Phase-3 feed seam (D-03 — minimal, co-shaped by Phase 3) -------------

    def set_bar_sink(self, sink: Callable[[ClosedBar], None]) -> None:
        """Register the closed-bar sink the Phase-3 ``LiveBarFeed`` consumes.

        Kept intentionally minimal: the provider hands a raw ``ClosedBar`` dict; the feed
        owns ``BarEvent`` construction and the ring buffer (LX-07/LX-08).
        """
        self._bar_sink = sink

    def _hand_closed_bar(self, bar: ClosedBar) -> None:
        """Deliver one completed bar to the registered sink (drop-and-log if unset)."""
        if self._bar_sink is None:
            self.logger.warning(
                "Closed bar dropped — no bar sink registered (set_bar_sink not called)")
            return
        self._bar_sink(bar)

    # --- native business-channel candle stream (the one no-analog piece) ------

    def start_stream(self) -> Any:
        """Launch the native candle loop on the connector loop; return the task handle.

        Spawned via ``connector.spawn`` (D-01/D-03: a separate socket on the connector's
        asyncio loop, an independent axis from the order arm). The handle is cancelled by
        the connector on its ``disconnect``.
        """
        symbol_okx = self._to_okx_symbol(self._symbol)
        channel = "candle" + self._okx_interval(self._timeframe)
        self._stream_handle = self._connector.spawn(
            self._stream_candles(symbol_okx, channel))
        return self._stream_handle

    async def _stream_candles(self, symbol_okx: str, channel: str) -> None:
        """Consume the native candle socket under the reconnect supervisor (D-19/D-20).

        The consume body (one WS connect + subscribe + read loop) is wrapped in a
        bounded-retry supervisor: a transient drop (or a server-side socket close)
        reconnects with exponential backoff after a debounce (a blip does not pause,
        D-19); a fatal error or the exhausted retry ceiling halts the engine (D-20).
        Without it a single socket drop silently killed the candle task (a code-verified
        gap) and paper-parity would starve for bars.
        """
        async def _connect_and_consume(_stream_name: str) -> None:
            await self._connect_and_consume_candles(symbol_okx, channel)

        await self._run_stream_supervisor(_connect_and_consume, "candles")

    async def _connect_and_consume_candles(self, symbol_okx: str, channel: str) -> None:
        """One native business-candle connection: subscribe + read, gating on ``confirm``.

        Opens an aiohttp WS to ``wss://{host}:8443/ws/v5/business`` where the host is the
        connector's region+sandbox-derived ``ws_hostname`` (D-02 correction: host, NOT
        header; OKX-REGION: the (region, sandbox) pair selects wspap/ws/wseeapap/wseea).
        Subscribes the ``candle{tf}`` channel for ``instId`` and forwards only completed
        bars downstream. The ``async with`` guarantees the session closes on task
        cancellation (Pitfall 4 — an unclosed session raises ``ResourceWarning`` and fails
        the strict suite). Returns when the server closes the socket; the supervisor then
        reconnects (a stream is not supposed to end on its own).
        """
        host = self._connector.ws_hostname
        url = f"wss://{host}:8443/ws/v5/business"
        subscribe = {"op": "subscribe",
                     "args": [{"channel": channel, "instId": symbol_okx}]}
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, autoping=False) as ws:
                await ws.send_json(subscribe)
                self.logger.info(
                    "OKX candle stream subscribed",
                    host=host, channel=channel, instId=symbol_okx)
                # Subscribed successfully — if we were paused on a prior disconnect,
                # resume after the fresh reconcile (D-19). WR-03: a subscribe does NOT
                # reset the retry budget (see _reset_reconnect_budget).
                self._on_stream_healthy("candles")
                # WR-03 (data arm): OKX pushes an in-progress-candle SNAPSHOT (confirm='0')
                # within ~30ms of EVERY subscribe — verified against the demo venue. That
                # snapshot is delivered ON subscribe, so it is NOT proof of a connection that
                # stays up: a subscribe-then-close storm delivers exactly that one payload each
                # cycle. Reset the retry budget only on a payload delivered AFTER the subscribe
                # snapshot (evidence of real streaming); otherwise the D-20 never-spin-forever
                # ceiling could never trip on the candle arm (plain payload-gating is defeated
                # by the snapshot — the order arm has no such subscribe-time push).
                payload_seen = False
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        continue
                    payload: Any = json.loads(msg.data)
                    rows: Any = payload.get("data", []) if isinstance(payload, dict) else []
                    if rows:
                        if payload_seen:
                            self._reset_reconnect_budget("candles")
                        payload_seen = True
                    for row in rows:
                        self._process_row(row)

    # --- reconnect supervisor (RES-01/D-19/D-20) -----------------------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the 05-04 freeze-in-place halt entrypoint (D-20).

        Called with reason ``'connector-fatal'`` on a fatal connector error or an
        exhausted retry ceiling. The halt entrypoint owns the CRITICAL alert; the
        provider passes NO exception text so no secret leaks (Pitfall 16, T-05-27).
        """
        self._halt_signal = halt_signal

    def set_stream_state_listener(
        self,
        on_down: Callable[[str], None],
        on_up: Callable[[str], None],
    ) -> None:
        """Inject the pause/resume-on-disconnect callbacks (D-19).

        ``on_down`` fires when the candle stream stays disconnected past the debounce
        window (pause NEW order submission); ``on_up`` fires on reconnect (the callback
        owns the resume-only-after-fresh-REST-reconcile discipline). Both fire from the
        connector loop thread and must not do blocking venue I/O (Pitfall 9).
        """
        self._on_stream_down = on_down
        self._on_stream_up = on_up

    async def _run_stream_supervisor(
        self, connect_and_consume: Callable[[str], Awaitable[None]], stream_name: str
    ) -> None:
        """Bounded-retry reconnect supervisor around one connection attempt (D-19/D-20).

        Runs ``connect_and_consume`` (one WS connect + read loop). A transient drop
        (``ccxt.NetworkError``/``RequestTimeout``/``DDoSProtection`` or an aiohttp
        connection error), or a clean return (server closed the socket), reconnects with
        exponential backoff after a debounce — staying running (publish-and-continue). A
        fatal error (``ccxt.AuthenticationError``/``PermissionDenied``) or the exhausted
        retry ceiling escalates to the injected halt entrypoint (HALTED + CRITICAL alert,
        reason ``'connector-fatal'``). ``asyncio.CancelledError`` is re-raised so the
        connector's disconnect cancels the task cleanly (Pitfall 4).
        """
        import ccxt  # lazy: ccxt already transitively imported on the live path only
        transient: tuple[type[BaseException], ...] = (
            ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection,
            aiohttp.ClientError, ConnectionError, asyncio.TimeoutError)
        fatal: tuple[type[BaseException], ...] = (
            ccxt.AuthenticationError, ccxt.PermissionDenied)
        while True:
            try:
                await connect_and_consume(stream_name)
                # A stream coroutine returning cleanly means the venue closed the
                # socket — not a terminal stop. Reconnect like a transient drop.
                drop_label = "socket closed by server"
            except asyncio.CancelledError:
                raise  # cooperative teardown — never swallow.
            except fatal as exc:
                self._escalate_connector_halt(
                    stream_name, exc, "fatal auth/permission error")
                return
            except transient as exc:
                drop_label = type(exc).__name__
            # Transient drop OR clean socket-close -> bounded-retry reconnect.
            attempt = self._reconnect_attempts.get(stream_name, 0) + 1
            self._reconnect_attempts[stream_name] = attempt
            if attempt > self._reconnect_ceiling:
                self._escalate_connector_halt(
                    stream_name, RuntimeError(drop_label),
                    "reconnect retry ceiling exhausted")
                return
            await asyncio.sleep(self._reconnect_debounce_s)
            if attempt > 1:
                # Still failing past the debounce window -> pause (D-19).
                self._mark_stream_down(stream_name)
            backoff = min(
                self._reconnect_backoff_base_s * (2 ** (attempt - 1)),
                self._reconnect_backoff_cap_s)
            # Scrub (T-05-27): log the drop LABEL (exception type / fixed string),
            # never str(exc) — a connector error may carry request context / a secret.
            self.logger.warning(
                "OKX %s stream dropped (%s) — reconnecting "
                "(attempt %d/%d, backoff %.1fs)",
                stream_name, drop_label, attempt, self._reconnect_ceiling, backoff)
            await asyncio.sleep(backoff)

    def _escalate_connector_halt(
        self, stream_name: str, exc: BaseException, cause: str
    ) -> None:
        """Halt the engine on an unrecoverable connector failure (D-20).

        Scrub (T-05-27): the log carries the exception TYPE + a fixed cause string, never
        ``str(exc)``; the halt entrypoint is called with the fixed reason
        ``'connector-fatal'`` so no secret can reach the CRITICAL alert.
        """
        self.logger.error(
            "OKX %s stream unrecoverable (%s: %s) — halting engine",
            stream_name, type(exc).__name__, cause)
        if self._halt_signal is not None:
            self._halt_signal("connector-fatal")

    def _mark_stream_down(self, stream_name: str) -> None:
        """Record a sustained disconnect and pause new submission once (D-19)."""
        if stream_name in self._streams_down:
            return
        self._streams_down.add(stream_name)
        self.logger.warning(
            "OKX %s stream disconnected — pausing new order submission", stream_name)
        if self._on_stream_down is not None:
            self._on_stream_down(stream_name)

    def _on_stream_healthy(self, stream_name: str) -> None:
        """A successful subscribe: resume if we were paused (D-19). Does NOT reset backoff.

        WR-03: a subscribe is NOT proof of health — it does NOT reset the reconnect retry
        budget. Only a delivered payload does (see ``_reset_reconnect_budget``). Resetting
        on a mere subscribe let a subscribe-then-close storm pin ``attempt`` at 1 forever
        and silently defeat the D-20 never-spin-forever HALT guarantee.
        """
        if stream_name in self._streams_down:
            self._streams_down.discard(stream_name)
            self.logger.info(
                "OKX %s stream reconnected — resuming after REST reconcile", stream_name)
            if self._on_stream_up is not None:
                self._on_stream_up(stream_name)

    def _reset_reconnect_budget(self, stream_name: str) -> None:
        """WR-03: a POST-SNAPSHOT payload proves the connection — reset the retry budget.

        Neither a subscribe (``_on_stream_healthy``) nor the OKX in-progress-candle SNAPSHOT
        that arrives on every subscribe resets ``_reconnect_attempts``; only a candle row
        delivered AFTER that snapshot does (see the ``payload_seen`` gate in
        ``_connect_and_consume_candles``). This keeps the D-20 ceiling able to trip under a
        subscribe-then-close storm — where OKX still pushes the snapshot each cycle — while a
        genuine, streaming reconnect still clears the accumulated attempts.
        """
        self._reconnect_attempts[stream_name] = 0

    def _process_row(self, row: Any) -> None:
        """Validate one raw business row, gate on ``confirm``, cross the Decimal edge.

        Input validation (V5, T-02-04-MALFORMED): a row must be a sequence of >= 9 fields
        before ``confirm`` (index 8) can be read — malformed rows are skipped-and-logged,
        never indexed blindly. The confirm gate (T-02-04-CONFIRM) drops every forming push
        (``confirm != "1"``). Every numeric field crosses via ``to_money(str(...))``
        (T-02-04-FLOAT — OKX sends numeric strings; no float ever forms).
        """
        if not isinstance(row, (list, tuple)) or len(row) < _MIN_ROW_FIELDS:
            self.logger.warning(
                "Malformed OKX candle row (need >= 9 fields) — skipping")
            return
        if row[_CONFIRM_INDEX] != "1":
            # Forming bar (confirm == "0") — dropped; only completed bars flow downstream.
            return
        # Field-validity guard (WR-04): a correct-length row can still carry a
        # non-numeric/empty cell (a malformed or partial venue frame). Crossing the
        # Decimal edge on such a field raises ValueError out of _process_row, which
        # would propagate through _stream_candles' for-loop and KILL the candle task
        # with no reconnect. Wrap the extraction so a bad row is skipped-and-logged
        # (matching the length-guard contract) and the async for loop stays alive.
        try:
            closed: ClosedBar = {
                "ts": int(row[0]),
                "open": to_money(str(row[1])),
                "high": to_money(str(row[2])),
                "low": to_money(str(row[3])),
                "close": to_money(str(row[4])),
                "volume": to_money(str(row[5])),
                # D-12: routing keys stamped from the provider's own trusted config
                # (self._symbol/self._timeframe), NOT read from the untrusted venue row
                # (T-03-01-TAMPER) — a spoofed row cannot forge the (symbol, timeframe) ring key.
                "symbol": self._symbol,
                "timeframe": self._timeframe,
            }
        except (ValueError, TypeError, IndexError):
            self.logger.warning(
                "Unparseable OKX candle row (bad numeric field) — skipping")
            return
        self._hand_closed_bar(closed)

    # --- REST backfill (Phase-3 warmup path, Decimal edge) --------------------

    def fetch_ohlcv_backfill(
        self, symbol: str, timeframe: str,
        since: int | None = None, limit: int = _BACKFILL_PAGE,
    ) -> list[ClosedBar]:
        """Backfill completed OHLCV bars via REST ``fetch_ohlcv`` through the shared client.

        Paginates in ``limit``-row windows (advancing ``since`` past the last bar to avoid
        the duplicated boundary bar) through ``connector.call(client.fetch_ohlcv(...))``,
        and crosses every numeric cell via ``to_money(str(...))`` — NEVER a bulk float
        cast of the frame / ``Decimal(float)`` (CONN-05). Returns Decimal-edge
        ``ClosedBar`` dicts for the Phase-3 warmup path (replayed one-by-one through the
        feed's ``update(bar)``, LX-09).
        """
        symbol_okx = self._to_okx_symbol(symbol)
        # ccxt's unified ``fetch_ohlcv`` takes the UNIFIED timeframe (``"1d"``) and maps it
        # to OKX's ``"1D"`` itself — passing the OKX token here makes ccxt's
        # ``parse_timeframe`` reject unit ``"D"``. The ``_okx_interval`` token is for the
        # native business-candle CHANNEL name only (``start_stream``), never for ccxt.
        client = self._connector.client

        raw: list[Any] = []
        page: list[Any] = list(
            self._connector.call(client.fetch_ohlcv(symbol_okx, timeframe, since, limit)))
        raw.extend(page)
        # IN-02: ``len(page) == limit`` (limit > 0) already implies ``page`` is
        # truthy, so the ``and page`` clause was dead.
        while len(page) == limit:
            last_ts = int(page[-1][0])
            page = list(self._connector.call(
                client.fetch_ohlcv(symbol_okx, timeframe, last_ts + 1, limit)))
            raw.extend(page)

        bars: list[ClosedBar] = []
        for row in raw:
            bars.append({
                "ts": int(row[0]),
                "open": to_money(str(row[1])),
                "high": to_money(str(row[2])),
                "low": to_money(str(row[3])),
                "close": to_money(str(row[4])),
                "volume": to_money(str(row[5])),
                # D-12: stamp the routing keys from the method's own params (NOT
                # self._symbol) so an ad-hoc backfill for any symbol/timeframe routes
                # to the correct ring key.
                "symbol": symbol,
                "timeframe": timeframe,
            })
        return bars

    # --- lifecycle ------------------------------------------------------------

    def stop(self) -> None:
        """Mark the stream stopped. Task cancellation + session close are owned by the
        connector's ``disconnect`` (which cancels the spawned handle; the candle loop's
        ``async with`` then closes the aiohttp session — Pitfall 4)."""
        self._stream_handle = None
