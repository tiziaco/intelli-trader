"""Price providers package (M5-05, D-16) — offline data-fetch seam.

Re-exports the ``PriceProvider`` ABC ONLY. The quarantined adapters
(``ccxt_provider``, ``oanda_provider``, ``binance_stream``, ``exchange_base``)
are deliberately NOT imported at package level — they pull heavy/optional
dependencies (ccxt, tpqoa, websocket, sqlalchemy) and belong to deferred
subsystems (D-oanda/D-live). Ingestion callers import them lazily.
"""

from .base import PriceProvider

__all__ = [
    'PriceProvider',
]
