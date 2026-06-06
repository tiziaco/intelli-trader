"""Provider seam for the price-handler split (M5-05, D-16).

A ``PriceProvider`` fetches raw OHLCV data from an external source (exchange
API, broker, streaming endpoint) so it can be written into a ``PriceStore``
by the offline ingestion pipeline (``itrader.price_handler.ingestion``).

Offline only — never imported on the run path (FR6). The trading loop reads
exclusively from a ``PriceStore``; network code is physically unreachable
from the backtest/live event loop. The dormant CCXT/OANDA/Binance adapters
quarantined in this package (D-21) will be adapted to this contract when the
persistence milestone (D-sql) revives ingestion.
"""

from abc import ABC, abstractmethod

import pandas as pd


class PriceProvider(ABC):
    """Abstract base class for offline OHLCV data providers (M5-05, FR6).

    Implementations wrap an external data source and return canonical OHLCV
    frames for the ingestion pipeline to persist via ``PriceStore.write_bars``.
    Providers are NEVER constructed or imported on the trading run path.
    """

    # -- Data fetch (offline ingestion surface) ------------------------------

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, start: str,
                    end: str | None = None) -> pd.DataFrame:
        """Fetch OHLCV bars for a symbol over a date window.

        Parameters
        ----------
        symbol : str
            The ticker symbol, e.g. ``'BTCUSD'``.
        timeframe : str
            The bar timeframe, e.g. ``'1d'``.
        start : str
            Start date (inclusive) of the requested window.
        end : str, optional
            End date (inclusive) of the requested window; ``None`` means
            "up to the latest available bar".

        Returns
        -------
        pd.DataFrame
            Canonical OHLCV frame: tz-aware ``DatetimeIndex`` named ``'date'``
            with float64 ``open/high/low/close/volume`` columns.
        """
        pass

    # -- Symbol discovery -----------------------------------------------------

    @abstractmethod
    def get_symbols(self) -> list[str]:
        """Return the symbols this provider can serve.

        Returns
        -------
        list[str]
            The tradable/downloadable symbols exposed by the source.
        """
        pass
