"""Price-handler package (M5-05, D-16/D-18) — the Provider/Store/Feed seams.

The legacy monolithic price handler (``data_provider.py``) was split and
deleted in Plan 06-05 (D-18). The package now re-exports the three seams:

* ``PriceStore`` / ``CsvPriceStore`` — canonical OHLCV storage (read-only on
  the run path, FR6; loud typed errors, FR7).
* ``BarFeed`` / ``BacktestBarFeed`` — the look-ahead-safe per-tick read model
  (the bar-timing contract lives in ``feed.bar_feed``).
* ``PriceProvider`` — the offline data-fetch seam (ingestion only).

Quarantined modules (``store.sql_store``, the provider adapters under
``providers/``) are deliberately NOT imported at package level — they pull
heavy/optional dependencies and belong to deferred subsystems (D-sql /
D-oanda / D-live).
"""

from .feed import BacktestBarFeed, BarFeed
from .providers import PriceProvider
from .store import CsvPriceStore, PriceStore

__all__ = [
    'PriceStore',
    'CsvPriceStore',
    'BarFeed',
    'BacktestBarFeed',
    'PriceProvider',
]
