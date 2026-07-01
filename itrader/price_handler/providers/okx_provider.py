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
Protocol only (imported from the ``itrader.connectors`` barrel) — it NEVER imports the
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

import json
from decimal import Decimal
from typing import Any, Callable, TypedDict

import aiohttp

from itrader.connectors import LiveConnector
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
        """Consume the native business candle socket, gating on ``confirm == "1"``.

        Opens an aiohttp WS to ``wss://{host}:8443/ws/v5/business`` where the host is
        driven off the injected connector's ``sandbox`` bool (D-02 correction: host, NOT
        header). Subscribes the ``candle{tf}`` channel for ``instId`` and forwards only
        completed bars downstream. The ``async with`` guarantees the session closes on task
        cancellation (Pitfall 4 — an unclosed session raises ``ResourceWarning`` and fails
        the strict suite).
        """
        host = "wspap.okx.com" if self._connector.sandbox else "ws.okx.com"
        url = f"wss://{host}:8443/ws/v5/business"
        subscribe = {"op": "subscribe",
                     "args": [{"channel": channel, "instId": symbol_okx}]}
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, autoping=False) as ws:
                await ws.send_json(subscribe)
                self.logger.info(
                    "OKX candle stream subscribed",
                    host=host, channel=channel, instId=symbol_okx)
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        continue
                    payload: Any = json.loads(msg.data)
                    rows: Any = payload.get("data", []) if isinstance(payload, dict) else []
                    for row in rows:
                        self._process_row(row)

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
        closed: ClosedBar = {
            "ts": int(row[0]),
            "open": to_money(str(row[1])),
            "high": to_money(str(row[2])),
            "low": to_money(str(row[3])),
            "close": to_money(str(row[4])),
            "volume": to_money(str(row[5])),
        }
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
        okx_tf = self._okx_interval(timeframe)
        client = self._connector.client

        raw: list[Any] = []
        page: list[Any] = list(
            self._connector.call(client.fetch_ohlcv(symbol_okx, okx_tf, since, limit)))
        raw.extend(page)
        # IN-02: ``len(page) == limit`` (limit > 0) already implies ``page`` is
        # truthy, so the ``and page`` clause was dead.
        while len(page) == limit:
            last_ts = int(page[-1][0])
            page = list(self._connector.call(
                client.fetch_ohlcv(symbol_okx, okx_tf, last_ts + 1, limit)))
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
            })
        return bars

    # --- lifecycle ------------------------------------------------------------

    def stop(self) -> None:
        """Mark the stream stopped. Task cancellation + session close are owned by the
        connector's ``disconnect`` (which cancels the spawned handle; the candle loop's
        ``async with`` then closes the aiohttp session — Pitfall 4)."""
        self._stream_handle = None
