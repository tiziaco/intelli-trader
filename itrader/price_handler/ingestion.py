"""Offline ingestion entry point (M5-05, FR6) — provider -> store pipeline stub.

Contract: for each symbol, ``provider.fetch_ohlcv(symbol, timeframe, start,
end)`` returns a canonical OHLCV frame which is persisted via
``store.write_bars(symbol, frame)``. This formalizes the legacy
``data_provider.load_data`` non-csv loop (download-then-persist) behind the
Provider/Store seams.

FR6: ingestion NEVER runs inside the trading loop. It is a batch, offline
process — the run path constructs only a read-only ``PriceStore`` and never
imports this module or any provider adapter.

Deferred: the real pipeline (and its CLI) lands with the persistence
milestone (D-sql); until then this stub raises loudly.
"""

from .providers.base import PriceProvider
from .store.base import PriceStore


def ingest(provider: PriceProvider, store: PriceStore, symbols: list[str],
           timeframe: str, start: str, end: str | None = None) -> None:
    """Fetch OHLCV bars for each symbol from a provider and persist them.

    Parameters
    ----------
    provider : PriceProvider
        The offline data source (``fetch_ohlcv`` per symbol).
    store : PriceStore
        The persistence target (``write_bars`` per symbol).
    symbols : list[str]
        The ticker symbols to ingest.
    timeframe : str
        The bar timeframe, e.g. ``'1d'``.
    start : str
        Start date (inclusive) of the ingestion window.
    end : str, optional
        End date (inclusive); ``None`` means up to the latest available bar.

    Raises
    ------
    NotImplementedError
        Always — the offline ingestion pipeline is deferred (D-sql).
    """
    raise NotImplementedError(
        "offline ingestion pipeline — deferred to the persistence milestone (D-sql)")
