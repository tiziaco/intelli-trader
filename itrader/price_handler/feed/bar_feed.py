"""Look-ahead-safe backtest bar feed — THE bar-timing contract (M5-01/M5-03).

This module is the single enforcement point and the single written home of
the engine's bar-timing contract (D-01..D-05, RESEARCH Pattern 1). Every
component is tested against these seven rules; look-ahead safety is an
ENGINE invariant enforced in the window slice below — never a strategy
responsibility.

The bar-timing contract
-----------------------

1. **Bars are stamped by open time** (D-04). The bar stamped ``T`` covers
   the interval ``[T, T + tf_base)`` (Binance kline / CCXT / TradingView
   convention — what the Phase 8 external engines will see).
2. **The tick at ``T`` means "the bar stamped ``T`` just closed."** The
   wall-clock semantics of the tick are ``T + tf_base``, but it is
   labeled ``T``.
3. **Decision visibility at tick ``T``:** all base bars stamped ``<= T``
   (every one of them is closed by rule 2). The same-timeframe window is
   the last ``N`` bars stamped ``<= T`` — both branches obey the same
   "last closed bar <= T" rule (D-02).
4. **Resampled visibility at tick ``T``:** a resampled bucket stamped
   ``B`` (``label='left'``, ``closed='left'``, covering ``[B, B + TF)``)
   is visible iff its last base bar has closed:
   ``B + TF <= T + tf_base``, equivalently ``B <= T - TF + tf_base``.
   The forming bucket is INVISIBLE. (Worked example: base 1d, TF = 7d,
   tick T = Sun Jan 7. Bucket B = Mon Jan 1 covers Jan 1-7; its last base
   bar is stamped Jan 7 = T and closed at the tick -> visible. At
   T = Sat Jan 6 it is NOT visible.) Rules 3 and 4 coincide when
   ``TF == tf_base``.
5. **Fills land at the next open** (D-01): a market order decided at tick
   ``T`` rests in the book and fills at the open of the bar stamped
   ``T + tf_base``, at tick ``T + tf_base``, with
   ``FillEvent.time = T + tf_base``.
6. **Equity at tick ``T``** = cash + positions valued at the close of the
   bar stamped ``T`` (D-05, close-marked).
7. **Last-bar edge:** orders decided on the final tick never fill — there
   is no next bar. Documented, not special-cased.

Replaces ``data_provider.get_resampled_bars``, whose resampled-branch upper
bound ``time + timeframe`` was the #21 look-ahead (future bars leaked into
the decision window), and whose per-tick ``resample`` was the dominant
hot-loop cost (#4). Here resampled frames are computed ONCE per
(ticker, timeframe) and the per-tick path is a pure ``searchsorted`` slice
(M5-03 — zero resample calls per tick).

Purity: like ``MatchingEngine``, the slice path has NO dependency on the
event queue, performs no network access and no store writes, and is fully
deterministic given the store frames. The logger is bound at construction
only; the per-tick QUERY path (window/megaframe/current_bars) does not
log. The one queue-aware seam is the BarEvent FACTORY
(``generate_bar_event``, relocated from the deleted ``DynamicUniverse`` —
Plan 07-02, D-20): the data engine produces the per-tick BarEvent and may
log the missing-ticker warning (RESEARCH OQ4).
"""

import queue
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from itrader.core.bar import Bar
from itrader.core.exceptions import MissingPriceDataError
from itrader.events_handler.events import BarEvent, TimeEvent
from itrader.logger import get_itrader_logger
from itrader.price_handler.store.base import PriceStore

from .base import BarFeed

# OHLCV aggregation spec for resampled buckets (RESEARCH Pattern 2,
# verified against pandas 2.3.3).
_AGG = {"open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}


def _offset_alias(timeframe: timedelta) -> str:
    """Map a timeframe to its canonical pandas offset alias.

    The Feed OWNS this map (Pitfall 2): the legacy ``outils.time_parser``
    timedelta-to-string helper must NEVER be reused for resample rules — it
    produces ``'30m'`` for minutes, which pandas 2.3.3 parses as MONTH-END
    and deprecates with a FutureWarning (a test error under
    ``filterwarnings=["error"]``).

    Mapping: minutes -> ``'min'``, hours -> ``'h'``, days -> ``'D'``;
    weeks resolve through the day branch as ``f'{n*7}D'`` (data-anchored —
    never ``'W'``, which anchors to Sunday with right labels).

    Parameters
    ----------
    timeframe : timedelta
        The bar timeframe to canonicalize.

    Returns
    -------
    str
        The pandas offset alias, e.g. ``'30min'``, ``'4h'``, ``'7D'``.

    Raises
    ------
    ValueError
        For unsupported units — anything not a whole number of minutes
        (months are not representable as a timedelta and are unsupported).
    """
    total = timeframe.total_seconds()
    seconds = int(total)
    if seconds <= 0 or seconds != total:
        raise ValueError(
            f"unsupported resample timeframe {timeframe!r} — must be a "
            "positive whole number of minutes/hours/days/weeks")
    if seconds % 86400 == 0:
        return f"{seconds // 86400}D"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    raise ValueError(
        f"unsupported resample timeframe {timeframe!r} — supported units "
        "are minutes, hours, days and weeks (months are not supported)")


class BacktestBarFeed(BarFeed):
    """Precompute-then-slice backtest feed (M5-01/M5-03/M5-05).

    Pulls every base frame from the store at construction, resamples once
    per (ticker, timeframe) — eagerly via ``precompute`` from strategy
    declarations, lazily-memoized on first access for undeclared timeframes
    (screener/megaframe path) — and serves per-tick windows as O(log n)
    positional slices under the completed-bars visibility rule (module
    docstring, rule 4).

    Parameters
    ----------
    store : PriceStore
        The canonical OHLCV store; its frames seed the cache at the base
        timeframe. Read-only access (FR6) — the feed never writes.
    base_timeframe : timedelta
        The timeframe of the store's base bars (``tf_base`` in the
        contract), e.g. ``timedelta(days=1)`` for the golden dataset.
    """

    def __init__(self, store: PriceStore, base_timeframe: timedelta) -> None:
        self._base_timeframe = base_timeframe
        self._base_alias = _offset_alias(base_timeframe)
        self._symbols: list[str] = store.symbols()

        # Precomputed frames (working state) keyed by (ticker, canonical
        # timeframe string) — base frames from store.read_bars seed the
        # cache; resampled frames memoize on precompute()/first access.
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        for ticker in self._symbols:
            self._frames[(ticker, self._base_alias)] = store.read_bars(ticker)

        # Run-path bindings for the BarEvent factory (Plan 07-02, D-20) —
        # set by the trading system at wiring time via ``bind``. The queue
        # is optional (unbound: the factory RETURNS the event); membership
        # is used ONLY for the missing-ticker warning (RESEARCH OQ4).
        self.global_queue: "Optional[queue.Queue[Any]]" = None
        self.membership: list[str] = []

        self.logger = get_itrader_logger().bind(component="BacktestBarFeed")
        self.logger.info(
            'Backtest bar feed initialized (%d symbols, base timeframe %s)',
            len(self._symbols), self._base_alias)

    # -- Precompute (M5-03 — resample once, out of the hot loop) --------------

    def precompute(self, tickers: list[str], timeframe: timedelta) -> None:
        """Eagerly resample and memoize frames for a (tickers, timeframe) set.

        Called at run-init from registered strategy declarations (06-05).
        Timeframes not declared here lazily compute-and-memoize on first
        ``window``/``megaframe`` access — either way each (ticker,
        timeframe) pair is resampled at most ONCE (M5-03).

        Parameters
        ----------
        tickers : list[str]
            The tickers to precompute.
        timeframe : timedelta
            The target bar timeframe.
        """
        alias = _offset_alias(timeframe)
        for ticker in tickers:
            self._resampled_frame(ticker, alias)

    def _resampled_frame(self, ticker: str, alias: str) -> pd.DataFrame:
        """Return the memoized frame for (ticker, alias), resampling once.

        ``label='left', closed='left'`` stamps each bucket by its open time
        (rule 1). NOTE (Pitfall 1): pandas KEEPS the trailing forming
        bucket — visibility is enforced at slice time in ``window``, never
        by resample alone.
        """
        key = (ticker, alias)
        frame = self._frames.get(key)
        if frame is not None:
            return frame
        base = self._frames.get((ticker, self._base_alias))
        if base is None:
            raise MissingPriceDataError(
                ticker, "ticker not loaded in BacktestBarFeed")
        resampled = base.resample(alias, label="left", closed="left").agg(_AGG)
        self._frames[key] = resampled
        return resampled

    # -- BarEvent factory (relocated from DynamicUniverse — Plan 07-02, D-20) --

    def bind(self, global_queue: "Optional[queue.Queue[Any]]",
             membership: list[str]) -> None:
        """Bind the run-path event sink and membership set (wiring time).

        Called once by the trading system after membership is derived
        (``itrader.universe.derive_membership``). ``global_queue`` may be
        ``None`` — the factory then returns the BarEvent instead of
        enqueueing it.

        Parameters
        ----------
        global_queue : Optional[queue.Queue]
            The global events queue, or ``None`` for the return contract.
        membership : list[str]
            The derived tradable symbol set — used ONLY for the
            missing-ticker warning loop (RESEARCH OQ4).
        """
        self.global_queue = global_queue
        self.membership = membership

    def generate_bar_event(self, time_event: TimeEvent) -> Optional[BarEvent]:
        """Generate the per-tick BarEvent from the feed's own bar facts.

        The relocated ``DynamicUniverse.generate_bar_event`` body (D-20 —
        the data engine owns BarEvent production, LEAN/Nautilus shape):
        wrap ``current_bars(time)`` in a BarEvent, warn for any membership
        ticker absent from the produced bars (sparse universe), and either
        enqueue (queue bound: returns ``None``) or return the event.

        Parameters
        ----------
        time_event : TimeEvent
            Simulation-clock event carrying the last closed bar time.
        """
        bars = self.current_bars(time_event.time)

        for ticker in self.membership:
            if ticker not in bars:
                self.logger.warning(
                    'Bar feed: no bar for ticker %s at %s in the feed',
                    ticker, str(time_event.time))

        bar_event = BarEvent(time=time_event.time, bars=bars)

        if self.global_queue is not None:
            self.global_queue.put(bar_event)
            return None
        return bar_event

    # -- Per-tick fact lookup (BarEvent payload, D-15) ------------------------

    def current_bars(self, time: datetime) -> dict[str, Bar]:
        """Return the ``Bar`` facts stamped exactly ``time``, keyed by ticker.

        Builds each ``Bar`` via ``Bar.from_row`` (Decimal string path, D-14)
        from the base-frame row stamped exactly ``time``; tickers with no
        bar at ``time`` are ABSENT from the dict (sparse universe, D-15).
        The close of the returned ``Bar`` is the value the portfolio marks
        equity with at the tick (rule 6).
        """
        bars: dict[str, Bar] = {}
        for ticker in self._symbols:
            base = self._frames[(ticker, self._base_alias)]
            pos = int(base.index.searchsorted(time, side="left"))
            if pos < len(base.index) and base.index[pos] == time:
                bars[ticker] = Bar.from_row(time, base.iloc[pos])
        return bars

    # -- History windows (strategy push path, D-20) ---------------------------

    def window(self, ticker: str, timeframe: timedelta, max_window: int,
               asof: datetime) -> pd.DataFrame:
        """Return the last ``max_window`` COMPLETED bars visible at ``asof``.

        The completed-bars cutoff implements rule 4:
        ``cutoff = asof - timeframe + base_timeframe`` (degenerating to
        ``asof`` when ``timeframe == base_timeframe``, rule 3 — both
        branches agree, D-02); a bucket stamped ``B`` is included iff
        ``B <= cutoff``. The lookup is a pure ``searchsorted`` positional
        slice — zero resample calls on this path (M5-03).

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.
        timeframe : timedelta
            The bar timeframe of the requested window.
        max_window : int
            Maximum number of bars to return.
        asof : datetime
            The decision tick (from the BarEvent — D-20).

        Returns
        -------
        pd.DataFrame
            float64 OHLCV frame (D-17), tz-aware ``DatetimeIndex``
            preserved (SMA_MACD slices by time), completed bars only.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the feed (FR7).
        ValueError
            If ``timeframe`` maps to no supported pandas offset alias.
        """
        alias = _offset_alias(timeframe)
        frame = self._resampled_frame(ticker, alias)
        cutoff = asof - timeframe + self._base_timeframe
        pos = int(frame.index.searchsorted(cutoff, side="right"))
        return frame.iloc[max(0, pos - max_window):pos]

    # -- Multi-symbol megaframe (screener path, D-19) --------------------------

    def megaframe(self, asof: datetime, timeframe: timedelta,
                  max_window: int) -> pd.DataFrame:
        """Return a multi-symbol close-price frame visible at ``asof`` (D-19).

        Per-symbol ``window`` close columns (named by symbol) concatenated
        with ``keys`` equal to the symbols ACTUALLY included — the FR8 key
        fix (the legacy ``to_megaframe`` keyed by ``self.prices.keys()``,
        misaligning columns whenever a symbol was dropped). The legacy
        tz-naive drop condition disappears: the store normalizes every
        frame tz-aware at load. A symbol with an empty window at ``asof``
        is excluded together with its key, loudly.

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
            Close columns keyed by included symbol, tz-aware index; empty
            frame if no symbol has a visible window.
        """
        closes: list[pd.Series] = []
        included: list[str] = []
        for symbol in self._symbols:
            frame = self.window(symbol, timeframe, max_window, asof)
            if frame.empty:
                self.logger.warning(
                    'Megaframe: excluding %s — no completed bars at %s',
                    symbol, asof)
                continue
            closes.append(frame["close"].rename(symbol))
            included.append(symbol)
        if not closes:
            return pd.DataFrame()
        return pd.concat(closes, axis=1, keys=included)
