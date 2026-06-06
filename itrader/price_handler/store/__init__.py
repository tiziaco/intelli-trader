"""Price store package (M5-05, D-16) — canonical OHLCV storage seam.

Re-exports the ``PriceStore`` ABC. The quarantined SQL backend
(``sql_store``) is deliberately NOT imported at package level — it pulls
sqlalchemy/psycopg2 and belongs to the deferred persistence milestone (D-sql).
"""

from .base import PriceStore

__all__ = [
    'PriceStore',
]
