"""OkxDataProvider — the OKX data arm: native ``/business`` confirm-gated candle stream
plus REST ``fetch_ohlcv`` backfill.

ccxt's unified ``watch_ohlcv`` drops the OKX ``confirm`` field (``parse_ohlcv`` returns
only ``[ts,o,h,l,c,v]``, ccxt #21885), so through the unified API a forming bar is
indistinguishable from a closed one. The flag survives only on OKX's native business
candle channel (``wss://{host}:8443/ws/v5/business``), whose row layout is::

    [ ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm ]
       0   1  2  3  4   5      6         7          8      <- confirm at index 8

``confirm == "0"`` is a forming push (repeated up to ~1/sec on the same ``ts``);
``confirm == "1"`` is the terminal closed bar. Only ``confirm == "1"`` rows reach the
``LiveBarFeed`` sink — a missed gate silently corrupts paper-parity.

The native socket host comes from ``connector.ws_hostname``, so it keys off the same
(region, sandbox) pair as the rest of the connector. ccxt's ``x-simulated-trading``
header is REST-only and never reaches a WebSocket — OKX WS demo is selected purely by the
demo *host*, so a socket hard-coded to the live host would stream the LIVE venue while
believing it is demo.
"""

from __future__ import annotations

import asyncio
import json
import queue
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable, TypedDict

import aiohttp

from itrader.connectors.base import LiveConnector
from itrader.core.exceptions import MissingPriceDataError, StateError
from itrader.core.money import to_money
from itrader.events_handler.events import BarsLoaded, BarsLoadFailed
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.core.bar import Bar


class ClosedBar(TypedDict):
    """A single completed OHLCV bar handed to the feed seam.

    ``ts`` is the venue bar-open timestamp in milliseconds — business time kept verbatim,
    never wall-clock. ``BarEvent`` construction from this dict is the feed's concern.
    """

    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    symbol: str        # routing key
    timeframe: str     # routing key


# OKX business-channel interval tokens (the channel name is ``"candle" + token``). The
# month token ``1M`` collides with the minute intent of a naive ``.lower()``, so the map
# is looked up verbatim — no case-folding. Already-OKX tokens pass through their own key.
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


class OkxDataProvider:
    """Independent OKX data arm: native confirm-gated candle stream + REST backfill.

    Constructed with the injected ``LiveConnector`` session plus the ``symbol`` /
    ``timeframe`` it streams. It reads ``connector.ws_hostname`` for the native socket
    host, drives REST ``fetch_ohlcv`` backfill through ``connector.client``, and launches
    the candle loop via ``connector.spawn``. Completed bars go to the sink ``LiveBarFeed``
    registers through :meth:`set_bar_sink`. Satisfies the ``LiveDataProvider`` Protocol
    structurally; the offline ``PriceProvider`` ABC is deliberately not subclassed.
    """

    def __init__(
        self, connector: LiveConnector, symbol: str, timeframe: str
    ) -> None:
        """Bind the injected session + the stream config; open no socket here.

        Parameters
        ----------
        connector : LiveConnector
            The injected session/transport Protocol. The provider reads ``ws_hostname``
            for the native host, ``client`` for REST backfill, and ``spawn`` to launch
            the candle loop — it never imports the concrete session class.
        symbol : str
            The instrument to stream, e.g. ``"BTC/USDT"`` or ``"BTC-USDT"`` (normalised
            to the OKX ``instId`` form ``BTC-USDT``).
        timeframe : str
            The bar timeframe, e.g. ``"1d"`` — mapped to the OKX interval token (``1D``).
        """
        self.logger = get_itrader_logger().bind(component="OkxDataProvider")
        self._connector = connector
        self._symbol = symbol
        self._timeframe = timeframe
        self._bar_sink: Callable[[ClosedBar], None] | None = None
        self._stream_handle: Any = None

        # The engine-thread queue the async warmup fetch hands its ONE BarsLoaded /
        # BarsLoadFailed back on (the MPSC-safe hop from the connector loop to the
        # single-writer engine thread). Injected via set_global_queue; None until then.
        self._global_queue: "queue.Queue[Any] | None" = None

        # Dynamic per-symbol subscription registry, keyed by the universe-member symbol
        # (the SAME form stamped into ``ClosedBar["symbol"]``). An ADDITIONAL index over
        # the connector's ``_stream_tasks`` set (which owns task lifecycle + disconnect
        # teardown), NOT a second lifecycle owner — membership is never decided here.
        self._streams: dict[str, asyncio.Task[Any]] = {}

        # Injected at the live composition root: the halt entrypoint (fatal / exhausted
        # -> HALTED + CRITICAL alert) and the pause/resume-on-disconnect callbacks. The
        # supervisor's closures late-bind them, so a setter after construction still works.
        self._halt_signal: Callable[[str], None] | None = None
        self._on_stream_down: Callable[[str], None] | None = None
        self._on_stream_up: Callable[[str], None] | None = None

        # The one shared reconnect ladder, configured here with the WIDE transient set
        # and reconnect_on_clean_return=True (a server socket-close is a normal
        # reconnect). ccxt + the supervisor are lazy-imported HERE, never at module top,
        # so the backtest import graph stays ccxt-free — they load only when a provider
        # is actually constructed.
        import ccxt

        from itrader import config
        from itrader.connectors.stream_supervisor import StreamSupervisor
        self._supervisor = StreamSupervisor(
            config.stream,
            transient_exceptions=(
                ccxt.NetworkError, ccxt.RequestTimeout, ccxt.DDoSProtection,
                aiohttp.ClientError, ConnectionError, asyncio.TimeoutError),
            fatal_exceptions=(ccxt.AuthenticationError, ccxt.PermissionDenied),
            reconnect_on_clean_return=True,
            halt_signal=lambda r: (
                self._halt_signal(r) if self._halt_signal is not None else None),
            on_down=lambda n: (
                self._on_stream_down(n) if self._on_stream_down is not None else None),
            on_up=lambda n: (
                self._on_stream_up(n) if self._on_stream_up is not None else None),
            logger=self.logger,
            label="OKX")

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

    # --- feed seam -----------------------------------------------------------

    def set_bar_sink(self, sink: Callable[[ClosedBar], None]) -> None:
        """Register the closed-bar sink ``LiveBarFeed`` consumes.

        The provider hands a raw ``ClosedBar`` dict; the feed owns ``BarEvent``
        construction and the ring buffer.
        """
        self._bar_sink = sink

    def set_global_queue(self, global_queue: "queue.Queue[Any]") -> None:
        """Inject the engine queue the async warmup emits BarsLoaded/BarsLoadFailed on.

        :meth:`spawn_warmup` is the ONE path that puts an event on the queue directly; the
        provider is otherwise a pure fetch-and-hand-to-sink arm. A post-construction seam
        (like :meth:`set_bar_sink`) so the live wiring order stays flexible.
        """
        self._global_queue = global_queue

    def _hand_closed_bar(self, bar: ClosedBar) -> None:
        """Deliver one completed bar to the registered sink (drop-and-log if unset)."""
        if self._bar_sink is None:
            self.logger.warning(
                "Closed bar dropped — no bar sink registered (set_bar_sink not called)")
            return
        self._bar_sink(bar)

    # --- native business-channel candle stream --------------------------------

    def start_stream(self) -> Any:
        """Launch the native candle loop on the connector loop; return the task handle.

        A separate socket on the connector's asyncio loop, an independent axis from the
        order arm. The handle is cancelled by the connector on its ``disconnect``.
        """
        symbol_okx = self._to_okx_symbol(self._symbol)
        channel = "candle" + self._okx_interval(self._timeframe)
        self._stream_handle = self._connector.spawn(
            self._stream_candles(symbol_okx, channel, self._symbol))
        return self._stream_handle

    def subscribe(self, symbol: str) -> None:
        """Dynamically subscribe one universe-member symbol's candle stream.

        Idempotent: a second call for an already-subscribed ``symbol`` is a no-op. Spawns
        ONE supervised ``candle{tf}`` coroutine via ``connector.spawn`` and records the
        task in the ``{symbol: task}`` registry. Engine-thread-safe: ``spawn`` marshals
        onto the connector loop via ``call_soon_threadsafe``, so a ``UniverseUpdateEvent``
        consumer on the engine thread can call it directly. The registry is a mechanical
        index — the provider carries NO membership knowledge.

        Ordering CONTRACT — warmup BEFORE subscribe: the caller MUST run
        ``feed.warmup(symbol, tf)`` BEFORE ``subscribe(symbol)`` (mirroring the
        wiring-time ``feed.warmup(...)`` → ``start_stream()`` order) so the feed's
        monotonic stamp is set from REST history and the first live closed bar lands on
        the in-sequence branch. The ``confirm='0'`` snapshot OKX pushes on every subscribe
        is already dropped by ``_process_row``.
        """
        if symbol in self._streams:
            return
        symbol_okx = self._to_okx_symbol(symbol)
        channel = "candle" + self._okx_interval(self._timeframe)
        self._streams[symbol] = self._connector.spawn(
            self._stream_candles(symbol_okx, channel, symbol))

    def unsubscribe(self, symbol: str) -> None:
        """Dynamically unsubscribe a symbol's candle stream — safe no-op if absent.

        Pops the registry entry and cancels the task exactly once, reusing the connector's
        cooperative-cancel teardown: the ``async with aiohttp.ClientSession()`` closes the
        socket on ``CancelledError``, ``StreamSupervisor.run`` re-raises it untouched, and
        the connector's ``_on_task_done`` untracks the task quietly.

        Thread affinity: this runs on the ENGINE thread, but ``task.cancel()`` and the
        supervisor-dict cleanup touch state owned by the CONNECTOR-LOOP thread. So —
        chosen over adding a ``threading.Lock`` — the ``_streams`` pop stays here
        (``subscribe`` writes it on the engine thread too, so it is single-writer there)
        while BOTH the cancel AND the supervisor cleanup are marshaled onto the connector
        loop, leaving that loop the single writer for the supervisor dicts. Cleanup is
        therefore ASYNC — it lands on the next connector-loop tick.

        The early return is not an optimisation: a symbol with no task AND no supervisor
        state must not reach ``spawn``, whose "connect() must run before spawn()"
        assertion fires when ``unsubscribe`` is called before the connector loop runs.
        ``spawn`` can still raise past that guard (e.g. ``TimeoutError``), so the coroutine
        is closed on any failure — an un-awaited coroutine raises a ``RuntimeWarning``
        that is test-fatal under ``filterwarnings=["error"]`` and would mask the real
        scheduling failure.
        """
        task = self._streams.pop(symbol, None)
        if (task is None
                and symbol not in self._supervisor._streams_down
                and symbol not in self._supervisor._reconnect_attempts):
            return

        async def _cleanup() -> None:
            if task is not None:
                task.cancel()
            # Else a stale down-flag pins is_streaming_healthy() False forever (wedging
            # StreamRecoveryHandler's _all_venue_streams_healthy resume gate) and a stale
            # attempt count trips the retry ceiling on a later re-subscribe.
            self._supervisor.forget(symbol)

        coro = _cleanup()
        try:
            self._connector.spawn(coro)
        except BaseException:
            coro.close()
            raise

    async def _stream_candles(
        self, symbol_okx: str, channel: str, symbol: str
    ) -> None:
        """Consume the native candle socket under the reconnect supervisor.

        The consume body (one WS connect + subscribe + read loop) is wrapped in a
        bounded-retry supervisor: a transient drop reconnects with exponential backoff
        after a debounce, so a blip does not pause; a fatal error or an exhausted retry
        ceiling halts the engine. Unsupervised, one socket drop kills the candle task and
        paper-parity starves for bars.

        The member ``symbol`` is threaded through as the supervisor ``stream_name``: with
        N dynamic channels the reconnect budget / down-state MUST key on the member
        symbol, never a shared literal — otherwise one symbol's drop marks all streams
        down and one symbol's payload resets all budgets, defeating the HALT ceiling.
        """
        async def _connect_and_consume(stream_name: str) -> None:
            await self._connect_and_consume_candles(symbol_okx, channel, stream_name)

        await self._supervisor.run(_connect_and_consume, symbol)

    async def _connect_and_consume_candles(
        self, symbol_okx: str, channel: str, stream_name: str
    ) -> None:
        """One native business-candle connection: subscribe + read, gating on ``confirm``.

        Opens an aiohttp WS to ``wss://{host}:8443/ws/v5/business``, where the connector's
        ``ws_hostname`` resolves the (region, sandbox) pair to wspap/ws/wseeapap/wseea.
        The ``async with`` guarantees the session closes on task cancellation — an
        unclosed session raises ``ResourceWarning`` and fails the strict suite. Returns
        when the server closes the socket; the supervisor then reconnects, since a stream
        is not supposed to end on its own.
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
                # Resume ONLY this symbol's stream if a prior disconnect paused it. A
                # subscribe does NOT reset the retry budget — mark_up never touches it.
                self._supervisor.mark_up(stream_name)
                # OKX pushes an in-progress-candle SNAPSHOT (confirm='0') within ~30ms of
                # EVERY subscribe, so a payload is NOT proof of a connection that stays
                # up — a subscribe-then-close storm delivers that one payload per cycle.
                # Reset the budget only on a payload AFTER the subscribe snapshot; plain
                # payload-gating would keep the retry ceiling from ever tripping here.
                payload_seen = False
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        continue
                    # A non-JSON frame is a tampering signal — log the exception TYPE
                    # only (never msg.data, which may embed venue/request context) and
                    # re-raise so the supervisor's catch-all escalates it to a HALT,
                    # rather than let a garbage frame silently kill the candle task.
                    try:
                        payload: Any = json.loads(msg.data)
                    except (ValueError, TypeError) as exc:
                        self.logger.warning(
                            "OKX candle frame parse failed (%s) — escalating to halt",
                            type(exc).__name__)
                        raise
                    rows: Any = payload.get("data", []) if isinstance(payload, dict) else []
                    if rows:
                        if payload_seen:
                            self._supervisor.reset_budget(stream_name)
                        payload_seen = True
                    for row in rows:
                        self._process_row(row)

    # --- reconnect supervisor ------------------------------------------------

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """Inject the freeze-in-place halt entrypoint.

        Called with reason ``'connector-fatal'`` on a fatal connector error or an
        exhausted retry ceiling. The halt entrypoint owns the CRITICAL alert; the
        provider passes NO exception text so no secret leaks.
        """
        self._halt_signal = halt_signal

    def set_stream_state_listener(
        self,
        on_down: Callable[[str], None],
        on_up: Callable[[str], None],
    ) -> None:
        """Inject the pause/resume-on-disconnect callbacks.

        ``on_down`` fires when the candle stream stays disconnected past the debounce
        window (pause NEW order submission); ``on_up`` fires on reconnect (the callback
        owns the resume-only-after-fresh-REST-reconcile discipline). Both fire from the
        connector loop thread and must not do blocking venue I/O.
        """
        self._on_stream_down = on_down
        self._on_stream_up = on_up

    def is_streaming_healthy(self) -> bool:
        """True iff this arm's candle stream is up.

        Delegates to the shared ``StreamSupervisor``, which owns the down-set. Read by
        ``StreamRecoveryHandler._all_venue_streams_healthy`` on the ENGINE thread while
        the connector loop mutates that set — a GIL-atomic emptiness read, no lock; any
        staleness self-heals via the re-fired resume Event.
        """
        return self._supervisor.is_healthy()

    def _process_row(self, row: Any) -> None:
        """Validate one raw business row, gate on ``confirm``, cross the Decimal edge.

        A row must be a sequence of >= 9 fields before ``confirm`` (index 8) can be read
        — malformed rows are skipped-and-logged, never indexed blindly. OKX sends numeric
        strings, so every field crosses via ``to_money(str(...))`` and no float ever forms.
        """
        if not isinstance(row, (list, tuple)) or len(row) < _MIN_ROW_FIELDS:
            self.logger.warning(
                "Malformed OKX candle row (need >= 9 fields) — skipping")
            return
        if row[_CONFIRM_INDEX] != "1":
            return
        # A correct-length row can still carry a non-numeric/empty cell. Crossing the
        # Decimal edge on one would raise through the caller's ``async for`` loop and KILL
        # the candle task with no reconnect — so a bad row is skipped-and-logged instead.
        try:
            closed: ClosedBar = {
                "ts": int(row[0]),
                "open": to_money(str(row[1])),
                "high": to_money(str(row[2])),
                "low": to_money(str(row[3])),
                "close": to_money(str(row[4])),
                "volume": to_money(str(row[5])),
                # Routing keys stamped from the provider's own trusted config, NOT read
                # from the untrusted venue row — a spoofed row cannot forge the ring key.
                "symbol": self._symbol,
                "timeframe": self._timeframe,
            }
        except (ValueError, TypeError, IndexError):
            self.logger.warning(
                "Unparseable OKX candle row (bad numeric field) — skipping")
            return
        self._hand_closed_bar(closed)

    # --- REST backfill -------------------------------------------------------

    def fetch_ohlcv_backfill(
        self, symbol: str, timeframe: str,
        since: int | None = None, limit: int | None = None,
    ) -> list[ClosedBar]:
        """Backfill completed OHLCV bars via REST ``fetch_ohlcv`` through the shared client.

        Paginates in ``limit``-row windows through ``connector.call(...)``, advancing
        ``since`` past the last bar so the boundary bar is not duplicated. ``limit``
        defaults to ``config.feed_provider.backfill_page``.

        Returns
        -------
        list[ClosedBar]
            Decimal-edge bars for the warmup path, replayed one-by-one through the feed's
            ``update(bar)``. Empty when the venue has no history in the window.
        """
        if limit is None:
            from itrader import config
            limit = config.feed_provider.backfill_page
        symbol_okx = self._to_okx_symbol(symbol)
        # ccxt's unified ``fetch_ohlcv`` takes the UNIFIED timeframe (``"1d"``) and maps
        # it to ``"1D"`` itself; passing the OKX token makes ``parse_timeframe`` reject
        # unit ``"D"``. The ``_okx_interval`` token is for the native CHANNEL name only.
        client = self._connector.client

        raw: list[Any] = []
        page: list[Any] = list(
            self._connector.call(client.fetch_ohlcv(symbol_okx, timeframe, since, limit)))
        raw.extend(page)
        while len(page) == limit:
            last_ts = int(page[-1][0])
            page = list(self._connector.call(
                client.fetch_ohlcv(symbol_okx, timeframe, last_ts + 1, limit)))
            raw.extend(page)

        return self._rows_to_closed_bars(raw, symbol, timeframe)

    async def _fetch_ohlcv_backfill_async(
        self, symbol: str, timeframe: str,
        since: int | None = None, limit: int | None = None,
    ) -> list[ClosedBar]:
        """Loop-native REST backfill: ``await`` ``client.fetch_ohlcv`` DIRECTLY on the loop.

        The twin of the synchronous :meth:`fetch_ohlcv_backfill`, differing in ONE thing:
        it ``await``s the ccxt client coroutine on the connector loop instead of bridging
        through ``connector.call(...).result()``. That bridge blocks the loop thread on a
        future the same loop must resolve, self-deadlocking into a 30s stall. This is the
        LOOP-triggered gap path only; the engine-thread ``warmup`` path keeps ``call()``.
        """
        if limit is None:
            from itrader import config
            limit = config.feed_provider.backfill_page
        symbol_okx = self._to_okx_symbol(symbol)
        client = self._connector.client
        raw: list[Any] = []
        page: list[Any] = list(
            await client.fetch_ohlcv(symbol_okx, timeframe, since, limit))
        raw.extend(page)
        while len(page) == limit:
            last_ts = int(page[-1][0])
            page = list(
                await client.fetch_ohlcv(symbol_okx, timeframe, last_ts + 1, limit))
            raw.extend(page)
        return self._rows_to_closed_bars(raw, symbol, timeframe)

    def _rows_to_closed_bars(
        self, raw: list[Any], symbol: str, timeframe: str
    ) -> list[ClosedBar]:
        """Cross the Decimal edge for a batch of raw ccxt OHLCV rows (shared sync/async).

        Every numeric cell crosses via ``to_money(str(...))`` — never a bulk float cast.
        Routing keys come from the caller's ``symbol`` / ``timeframe`` params, NOT
        ``self._symbol``, so an ad-hoc backfill for any pair routes to the right ring key.
        """
        bars: list[ClosedBar] = []
        for row in raw:
            bars.append({
                "ts": int(row[0]),
                "open": to_money(str(row[1])),
                "high": to_money(str(row[2])),
                "low": to_money(str(row[3])),
                "close": to_money(str(row[4])),
                "volume": to_money(str(row[5])),
                "symbol": symbol,
                "timeframe": timeframe,
            })
        return bars

    def spawn_gap_backfill(
        self, symbol: str, timeframe: str, since: int, limit: int,
        on_bars: Callable[[list[ClosedBar]], None],
    ) -> None:
        """Schedule a loop-native, supervised gap backfill on the connector loop.

        MUST be reached from loop-thread code — the ``LiveBarFeed`` gap branch runs
        synchronously INSIDE the running candle coroutine, so ``get_running_loop()``
        returns the connector loop here. Scheduling uses that loop's ``create_task``:
        NEVER ``connector.spawn`` (whose cross-thread ``ready.wait`` self-deadlocks when
        driven from the loop thread) and NEVER ``connector.call(...).result()``. The task
        is supervised so an unexpected failure escalates to the halt entrypoint.
        """
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            self._run_gap_backfill(symbol, timeframe, since, limit, on_bars))
        task.add_done_callback(self._on_gap_backfill_done)

    async def _run_gap_backfill(
        self, symbol: str, timeframe: str, since: int, limit: int,
        on_bars: Callable[[list[ClosedBar]], None],
    ) -> None:
        """Await the loop-native interior backfill, then hand the bars to the feed's replay."""
        bars = await self._fetch_ohlcv_backfill_async(
            symbol, timeframe, since=since, limit=limit)
        on_bars(bars)

    def _on_gap_backfill_done(self, task: "asyncio.Task[Any]") -> None:
        """Supervise the spawned gap-backfill task — an unknown failure halts the engine.

        A cooperative ``CancelledError`` (connector disconnect) or a clean finish is quiet;
        anything else is logged (exception TYPE only, never ``str(exc)``) and escalated to
        the halt entrypoint. ``task.exception()`` is read only past the cancelled guard so
        it never re-raises the ``CancelledError``.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        self.logger.error(
            "OKX gap backfill task died (%s) — halting engine", type(exc).__name__)
        if self._halt_signal is not None:
            self._halt_signal("connector-fatal")

    # --- async warmup ---------------------------------------------------------

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        """Schedule a loop-native REST warmup fetch; emit ONE BarsLoaded/BarsLoadFailed.

        Runs ONLY the REST fetch (pure I/O, no engine/feed state) on the connector loop and
        hands ALL fetched bars back to the engine thread as ONE ``BarsLoaded``
        bulk-transport event — never a per-bar flood. On ANY fetch failure it emits ONE
        ``BarsLoadFailed`` whose reason is the exception TYPE name only, never ``str(exc)``.

        Cross-thread: triggered from the ENGINE thread, so it schedules onto the connector
        loop via ``connector.spawn`` — NEVER ``create_task`` (which would fail off-loop)
        and NEVER ``connector.call(...).result()`` (which would block the engine thread on
        the fetch). The only thing crossing back to the engine thread is the ``queue.put``.

        Raises
        ------
        StateError
            When no engine queue has been bound via :meth:`set_global_queue`.
        """
        if self._global_queue is None:
            # A bound queue is a runtime wiring precondition, not an invariant: a typed
            # StateError that ALWAYS fires (never a bare assert, which ``python -O``
            # strips) beats a ``None.put`` AttributeError swallowed by the task's except.
            raise StateError(
                "OkxDataProvider",
                "unbound",
                required_state="queue-bound (call set_global_queue first)",
                operation="spawn_warmup",
            )
        handle = self._connector.spawn(self._run_warmup(symbol, timeframe, limit))
        # A crash OUTSIDE the coroutine's own scrubbed except is logged + halts, never
        # swallowed.
        handle.add_done_callback(self._on_warmup_done)

    async def _run_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        """Await the loop-native REST warmup fetch, then emit ONE BarsLoaded / BarsLoadFailed.

        Runs on the connector loop. ``await``s the loop-native
        :meth:`_fetch_ohlcv_backfill_async` — no ``call().result()`` bridge — converts the
        ``ClosedBar``s via the feed's canonical ``_build_bar``, and puts ONE ``BarsLoaded``
        on the engine queue stamped with the business ``time`` of the NEWEST venue bar,
        never wall-clock. Any exception becomes ONE scrubbed ``BarsLoadFailed``.
        """
        # spawn_warmup guarantees a bound queue before scheduling; narrow for mypy.
        engine_queue = self._global_queue
        assert engine_queue is not None
        try:
            closed_bars = await self._fetch_ohlcv_backfill_async(
                symbol, timeframe, limit=limit)
            bars = self._closed_bars_to_bars(closed_bars)
            if not bars:
                # An empty warmup window cannot warm indicators — surface it as a scrubbed
                # failure rather than an empty BarsLoaded that breaks the payload contract.
                raise MissingPriceDataError(symbol, "warmup fetch returned no bars")
            engine_queue.put(BarsLoaded(
                symbol=symbol, timeframe=timeframe, bars=bars, time=bars[-1].time))
        except Exception as exc:
            # Scrub: the exception TYPE name only — NEVER str(exc), which may embed venue
            # request context / a credential / a URL.
            self.logger.warning(
                "OKX warmup for %s/%s failed (%s) — emitting BarsLoadFailed",
                symbol, timeframe, type(exc).__name__)
            engine_queue.put(BarsLoadFailed(
                symbol=symbol, reason=type(exc).__name__,
                # No venue bar exists on a failure to source business time from, and
                # this is a live-only control-plane signal that never reaches the
                # deterministic backtest path — so the wall-clock is the pragmatic stamp.
                time=datetime.now(UTC)))

    def _closed_bars_to_bars(
        self, closed_bars: "list[ClosedBar]"
    ) -> "tuple[Bar, ...]":
        """Convert fetched ``ClosedBar``s to ``Bar``s via the feed's canonical ``_build_bar``.

        Reusing ``LiveBarFeed._build_bar`` — the ONE ``ClosedBar`` → ``Bar`` conversion —
        keeps the warmup bulk-transport path and the live ``update()`` path building
        byte-identical ``Bar`` facts. The open-time is the venue ``ts`` as a tz-aware
        ``pd.Timestamp``, never wall-clock. Live-only imports are kept LOCAL.
        """
        import pandas as pd

        from itrader.price_handler.feed.live_bar_feed import LiveBarFeed
        return tuple(
            LiveBarFeed._build_bar(
                pd.Timestamp(cb["ts"], unit="ms", tz="UTC"), cb)
            for cb in closed_bars)

    def _on_warmup_done(self, task: "asyncio.Task[Any]") -> None:
        """Supervise the spawned warmup task — an unknown failure halts the engine.

        Mirrors :meth:`_on_gap_backfill_done`; what it catches is a crash OUTSIDE
        ``_run_warmup``'s own scrubbed except — e.g. the emit itself failing.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        self.logger.error(
            "OKX warmup task died (%s) — halting engine", type(exc).__name__)
        if self._halt_signal is not None:
            self._halt_signal("connector-fatal")

    # --- lifecycle ------------------------------------------------------------

    def stop(self) -> None:
        """Mark the stream stopped. Task cancellation + session close are owned by the
        connector's ``disconnect``, which cancels the spawned handle; the candle loop's
        ``async with`` then closes the aiohttp session."""
        self._stream_handle = None
