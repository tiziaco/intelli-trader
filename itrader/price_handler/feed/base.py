"""Feed seam for the price-handler split (M5-05, D-16/D-20).

A ``BarFeed`` is the runtime READ-MODEL the engine queries per tick: the
current ``Bar`` facts for the BarEvent (D-15 "event = fact, feed = query"),
look-ahead-safe history windows for strategies (D-02/D-20 — strategies never
choose the as-of time; ``asof`` always comes from the event), and the
multi-symbol megaframe for screeners (D-19).

The Feed is the SINGLE enforcement point of the bar-timing contract: the
"strategies never see the future" invariant lives in the window slice here
and nowhere else (M5-01). See ``bar_feed`` for the full contract.

FR7 — loud typed errors, never silent ``None``: accessors raise
``MissingPriceDataError`` for unknown tickers.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING

import pandas as pd

from itrader.core.bar import Bar

from .cache_registration import RawBarConsumer, derive

if TYPE_CHECKING:
    # String-only forward-refs for the ``generate_bar_event`` signature — keeps the
    # base feed module's runtime imports unchanged (the events package is pure, but
    # guarding it costs nothing and preserves the import surface exactly).
    from itrader.events_handler.events import BarEvent, TimeEvent


def assert_update_trigger(base_timeframe: timedelta,
                          timeframes: Iterable[timedelta]) -> None:
    """The G1 update-trigger seam guard — interface-only (P5-D16b).

    The shared recent-bars feed's update trigger is conceptually "a consolidator
    emits on ``(symbol, timeframe)`` bucket-close -> drives ``indicator.update()``."
    The interface MUST NOT hardcode per-base-tick updates; it asserts only the
    causality ordering that makes any such consolidator look-ahead-safe:

        ``base_timeframe <= min(timeframe)`` over every consumed timeframe.

    A base bar must be no coarser than the finest consumed timeframe — otherwise a
    finer consumer would need a bar the base feed has not produced yet (a
    sub-base, non-causal trigger that could read ahead). For golden SMA_MACD
    (``1d == base == 1d``) the trigger collapses to "every tick" and the assertion
    holds trivially (``1d <= 1d``).

    The full multi-timeframe consolidator is DEFERRED (tracked to-do —
    ``.planning/todos/multi-timeframe-consolidator.md``); Plan A ships this guard
    + the golden-collapsed "every tick" case only.

    Parameters
    ----------
    base_timeframe : timedelta
        The store's base-bar timeframe (``tf_base``).
    timeframes : Iterable[timedelta]
        Every timeframe a registered consumer drives its update off. Empty is
        permitted (no consumer wired -> nothing to order against).

    Raises
    ------
    ValueError
        If ``base_timeframe > min(timeframe)`` for any consumed timeframe — the
        non-causal/sub-base trigger that could read ahead.
    """
    frames = list(timeframes)
    if not frames:
        return
    finest = min(frames)
    if base_timeframe > finest:
        raise ValueError(
            "update-trigger seam (G1, P5-D16b): base_timeframe "
            f"{base_timeframe!r} must be <= min(timeframe) {finest!r} — a base "
            "bar coarser than the finest consumed timeframe would require a bar "
            "the feed has not produced (a non-causal sub-base trigger)")


class BarFeed(ABC):
    """Abstract base class for the per-tick market-data read model (M5-05).

    Serves current-bar facts, completed-bars-only history windows, and the
    multi-symbol megaframe. Backtest implementation: ``BacktestBarFeed``
    (precompute + slice); a live feed lands with D-live.

    Shared recent-bars API (P5-D16)
    -------------------------------
    The feed also owns the shared recent-bars seam: a **newest-bar provision**
    (``newest_bar`` — the latest completed bar per symbol the G5 single walk
    writes) plus a **consumer-registration / capacity-derivation interface**
    (``register_raw_bar_consumer`` / ``cache_capacity`` — delegating to
    ``cache_registration.derive``, the pure ``derive_instruments`` mirror). The
    deep multi-bar buffer is DEFERRED (P5-D16/P5-D22) — Plan A ships the
    newest-bar provision + the registration interface only, so the first raw-bar
    consumer (screener / raw-history strategy) extends it with zero structural
    change.
    """

    # -- Shared recent-bars registration / capacity (P5-D16) ------------------

    def register_raw_bar_consumer(self, consumer: RawBarConsumer) -> None:
        """Register a raw-bar consumer; capacity is re-derived from all of them.

        The consumer-registration half of the shared recent-bars interface
        (P5-D16). Capacity is NEVER hand-set — it is purely derived via
        ``cache_registration.derive`` over the registered consumers (the
        ``derive_instruments`` mirror), keying off RAW-BAR consumers because
        indicators self-buffer under Model B (P5-D07).

        There is NO raw-bar consumer in this phase (the deferral, P5-D16/P5-D22);
        this method is the extension seam the first screener / raw-history
        strategy calls. Until then the derived capacity stays at the newest-bar
        floor.

        Parameters
        ----------
        consumer : RawBarConsumer
            A raw-bar consumer declaring ``required_history_depth``.
        """
        self._raw_bar_consumers.append(consumer)

    def cache_capacity(self) -> int:
        """The derived shared recent-bars cache capacity (P5-D16/P5-D22).

        Purely derived (never hand-set) from the registered raw-bar consumers via
        ``cache_registration.derive``. With no consumer registered (the current
        deferral) this is the newest-bar-only floor (depth 1).
        """
        return derive(self._raw_bar_consumers)

    @property
    def _raw_bar_consumers(self) -> list[RawBarConsumer]:
        """The registered raw-bar consumers (lazily-initialised, ABC-shared).

        Held on the ABC so every concrete feed shares the same registration
        seam without re-declaring storage. Lazily created so subclasses need no
        ``super().__init__`` change.
        """
        registry = getattr(self, "_raw_bar_consumers_store", None)
        if registry is None:
            registry = []
            self._raw_bar_consumers_store = registry
        return registry

    # -- Shared recent-bars: newest-bar provision (P5-D16 / G5) ----------------

    @abstractmethod
    def newest_bar(self, ticker: str) -> Bar | None:
        """Return the newest completed ``Bar`` seen for ``ticker``, or ``None``.

        The newest-bar half of the shared recent-bars interface (P5-D16). The
        value is written by the SINGLE G5 per-symbol walk (P5-D16a) that also
        builds the ``BarEvent`` payload — one source of truth, never a second
        parallel pass. Returns ``None`` before the symbol's first bar.

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.

        Returns
        -------
        Bar | None
            The latest completed bar written for ``ticker`` by the most recent
            ``current_bars``/``generate_bar_event`` tick, or ``None`` if the
            symbol has produced no bar yet.
        """
        pass

    # -- Per-tick fact lookup (BarEvent payload, D-15) ------------------------

    @abstractmethod
    def current_bars(self, time: datetime) -> dict[str, Bar]:
        """Return the ``Bar`` facts stamped exactly ``time``, keyed by ticker.

        Parameters
        ----------
        time : datetime
            The tick timestamp (a base-bar open-time stamp, D-04).

        Returns
        -------
        dict[str, Bar]
            One immutable ``Bar`` per ticker that has a base bar stamped
            exactly ``time``. Tickers with no bar at ``time`` are ABSENT
            from the dict (sparse universe, D-15) — never ``None`` values.
        """
        pass

    # -- Run-path event-sink binding (wiring time) ----------------------------

    @abstractmethod
    def bind(self, global_queue: Any, membership: list[str]) -> None:
        """Bind the run-path event sink + membership set (wiring time).

        Called once by the shared universe wiring (``wire_universe``) after
        membership is derived. Declared on the base so the SHARED wiring seam can
        call ``feed.bind`` uniformly across modes (``BacktestBarFeed`` enqueues via
        the bound sink or returns the ``BarEvent`` when ``global_queue`` is ``None``;
        ``LiveBarFeed`` binds the same sink for ``update()`` to ``put`` bars). The
        ``global_queue`` type is left loose (``Any``) because the concrete feeds bind
        different transports (an ``EventBus`` in backtest, a ``queue.Queue`` in live).

        Parameters
        ----------
        global_queue : Any
            The event sink the feed enqueues bar events onto, or ``None`` for the
            backtest return-contract.
        membership : list[str]
            The derived tradable symbol set (used for the missing-ticker warning).
        """
        pass

    # -- TIME-route bar-event factory (D-20/D-15) -----------------------------

    @abstractmethod
    def generate_bar_event(self, time_event: "TimeEvent") -> "BarEvent | None":
        """Return the ``BarEvent`` for the tick at ``time_event``, or ``None``.

        The TIME-route bar-event factory (D-20/D-15). Declared on the base so the
        shared ``compose_engine`` seam can pass ``feed.generate_bar_event`` to the
        ``EventHandler`` uniformly across modes (compose reads the base ``BarFeed``
        type off ``ctx.feed``, not a concretion). ``BacktestBarFeed`` builds the
        event from the pinned bar grid; ``LiveBarFeed`` is a DORMANT no-op — live
        emits ``BarEvent``s directly via ``update()``, so its TIME route is
        reserved-but-inert (D-02/D-05).

        Parameters
        ----------
        time_event : TimeEvent
            The tick the bar event is produced for (the pinned bar-date grid stamp
            in backtest; unused by the dormant live override).

        Returns
        -------
        BarEvent | None
            The bar event for the tick, or ``None`` when there is no bar to emit.
        """
        pass

    # -- History windows (strategy push path, D-20) ---------------------------

    @abstractmethod
    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame:
        """Return the last ``max_window`` COMPLETED bars visible at ``asof``.

        Look-ahead safety (M5-01/D-02) is enforced here and only here: the
        returned frame contains exclusively bars whose interval has fully
        closed by the tick at ``asof`` — the forming resampled bucket is
        invisible.

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.
        timeframe : timedelta
            The bar timeframe of the requested window (may differ from the
            store's base timeframe; resampled frames are precomputed/memoized,
            M5-03 — zero resample calls on the per-tick path).
        max_window : int
            Maximum number of bars to return (fewer near dataset start).
        asof : datetime
            The decision tick (comes from the BarEvent — strategies never
            choose it, D-20).

        Returns
        -------
        pd.DataFrame
            float64 OHLCV frame (D-17 — analytics stay float; only ``Bar``
            touches money), tz-aware ``DatetimeIndex``, completed bars only.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the feed (FR7 — never ``None``).
        ValueError
            If ``timeframe`` maps to no supported pandas offset alias.
        """
        pass

    # -- Multi-symbol megaframe (screener path, D-19) --------------------------

    @abstractmethod
    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame:
        """Return a multi-symbol close-price frame visible at ``asof`` (D-19).

        Parameters
        ----------
        asof : datetime
            The decision tick (same visibility rule as ``window``).
        timeframe : timedelta
            The bar timeframe of the per-symbol windows.
        max_window : int
            Maximum number of bars per symbol.

        Returns
        -------
        pd.DataFrame
            Per-symbol close columns concatenated with ``keys`` equal to the
            symbols ACTUALLY included (FR8 fix — symbols with an empty window
            at ``asof`` are excluded together with their key), over a
            tz-aware ``DatetimeIndex``.
        """
        pass
