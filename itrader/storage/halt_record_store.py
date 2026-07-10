"""Durable halt-record store — the HALTED latch that survives a process restart (D-10).

Phase 05.1 D-05 landed an IN-PROCESS ``HALTED`` latch. But a supervised auto-restart builds
a FRESH ``LiveTradingSystem`` whose in-process ``_status`` is ``STOPPED``, so a breaker-class
halt whose cause is not re-detectable at start would be silently cleared. This store puts the
latch on the shared ``SqlEngine`` spine (ARCH-4 Layer 2): ``record_halt`` persists an
unresolved record, ``has_unresolved`` / ``get_unresolved`` read it back on the next process,
and ``resolve_all`` clears it (operator ``reset_halt``). The DURABLE record is what latches
across a restart.

Secret-scrub (V7 / T-05.2-18): the schema carries ONLY the machine-readable ``reason`` literal
+ ``created_at`` timestamp + a ``resolved`` flag — deliberately NO free-form exception / payload
column, so ``str(exc)`` or a connector payload can never leak into persistence (mirrors the
``ErrorEvent`` field-bind discipline at ``halt()``).

The store *composes* a ``SqlEngine`` by reference (has-a, D-06 — never a cross-concern god
base) and registers the single ``halt_records`` table on ``backend.metadata``. It is
schema-pure (WR-03/D-14 — no runtime ``create_all``): the durable schema is Alembic-owned in
production (``d10_halt_records``) and provisioned by ``provision_schema`` in tests. All SQL is
parameterized SQLAlchemy Core against the constant ``Table`` object — never f-string SQL
(T-05.2-19 / SEC-01). The single ``id`` PK is a UUIDv7 from the shared ``idgen`` singleton (the
one ID scheme — no second scheme, no DB autoincrement). 4-space indentation (matches the
``itrader/storage`` spine layer this file sits in).
"""

import uuid
from datetime import datetime
from typing import NamedTuple, Optional

from sqlalchemy import Boolean, Column, MetaData, String, Table, insert, select, update
from sqlalchemy.engine import Engine

from itrader import idgen
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, Uuid


class HaltRecord(NamedTuple):
    """A durable halt record — the machine-readable reason literal + its timestamp.

    Deliberately carries ONLY the two secret-scrub-safe fields the schema stores (V7 /
    T-05.2-18) — no exception text, no connector payload.
    """

    reason: str
    created_at: datetime


def build_halt_records_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``halt_records`` table on ``metadata`` and return it.

    Idempotent on a shared backend (reuse an already-registered table) — the same
    shared-backend guard as ``build_portfolio_tables`` / the results store. This function is
    the SINGLE SOURCE OF TRUTH for the ``halt_records`` schema: the test-path ``create_all``
    and the deploy-path Alembic ``--autogenerate`` (``migrations/env.py`` imports it) derive
    from one definition.

    Columns (secret-scrub, V7): ``id`` (UUIDv7 PK), ``reason`` (machine-readable literal),
    ``created_at`` (deterministic UTC-isoformat business/wall timestamp), ``resolved`` (bool).
    There is deliberately NO raw-exception / payload column.
    """
    if "halt_records" in metadata.tables:
        return metadata.tables["halt_records"]
    return Table(
        "halt_records",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("reason", String, nullable=False),
        Column("created_at", UtcIsoText, nullable=False),
        Column("resolved", Boolean, nullable=False),
    )


class HaltRecordStore:
    """Durable halt-record write / read-unresolved / resolve on the shared SQL spine.

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; this store registers its one table on ``sql_engine.metadata`` but does NOT
        create it — the durable schema is Alembic-owned in production (WR-03/D-14) and
        provisioned by the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.halt_records: Table = build_halt_records_table(sql_engine.metadata)
        # WR-03/D-14 — schema-pure: register the table, never create it (Alembic-owned in
        # production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="HaltRecordStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def record_halt(self, reason: str, at: datetime) -> None:
        """Persist an UNRESOLVED durable halt record — the reason literal + timestamp ONLY.

        Binds ONLY the declared ``reason`` literal and ``created_at`` timestamp (V7 secret-scrub,
        T-05.2-18). A fresh UUIDv7 ``id`` from the shared ``idgen`` singleton (single ID scheme).
        """
        with self.engine.begin() as connection:
            connection.execute(
                insert(self.halt_records),
                [
                    {
                        "id": idgen.generate_halt_record_id(),
                        "reason": reason,
                        "created_at": at,
                        "resolved": False,
                    }
                ],
            )

    def has_unresolved(self) -> bool:
        """Whether any UNRESOLVED durable halt record exists (the restart latch)."""
        statement = (
            select(self.halt_records.c.id)
            .where(self.halt_records.c.resolved.is_(False))
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).first()
        return row is not None

    def get_unresolved(self) -> Optional[HaltRecord]:
        """The oldest UNRESOLVED durable halt record (reason literal + timestamp), or None."""
        statement = (
            select(self.halt_records.c.reason, self.halt_records.c.created_at)
            .where(self.halt_records.c.resolved.is_(False))
            .order_by(self.halt_records.c.created_at.asc())
            .limit(1)
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return HaltRecord(reason=row["reason"], created_at=row["created_at"])

    def resolve_all(self) -> None:
        """Resolve every unresolved durable halt record (operator ``reset_halt`` clear)."""
        with self.engine.begin() as connection:
            connection.execute(
                update(self.halt_records)
                .where(self.halt_records.c.resolved.is_(False))
                .values(resolved=True)
            )
