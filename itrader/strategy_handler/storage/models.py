"""Core ``Table`` definition for the signal store (OPS-03, D-04/D-05).

SQLAlchemy **Core** (not declarative ORM) — matching the existing concretes that compose
the spine (``results/models.py``'s ``build_results_tables`` and ``price_handler/store/sql_store.py``).
``build_signal_tables`` registers the single ``signals`` table on the injected
``metadata`` and is idempotent on a shared backend (reuse an already-registered table —
the same guard as ``results/models.py`` / ``sql_store.py``, D-12).

Column-type vocabulary comes from ``itrader.storage``: ``Uuid`` round-trips to a native
``uuid.UUID`` on both dialects (D-03), ``UtcIsoText`` stores business-time as ISO-8601 UTC
TEXT (D-04/D-05), and ``json_variant()`` is ``JSON`` on SQLite / ``JSONB`` on Postgres — the
ONE allowed JSON column (the ``config`` params snapshot, mirroring ``runs.settings``, D-01).
Money fields (stop_loss/take_profit/exit_fraction/quantity/entry_price) are Postgres-native
``Numeric`` (exact Decimal, OPS-04 / Pitfall 2 — money never lands on SQLite).

4-space indentation (matches the ``strategy_handler/storage/`` siblings).
"""

from sqlalchemy import (
    Column,
    MetaData,
    Numeric,
    String,
    Table,
)

from itrader.storage import Uuid, UtcIsoText, json_variant


def build_signal_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the ``signals`` table on ``metadata`` and return it.

    Parameters
    ----------
    metadata : MetaData
        The shared spine ``MetaData`` (``backend.metadata``). If ``signals`` is already
        registered, the existing ``Table`` is reused — the same shared-backend guard as
        ``results/models.py`` / ``sql_store.py`` (D-12 idempotent append).

    Returns
    -------
    dict[str, Table]
        ``{"signals": ...}``.
    """
    tables: dict[str, Table] = {}

    # signals — one row per captured SignalRecord (OPS-03). PK signal_id (UUIDv7, D-03);
    # strategy_id + ticker are INDEXED so by_strategy/by_ticker are indexed WHERE filters
    # (T-03-15 — no cross-strategy/ticker bleed). time is UtcIsoText business-time (D-04/D-05);
    # action/order_type persist as their enum ``.value`` String. Money is Postgres-native
    # Numeric exact Decimal (OPS-04). config is the ONE allowed json_variant column (D-01).
    if "signals" in metadata.tables:
        tables["signals"] = metadata.tables["signals"]
    else:
        tables["signals"] = Table(
            "signals",
            metadata,
            # WR-02 — logically-required columns carry ``nullable=False`` so the DB enforces
            # the non-null invariant the ``SignalRecord`` entity already guarantees (the
            # money columns stop_loss/take_profit/quantity/entry_price are genuinely Optional
            # and stay ``nullable=True``).
            Column("signal_id", Uuid(as_uuid=True), primary_key=True),
            Column("strategy_id", Uuid(as_uuid=True), index=True, nullable=False),
            Column("ticker", String, index=True, nullable=False),
            Column("time", UtcIsoText, nullable=False),
            Column("action", String, nullable=False),
            Column("order_type", String, nullable=False),
            Column("stop_loss", Numeric, nullable=True),
            Column("take_profit", Numeric, nullable=True),
            Column("exit_fraction", Numeric, nullable=False),
            Column("quantity", Numeric, nullable=True),
            Column("entry_price", Numeric, nullable=True),
            Column("config", json_variant(), nullable=False),
        )

    return tables
