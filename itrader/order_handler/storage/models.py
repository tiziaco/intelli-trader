"""Core ``Table`` definitions for the order-mirror store (OPS-01, D-01/D-02/D-08).

SQLAlchemy **Core** (not declarative ORM) — mirroring ``itrader/results/models.py``'s
``build_results_tables`` idempotent registrar. ``build_order_tables`` registers the two
order tables on the injected ``backend.metadata`` and is idempotent on a shared backend
(reuse an already-registered table, the same guard as ``results/models.py`` / ``sql_store.py``).

The ``orders`` table maps every ``Order`` field (``order_handler/order.py::Order``) to a
column EXCEPT ``child_order_ids`` — that ``List[OrderId]`` is NOT a column (D-02); it is
derived on read by querying ``parent_order_id`` (Pitfall 6). Brackets persist via the
nullable, indexed, self-referential ``parent_order_id`` FK (D-02). ``state_changes`` (a
``List[OrderStateChange]``) lands in the ``order_state_changes`` child table (load-bearing
for the D-10 field-wise ``Order.__eq__`` round-trip).

Column-type vocabulary comes from ``itrader.storage`` (``Uuid`` round-trips to a native
``uuid.UUID`` on both dialects, D-03; ``UtcIsoText`` is deterministic UTC-isoformat business
time, D-04; ``json_variant()`` is ``JSON`` on SQLite / ``JSONB`` on Postgres). Money is
``sqlalchemy.Numeric`` imported direct (asdecimal, unbounded) — there is deliberately NO
money TypeDecorator on the spine (D-13). 4-space indentation (matches the existing
``order_handler/storage`` siblings + the ``results`` analog).
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)

from itrader.storage import Uuid, UtcIsoText, json_variant


def build_order_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the two order tables on ``metadata`` and return them.

    Parameters
    ----------
    metadata : MetaData
        The shared spine ``MetaData`` (``backend.metadata``). If a table name is already
        registered, the existing ``Table`` is reused — the same shared-backend guard as
        ``results/models.py`` (idempotent append on a shared backend).

    Returns
    -------
    dict[str, Table]
        ``{"orders": ..., "order_state_changes": ...}``.
    """
    tables: dict[str, Table] = {}

    # orders — one row per Order (OPS-01). The column map is the verbatim Order field list
    # (order.py:46-108) minus child_order_ids (D-02 — derived on read). The self-referential
    # parent_order_id FK declares brackets (D-02); the (portfolio_id, status) composite index
    # (D-08) serves the hot active-set queries.
    if "orders" in metadata.tables:
        tables["orders"] = metadata.tables["orders"]
    else:
        tables["orders"] = Table(
            "orders",
            metadata,
            # WR-02 — logically-required columns carry ``nullable=False`` so the DB enforces
            # the same non-null invariant the ``Order`` entity already guarantees (defense in
            # depth; a partial write / buggy caller can no longer persist a NULL that would
            # later crash ``_row_to_order`` on e.g. ``OrderType(None)``). The genuinely-optional
            # lifecycle columns below stay ``nullable=True``.
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("time", UtcIsoText, nullable=False),
            Column("type", String, nullable=False),
            Column("status", String, nullable=False),
            Column("ticker", String, nullable=False),
            Column("action", String, nullable=False),
            Column("price", Numeric, nullable=False),
            Column("quantity", Numeric, nullable=False),
            Column("exchange", String, nullable=False),
            Column("strategy_id", Uuid(as_uuid=True), nullable=False),
            Column("portfolio_id", Uuid(as_uuid=True), nullable=False),
            Column("filled_quantity", Numeric, nullable=False),
            Column("created_at", UtcIsoText, nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
            Column("filled_at", UtcIsoText, nullable=True),
            Column("cancelled_at", UtcIsoText, nullable=True),
            Column("expired_at", UtcIsoText, nullable=True),
            Column("expiry_time", UtcIsoText, nullable=True),
            # D-02 — nullable, indexed, self-referential bracket FK. child_order_ids is
            # NOT a column; it is rebuilt on read from this FK (Pitfall 6).
            # WR-01 — ``ondelete="SET NULL"`` so deleting a bracket PARENT orphans its
            # children cleanly instead of raising Postgres FK-RESTRICT ``IntegrityError``
            # (the delete paths filter to ACTIVE orders, so a terminal child can still
            # reference an about-to-be-deleted active parent).
            Column(
                "parent_order_id",
                Uuid(as_uuid=True),
                ForeignKey("orders.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            Column("rejection_reason", String, nullable=True),
            Column("modification_count", Integer, nullable=False),
            Column("last_modification_time", UtcIsoText, nullable=True),
            Column("leverage", Numeric, nullable=False),
            Column("trail_type", String, nullable=True),
            Column("trail_value", Numeric, nullable=True),
            # 05-07 (RECON-05 / Open Question 3) — the venue order id, nullable so
            # backtest/paper orders (no venue id) round-trip unchanged. Persisted so a
            # rehydrated bracket leg re-links confidently to a venue resting order.
            Column("venue_order_id", String, nullable=True),
            # D-08 — composite index over the hot active-set predicate (portfolio_id, status).
            Index("ix_orders_portfolio_status", "portfolio_id", "status"),
        )

    # order_state_changes — the OrderStateChange audit trail child table (D-10). Composite
    # PK (order_id, seq) preserves the per-order transition order; order_id FKs orders.id.
    # additional_data is the one JSON column (json_variant) — NULL when the change carries
    # no extra payload.
    if "order_state_changes" in metadata.tables:
        tables["order_state_changes"] = metadata.tables["order_state_changes"]
    else:
        tables["order_state_changes"] = Table(
            "order_state_changes",
            metadata,
            Column(
                "order_id",
                Uuid(as_uuid=True),
                ForeignKey("orders.id"),
                primary_key=True,
            ),
            Column("seq", Integer, primary_key=True),
            # WR-02 — from_status is genuinely Optional (a brand-new order has no prior
            # status); the rest are non-null on every OrderStateChange.
            Column("from_status", String, nullable=True),
            Column("to_status", String, nullable=False),
            Column("timestamp", UtcIsoText, nullable=False),
            Column("reason", String, nullable=False),
            Column("triggered_by", String, nullable=False),
            Column("additional_data", json_variant(), nullable=True),
        )

    return tables
