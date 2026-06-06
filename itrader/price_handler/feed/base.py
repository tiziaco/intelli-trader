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
from datetime import datetime, timedelta

import pandas as pd

from itrader.core.bar import Bar


class BarFeed(ABC):
    """Abstract base class for the per-tick market-data read model (M5-05).

    Serves current-bar facts, completed-bars-only history windows, and the
    multi-symbol megaframe. Backtest implementation: ``BacktestBarFeed``
    (precompute + slice); a live feed lands with D-live.
    """

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
