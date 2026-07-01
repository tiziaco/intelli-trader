"""LiveBarFeed — the live push-driven ring-buffer BarFeed (Phase 3, FEED-01/02/04).

The live sibling of ``BacktestBarFeed``: a second concrete ``BarFeed`` that,
instead of precomputing frames from a store, ingests confirm-gated ``ClosedBar``
dicts pushed from the Phase-2 ``OkxDataProvider`` and serves the same read-model
surface off a bounded ``deque`` ring per ``(symbol, timeframe)`` (FEED-01, D-09).

Unlike the backtest feed (``TimeEvent`` -> ``generate_bar_event`` pull, D-20), the
live feed emits a single-ticker ``BarEvent`` DIRECTLY onto ``global_queue`` the
moment a closed bar arrives (D-02/D-03/D-04) — the bar's arrival IS the event,
replacing ``TimeGenerator``'s driver role (FEED-05). ``generate_bar_event`` is kept
as a DORMANT no-op so the reserved TIME route (D-05) stays wired without crashing.

The genuinely novel logic (no backtest analog) is the FEED-04 monotonic guard in
``update()``: every incoming bar is classified against the last-delivered stamp
``L`` per ``(symbol, timeframe)`` — in-sequence deliver, gap backfill-and-replay,
duplicate drop, revision forward-only WARN+drop (no state mutation, D-07), stale
reject (D-06). An out-of-order or replayed bar can never rewind indicator state.

Thread model (D-02/D-19): all ``update()`` calls stay on the single connector
asyncio thread (single-writer ring/guard); only the MPSC-safe ``queue.Queue.put``
crosses to the engine thread — no lock needed.

Inertness: this module is LAZY-imported inside ``LiveTradingSystem.__init__`` only
and MUST NOT be pulled onto the backtest hot path (the recurring milestone gate).
It is deliberately NOT re-exported from the ``feed`` package barrel.

Indentation: 4 SPACES (the ``price_handler/feed/`` package convention) — NO tabs.
"""

from __future__ import annotations

import queue
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

import pandas as pd

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.logger import get_itrader_logger
from itrader.outils.time_parser import to_timedelta

from .bar_feed import _AGG, _offset_alias
from .base import BarFeed

if TYPE_CHECKING:
    # ClosedBar is a TypedDict — needed only for annotations. Guarding the import
    # keeps aiohttp/connector code out of this module's runtime import graph
    # (``from __future__ import annotations`` makes every annotation a lazy string).
    from itrader.price_handler.providers.okx_provider import ClosedBar

_NS_PER_MS = 1_000_000


class LiveBarFeed(BarFeed):
    """Push-driven ring-buffer ``BarFeed`` for the live path (FEED-01/02/04).

    Holds a bounded ``deque(maxlen=cache_capacity())`` ring per ``(symbol,
    timeframe)`` (D-09), constructs ``Bar`` facts with tz-aware venue-open time
    from confirm-gated ``ClosedBar`` dicts, and emits single-ticker ``BarEvent``s
    directly onto the bound queue. The data provider is held on the PRIVATE
    ``self._provider`` (may be ``None`` at construction) and injected
    post-construction ONLY through :meth:`set_provider` (D-01/D-13).

    Parameters
    ----------
    provider : Any
        The data provider exposing ``fetch_ohlcv_backfill(symbol, timeframe,
        since, limit) -> list[ClosedBar]`` for gap-backfill/warmup. May be
        ``None`` (the OKX provider is injected later via :meth:`set_provider`).
    base_timeframe : timedelta
        The base-bar timeframe of the subscribed stream (``tf_base``).
    """

    def __init__(self, provider: Any, base_timeframe: timedelta) -> None:
        # The data provider lives on the PRIVATE attr; set_provider is the only
        # public post-construction write path (no public ``provider`` attribute).
        self._provider: Any = provider
        self._base_timeframe = base_timeframe
        self._base_alias = _offset_alias(base_timeframe)
        # Bounded ring per (symbol, timeframe) — created lazily on first delivery
        # with maxlen=cache_capacity() (D-09: read at creation, NEVER cached at
        # __init__, so the 03-04 D-13 registration sizes it to 100).
        self._ring: dict[tuple[str, str], deque[Bar]] = {}
        # Monotonic-guard L-tracking: last-delivered open-time per (symbol, tf).
        self._last_delivered: dict[tuple[str, str], pd.Timestamp] = {}
        # Newest-bar provision (P5-D16 / G5) written by every delivery.
        self._newest_bars: dict[str, Bar] = {}
        # Run-path bindings (mirror bar_feed.py:334-335); set via bind().
        self.global_queue: "Optional[queue.Queue[Any]]" = None
        self.membership: list[str] = []
        self.logger = get_itrader_logger().bind(component="LiveBarFeed")
        self.logger.info(
            "Live bar feed initialized (base timeframe %s)", self._base_alias)

    # -- Provider -> feed seam (D-01/D-13) ------------------------------------

    def set_provider(self, provider: Any) -> None:
        """Inject the data provider post-construction (the ONLY public write path).

        The 03-04 composition root constructs the OKX provider AFTER the feed and
        wires it here. ``update()`` / warmup / gap-backfill read the PRIVATE
        ``self._provider``; there is deliberately NO public ``provider`` attribute
        (a bare ``feed.provider = x`` would create a dead attribute and leave
        ``self._provider`` ``None``).
        """
        self._provider = provider

    def bind(self, global_queue: "Optional[queue.Queue[Any]]",
             membership: list[str]) -> None:
        """Bind the run-path event sink + membership (mirror ``BacktestBarFeed.bind``).

        ``update()`` needs ``self.global_queue`` to ``put`` the ``BarEvent``.
        """
        self.global_queue = global_queue
        self.membership = membership

    # -- Bar construction (Decimal edge already crossed at the provider) -------

    def _build_bar(self, t: pd.Timestamp, cb: "ClosedBar") -> Bar:
        """Build a ``Bar`` straight from the Decimal ``ClosedBar`` fields.

        The OHLCV are ALREADY ``Decimal`` (the provider crossed the edge via
        ``to_money``) — never re-cast through float / ``Bar.from_row`` (D-14).
        """
        return Bar(time=t, open=cb["open"], high=cb["high"], low=cb["low"],
                   close=cb["close"], volume=cb["volume"])

    # -- Ingestion — the FEED-04 monotonic-forward-only guard (D-06/D-07) ------

    def update(self, closed_bar: "ClosedBar") -> None:
        """Ingest one confirm-gated ``ClosedBar`` through the monotonic guard.

        Classifies the incoming open-time ``t`` against the last-delivered stamp
        ``L`` per ``(symbol, timeframe)`` (D-06 taxonomy):

        - ``L is None`` (first bar) or ``t == L + tf`` (in-sequence) → deliver.
        - ``t < L`` (stale) → reject + log, NO emit, no state mutation.
        - ``t == L`` (duplicate/revision) → identical values drop quietly;
          differing values are a forward-only revision (WARN + drop, NO state
          mutation — indicator state is never rewound, D-07).
        - ``t > L + tf`` (gap) → backfill the interior range ``[L+tf .. t-tf]``
          and replay each bar through ``update()``, THEN deliver ``t``.

        Every incoming bar AND every replayed backfill bar takes this one path
        (FEED-03 — no bulk fast-path). The gap recursion terminates because each
        replayed bar advances ``L`` by exactly one ``tf`` (no nested gap; a
        boundary re-send is absorbed by the duplicate branch, Pitfall 5). Stale /
        duplicate / revision are LOGGED, never raised — they are legitimate venue
        events. ``t`` is the venue open-time only (never ``datetime.now()``).
        """
        sym = closed_bar["symbol"]
        tf_str = closed_bar["timeframe"]
        tf = to_timedelta(tf_str)
        t = pd.Timestamp(closed_bar["ts"], unit="ms", tz="UTC")
        last = self._last_delivered.get((sym, tf_str))
        if last is not None:
            if t < last:
                return self._reject_stale(sym, t, last)
            if t == last:
                return self._duplicate_or_revision(sym, tf_str, t, closed_bar)
            if t > last + tf:
                self._backfill_gap(sym, tf_str, last + tf, t - tf)
        self._deliver(sym, tf_str, t, closed_bar)

    def _reject_stale(self, sym: str, t: pd.Timestamp,
                      last: pd.Timestamp) -> None:
        """Stale bar (``t < L``) → warn + drop, NO emit, no state mutation (D-06)."""
        self.logger.warning(
            "Stale bar rejected for %s: t=%s < last-delivered=%s "
            "(no emit, no state mutation)", sym, str(t), str(last))

    def _duplicate_or_revision(self, sym: str, tf_str: str, t: pd.Timestamp,
                               cb: "ClosedBar") -> None:
        """``t == L`` → duplicate drop (identical) or forward-only revision (D-07).

        A revision (differing OHLCV at the same open-time) is dropped WITHOUT any
        state mutation — the ``confirm==1`` gate means a forming bar is never
        delivered to revise, and indicator state is never rewound.
        """
        ring = self._ring.get((sym, tf_str))
        last_bar = ring[-1] if ring else None
        incoming = self._build_bar(t, cb)
        if last_bar is not None and self._same_ohlcv(last_bar, incoming):
            self.logger.debug(
                "Duplicate bar dropped for %s at %s (identical OHLCV)",
                sym, str(t))
            return
        self.logger.warning(
            "Revision dropped for %s at %s (forward-only, no state mutation, "
            "D-07): last-close=%s incoming-close=%s", sym, str(t),
            str(last_bar.close) if last_bar is not None else None,
            str(incoming.close))

    def _backfill_gap(self, sym: str, tf_str: str, first_missing: pd.Timestamp,
                      last_missing: pd.Timestamp) -> None:
        """Fill a hole ``[first_missing .. last_missing]`` and replay each bar.

        Fetches exactly the interior missing bars (one per ``tf``, inclusive both
        ends) via the PRIVATE ``self._provider.fetch_ohlcv_backfill`` (injected in
        the 03-04 OKX arm via :meth:`set_provider`) and replays each returned
        ``ClosedBar`` through ``update()`` — the single FEED-03 path.
        """
        tf = to_timedelta(tf_str)
        since_ms = int(first_missing.value // _NS_PER_MS)
        limit = int((last_missing - first_missing) / tf) + 1
        self.logger.info(
            "Gap for %s: backfilling %d interior bar(s) [%s .. %s]",
            sym, limit, str(first_missing), str(last_missing))
        bars = self._provider.fetch_ohlcv_backfill(
            sym, tf_str, since=since_ms, limit=limit)
        for cb in bars:
            self.update(cb)

    @staticmethod
    def _same_ohlcv(a: Bar, b: Bar) -> bool:
        """True iff two Bars carry identical OHLCV (duplicate vs revision, D-06)."""
        return (a.open == b.open and a.high == b.high and a.low == b.low
                and a.close == b.close and a.volume == b.volume)

    def _deliver(self, sym: str, tf_str: str, t: pd.Timestamp,
                 cb: "ClosedBar") -> None:
        """Construct the Bar, append to the (lazily-sized) ring, and emit."""
        bar = self._build_bar(t, cb)
        ring = self._ring.get((sym, tf_str))
        if ring is None:
            # D-09: size the ring by the derived capacity AT CREATION (read
            # lazily, not cached at __init__) so the 03-04 D-13 registration
            # makes it 100 on the live feed.
            ring = deque(maxlen=self.cache_capacity())
            self._ring[(sym, tf_str)] = ring
        ring.append(bar)
        self._newest_bars[sym] = bar
        self._last_delivered[(sym, tf_str)] = t
        self._emit(sym, bar)

    def _emit(self, sym: str, bar: Bar) -> None:
        """Put a single-ticker ``BarEvent`` on the queue (D-02/D-03/D-04).

        The ``(sym, bar)`` shape is the Phase-6 burst-coalescing seam — a
        consolidator can slot in here WITHOUT changing the ``BarEvent`` contract.
        Emission is one ``queue.Queue.put`` (MPSC-safe, no lock — D-19).
        """
        assert self.global_queue is not None, (
            "LiveBarFeed.update() requires a bound queue — call bind() first")
        self.global_queue.put(BarEvent(time=bar.time, bars={sym: bar}))

    # -- Newest-bar provision (P5-D16 / G5) -----------------------------------

    def newest_bar(self, ticker: str) -> Bar | None:
        """Return the newest completed ``Bar`` delivered for ``ticker``, or ``None``."""
        return self._newest_bars.get(ticker)

    # -- Per-tick fact lookup (mostly dormant on live — direct emission used) --

    def current_bars(self, time: datetime) -> dict[str, Bar]:
        """Return the ``Bar`` facts stamped exactly ``time``, keyed by ticker.

        Required by the ABC and the reserved TIME/``generate_bar_event`` path;
        live delivery is direct via ``update()`` so this is mostly dormant. Reads
        the ring newest-first and stops once a bar is older than ``time`` (the
        ring is monotonically ordered).
        """
        bars: dict[str, Bar] = {}
        for (sym, _tf), ring in self._ring.items():
            for bar in reversed(ring):
                if bar.time == time:
                    bars[sym] = bar
                    break
                if bar.time < time:
                    break
        return bars

    # -- History windows (D-11 pull-resample from the ring) -------------------

    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame:
        """Return the last ``max_window`` COMPLETED bars visible at ``asof``.

        Mirrors the ``BacktestBarFeed`` rule-4 cutoff
        (``cutoff = asof - timeframe + base_timeframe``, degenerating to ``asof``
        when ``timeframe == base_timeframe``): a bucket stamped ``B`` is included
        iff ``B <= cutoff`` (``searchsorted`` side ``"right"``). For a coarser
        ``timeframe`` the base ring is resampled (``label='left', closed='left'``,
        ``_offset_alias`` — never the legacy ``time_parser`` string, Pitfall 4).

        Raises
        ------
        MissingPriceDataError
            If ``ticker`` has no ring (FR7 — never ``None``).
        ValueError
            If ``asof`` is tz-naive (would skew the tz-aware index compare).
        """
        base = self._base_frame(ticker)
        if timeframe == self._base_timeframe:
            resampled = base
        else:
            alias = _offset_alias(timeframe)
            resampled = (base.resample(alias, label="left", closed="left")
                         .agg(_AGG).dropna(how="all"))
        cutoff = asof - timeframe + self._base_timeframe
        if getattr(cutoff, "tzinfo", None) is None:
            raise ValueError(
                "window() asof must be tz-aware to match the tz-aware ring "
                f"index; got {asof!r}")
        pos = int(resampled.index.searchsorted(pd.Timestamp(cutoff),
                                               side="right"))
        start = max(0, pos - max_window)
        return resampled.iloc[start:pos]

    def _base_frame(self, ticker: str) -> pd.DataFrame:
        """Build a tz-aware float64 OHLCV frame from the ticker's base ring (D-17).

        Analytics stay float (only ``Bar`` touches money) — the ring ``Decimal``
        OHLCV are cast to ``float`` for the resample/window path.
        """
        ring = self._find_ring(ticker)
        index = pd.DatetimeIndex([bar.time for bar in ring])
        return pd.DataFrame(
            {
                "open": [float(bar.open) for bar in ring],
                "high": [float(bar.high) for bar in ring],
                "low": [float(bar.low) for bar in ring],
                "close": [float(bar.close) for bar in ring],
                "volume": [float(bar.volume) for bar in ring],
            },
            index=index,
        )

    def _find_ring(self, ticker: str) -> "deque[Bar]":
        """Return the ring for ``ticker`` (any timeframe), or raise (FR7)."""
        for (sym, _tf), ring in self._ring.items():
            if sym == ticker:
                return ring
        raise MissingPriceDataError(
            ticker, "ticker not known to LiveBarFeed (no ring)")

    # -- Multi-symbol megaframe (screener path, D-19) --------------------------

    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame:
        """Return a multi-symbol close-price frame visible at ``asof`` (D-19).

        Per-symbol ``window`` close columns keyed by the symbols ACTUALLY
        included (FR8). Golden SMA_MACD is N=1 and never exercises this — a
        correct-but-simple form suffices (RESEARCH §Pattern 1).
        """
        closes: list[pd.Series] = []
        included: list[str] = []
        seen: set[str] = set()
        for (sym, _tf) in self._ring:
            if sym in seen:
                continue
            seen.add(sym)
            frame = self.window(sym, timeframe, max_window, asof)
            if frame.empty:
                continue
            closes.append(frame["close"].rename(sym))
            included.append(sym)
        if not closes:
            return pd.DataFrame()
        return pd.concat(closes, axis=1, keys=included)

    # -- Dormant TIME route (D-05) --------------------------------------------

    def generate_bar_event(self, time_event: TimeEvent) -> Optional[BarEvent]:
        """DORMANT no-op — live emits BarEvents directly via ``update()`` (D-02/D-03).

        ``generate_bar_event`` is concrete on ``BacktestBarFeed`` ONLY and is NOT
        inherited by ``LiveBarFeed(BarFeed)`` — it is defined here so
        ``LiveTradingSystem.__init__`` can pass ``self.feed.generate_bar_event``
        to ``EventHandler`` unconditionally (live_trading_system.py:201) without
        crashing on any venue. The live TIME route is reserved but inert (D-05).
        """
        return None
