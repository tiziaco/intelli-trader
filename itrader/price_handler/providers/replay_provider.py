"""ReplayDataProvider — the offline, synchronous stand-in for ``OkxDataProvider`` that
replays the committed golden BTCUSD CSV through the exact Phase-3 feed seam (PAPER-03,
COV-01, D-02/D-03/D-09/D-10/D-12).

This is the replay entry point that makes the paper-parity gate meaningful (D-02).
Because the exchange/matching/cost code is shared with the backtest (D-04), driving the
live-paper path from this provider proves that ``LiveBarFeed`` + the live wiring reproduce
the backtest on identical data.

The provider is a DROP-IN for ``OkxDataProvider`` on the two methods the Phase-3
``LiveBarFeed``/``LiveTradingSystem`` wiring actually call — ``set_bar_sink`` and
``fetch_ohlcv_backfill`` — plus a NEW ``replay_bar`` / ``iter_closed_bars`` pair that
replaces the async ``_stream_candles`` loop with a SYNCHRONOUS in-thread push (D-03). It
adds no async surface and pulls in no live-transport or exchange-client dependency — it is
import-light and CI-runnable offline.

Golden data source (D-01/D-02): the rows come from ``CsvPriceStore`` (the SAME committed
dataset the backtest reads), so iterating its frame yields an identical row set/order/values
to the backtest — the parity anchor.

Decimal edge (money correctness): every numeric CSV cell crosses the Decimal boundary via
``to_money(str(x))`` — never the raw Decimal-from-float constructor and never a bulk float
cast of the frame.

Business time (D-09): ``ts`` is the CSV bar-OPEN timestamp in milliseconds, kept verbatim
(``int(index.value // 1_000_000)`` off the tz-aware ``DatetimeIndex``), never wall-clock —
so the replayed bars land exactly on the backtest bar-open grid.

Routing keys (D-12): ``symbol``/``timeframe`` are stamped from the provider's own trusted
config (``self._symbol``/``self._timeframe``), NOT read off the row — the same tampering
defense as ``OkxDataProvider`` (T-04-01). Note the universe-member symbol form is
``"BTCUSD"`` (what the strategy's ``window()`` queries), NEVER ``"BTC/USDT"``.

Indentation: this file is 4-SPACE (the whole ``providers/`` tree is 4-space, matched to
``okx_provider.py``) — never tabs. ``mypy --strict`` applies (new code, matching the
``okx_provider`` discipline).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, Callable

from itrader.config.stream import FeedProviderSettings
from itrader.core.money import to_money
from itrader.logger import get_itrader_logger
from itrader.price_handler.providers.okx_provider import ClosedBar
from itrader.price_handler.store.csv_store import CsvPriceStore


class ReplayDataProvider:
    """Replay the golden ``CsvPriceStore`` frame as confirm-gated ``ClosedBar`` dicts.

    Constructed with the committed golden store (default ``CsvPriceStore()`` — the pinned
    BTCUSD dataset/window, byte-identical to the backtest store frame) plus the
    ``symbol``/``timeframe`` it stamps. It registers no sink at construction; the Phase-3
    ``LiveBarFeed`` registers one via :meth:`set_bar_sink`, and the 04-02 driver pushes each
    completed row synchronously via :meth:`replay_bar` (the public analog of
    ``OkxDataProvider._hand_closed_bar``).

    The confirm gate is satisfied by construction — every stored row is a completed bar, so
    each is handed straight to the sink (no ``confirm != "1"`` drop needed).

    Uniform provider surface (VENUE-05 / D-10): inherits nothing — it implements the
    optional streaming/wiring seams (``set_global_queue`` / ``set_halt_signal`` /
    ``set_stream_state_listener`` / ``subscribe`` / ``unsubscribe`` / ``spawn_warmup`` /
    ``is_streaming_healthy`` → ``True``) DIRECTLY as no-ops. Offline replay does NOT stream,
    so these are DELIBERATE no-ops — they exist only so the ``VenueLifecycle`` (05-06) can
    call the streaming seams UNCONDITIONALLY on any provider (killing the venue-string
    provider-wiring branch). It keeps its own real ``set_bar_sink``, so
    ``isinstance(ReplayDataProvider(...), LiveDataProvider)`` is True.
    """

    def __init__(
        self,
        store: CsvPriceStore | None = None,
        symbol: str = "BTCUSD",
        timeframe: str = "1d",
    ) -> None:
        """Bind the golden store + the stamping config; open no I/O beyond the store load.

        Parameters
        ----------
        store : CsvPriceStore, optional
            The golden price store. ``None`` defaults to ``CsvPriceStore()`` (the committed
            BTCUSD dataset, pinned window — byte-identical to the backtest store frame).
        symbol : str
            The universe-member ticker stamped into every ``ClosedBar`` (default
            ``"BTCUSD"``) — the form the strategy's ``window()`` queries, NOT ``"BTC/USDT"``.
        timeframe : str
            The bar timeframe stamped into every ``ClosedBar`` (default ``"1d"``).
        """
        self.logger = get_itrader_logger().bind(component="ReplayDataProvider")
        self._store = store if store is not None else CsvPriceStore()
        self._symbol = symbol
        self._timeframe = timeframe
        # The Phase-3 LiveBarFeed registers the sink; until then bars are dropped-and-logged.
        self._bar_sink: Callable[[ClosedBar], None] | None = None

    # -- Phase-3 feed seam (mirror okx_provider.py:160-174) --------------------

    def set_bar_sink(self, sink: Callable[[ClosedBar], None]) -> None:
        """Register the closed-bar sink the Phase-3 ``LiveBarFeed`` consumes.

        Verbatim analog of ``OkxDataProvider.set_bar_sink``: the provider hands a raw
        ``ClosedBar`` dict; the feed owns ``BarEvent`` construction and the ring buffer.
        """
        self._bar_sink = sink

    def replay_bar(self, bar: ClosedBar) -> None:
        """Deliver one completed bar to the registered sink (drop-and-log if unset).

        The PUBLIC synchronous analog of ``OkxDataProvider._hand_closed_bar`` — the 04-02
        driver interleaves these per-bar pushes with ``process_events`` (D-03). No sink
        registered is a legitimate (mis-wired) state: WARN and drop, never raise.
        """
        if self._bar_sink is None:
            self.logger.warning(
                "Closed bar dropped — no bar sink registered (set_bar_sink not called)")
            return
        self._bar_sink(bar)

    # -- Golden-CSV replay (NEW, replaces the async _stream_candles loop — D-03) --

    def iter_closed_bars(self) -> Iterator[ClosedBar]:
        """Yield the golden store rows as Decimal-edge ``ClosedBar`` dicts, in frame order.

        Each row's ``ts`` is the tz-aware ``date`` index value converted to epoch-ms
        verbatim (``int(index.value // 1_000_000)`` — the ms round-trip lands exactly on
        the backtest bar-open grid, D-09). Every OHLCV cell crosses the Decimal edge via
        ``to_money(str(cell))`` (never the Decimal-from-float constructor, never a bulk
        float cast). The
        ``symbol``/``timeframe`` routing keys are stamped from trusted provider config, NOT
        read off the row (D-12). Frame order/values are identical to the backtest read —
        the parity anchor (D-01).
        """
        frame = self._store.read_bars(self._symbol)
        for row in frame.itertuples():
            ts_ms = int(row.Index.value // 1_000_000)
            closed: ClosedBar = {
                "ts": ts_ms,
                "open": to_money(str(row.open)),
                "high": to_money(str(row.high)),
                "low": to_money(str(row.low)),
                "close": to_money(str(row.close)),
                "volume": to_money(str(row.volume)),
                "symbol": self._symbol,
                "timeframe": self._timeframe,
            }
            yield closed

    def fetch_ohlcv_backfill(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        limit: int | None = None,
    ) -> list[ClosedBar]:
        """Return the golden bars for the Phase-3 warmup / gap-backfill seam.

        Mirrors ``OkxDataProvider.fetch_ohlcv_backfill``'s signature so
        ``LiveBarFeed.set_provider``/``warmup`` have a working ``_provider`` seam. Returns
        ``iter_closed_bars()`` filtered to ``since is None or cb["ts"] >= since`` and
        truncated to ``limit``. The golden 1d bars are contiguous so no gap-backfill fires
        on the parity path, but the method must exist and be Decimal-edge-correct.
        ``limit`` defaults to the folded backfill page size (CFG-03/D-08,
        ``FeedProviderSettings().backfill_page``) when not given.
        """
        if limit is None:
            limit = FeedProviderSettings().backfill_page
        bars = [
            cb for cb in self.iter_closed_bars()
            if since is None or cb["ts"] >= since
        ]
        return bars[:limit]

    # -- Optional streaming/wiring seams: inline no-ops (VENUE-05 / D-10) -------
    # Offline replay does NOT stream, so each of these is a DELIBERATE no-op. They
    # exist only so the VenueLifecycle (05-06) can call the streaming seams
    # UNCONDITIONALLY on any provider — no venue-string branch, no hasattr probe.

    def set_global_queue(self, global_queue: Any) -> None:
        """No-op: a non-streaming provider emits no async warmup events."""
        return None

    def set_halt_signal(self, halt_signal: Callable[[str], None]) -> None:
        """No-op: a non-streaming provider raises no connector-fatal halt."""
        return None

    def set_stream_state_listener(
        self,
        on_down: Callable[[str], None],
        on_up: Callable[[str], None],
    ) -> None:
        """No-op: a non-streaming provider never goes down/up."""
        return None

    def subscribe(self, symbol: str) -> None:
        """No-op: a non-streaming provider has no per-symbol stream to subscribe."""
        return None

    def unsubscribe(self, symbol: str) -> None:
        """No-op: a non-streaming provider has no per-symbol stream to unsubscribe."""
        return None

    def spawn_warmup(self, symbol: str, timeframe: str, limit: int) -> None:
        """No-op: a non-streaming provider does no loop-native REST warmup."""
        return None

    def is_streaming_healthy(self) -> bool:
        """A non-streaming provider is trivially healthy."""
        return True
