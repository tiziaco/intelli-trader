"""Store seam for the price-handler split (M5-05, D-16).

A ``PriceStore`` owns the canonical OHLCV frames the engine reads: tz-aware
``DatetimeIndex`` named ``'date'`` with float64 ``open/high/low/close/volume``
columns. The run path is READ-ONLY (FR6): the trading loop only ever calls
the read accessors; ``write_bars`` is the offline ingestion surface
(provider -> store, see ``itrader.price_handler.ingestion``).

FR7 — loud typed errors, never silent ``None``: every read accessor raises
``MissingPriceDataError`` for unknown tickers / unusable data instead of
returning ``None``. This replaces the bare-``except:``-then-``return None``
defect in the legacy ``data_provider.py`` accessors, which silently turned
data gaps into downstream ``NoneType`` corruption.
"""

from abc import ABC, abstractmethod

import pandas as pd


class PriceStore(ABC):
    """Abstract base class for canonical OHLCV price storage (M5-05, D-16).

    Provides a unified read interface for the trading run path (backtest CSV
    store now; SQL-backed store with the persistence milestone, D-sql) plus a
    single write surface reserved for offline ingestion (FR6).
    """

    # -- Read accessors (run path — raise, never return None: FR7) -----------

    @abstractmethod
    def read_bars(self, ticker: str) -> pd.DataFrame:
        """Return the full canonical OHLCV frame for a ticker.

        Parameters
        ----------
        ticker : str
            The ticker symbol, e.g. ``'BTCUSD'``.

        Returns
        -------
        pd.DataFrame
            Canonical frame: tz-aware ``DatetimeIndex`` named ``'date'``,
            float64 ``open/high/low/close/volume`` columns.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the store (FR7 — never ``None``).
        """
        pass

    @abstractmethod
    def has(self, ticker: str) -> bool:
        """Return whether the store holds bars for a ticker.

        Parameters
        ----------
        ticker : str
            The ticker symbol to check.

        Returns
        -------
        bool
            ``True`` if the ticker is served by this store.
        """
        pass

    @abstractmethod
    def symbols(self) -> list[str]:
        """Return all tickers served by this store.

        Returns
        -------
        list[str]
            The loaded ticker symbols.
        """
        pass

    @abstractmethod
    def index(self, ticker: str) -> pd.DatetimeIndex:
        """Return the bar index for a ticker (feeds ``TimeGenerator.set_dates``).

        Parameters
        ----------
        ticker : str
            The ticker symbol whose bar timestamps are requested.

        Returns
        -------
        pd.DatetimeIndex
            The tz-aware bar index of the ticker's canonical frame.

        Raises
        ------
        MissingPriceDataError
            If the ticker is unknown to the store (FR7 — never ``None``).
        """
        pass

    # -- Write surface (offline ingestion only — FR6) ------------------------

    @abstractmethod
    def write_bars(self, ticker: str, frame: pd.DataFrame) -> None:
        """Persist a canonical OHLCV frame for a ticker.

        Offline ingestion surface (provider -> store). Read-only stores on
        the run path raise ``NotImplementedError`` (FR6).

        Parameters
        ----------
        ticker : str
            The ticker symbol the frame belongs to.
        frame : pd.DataFrame
            The canonical OHLCV frame to persist.
        """
        pass
