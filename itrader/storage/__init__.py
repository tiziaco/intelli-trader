"""The shared SQL spine package (D-01).

A domain-neutral home that every storage concern *composes* — ``SqlBackend`` (Engine +
MetaData, no business logic) plus the cross-dialect ``types`` helpers (``UtcIsoText``,
``json_variant``, and the ``Uuid`` usage). Like ``price_handler/store``, the quarantined
SQL-heavy ``sql_store`` backend is deliberately NOT imported at package level, so the
backtest import path stays SQL-free (GATE-01 inertness).
"""

from itrader.storage.backend import SqlBackend
from itrader.storage.types import UtcIsoText, Uuid, UuidType, json_variant

__all__ = [
    "SqlBackend",
    "UtcIsoText",
    "Uuid",
    "UuidType",
    "json_variant",
]
