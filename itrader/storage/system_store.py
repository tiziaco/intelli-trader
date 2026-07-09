"""Durable system KV store — the cardinality-1 runtime-config spine (STORE-01, D-06/D-08).

A namespaced key/value store on the shared ``SqlEngine`` spine: ``upsert(key, value, at)``
persists (or overwrites) one JSON blob per natural ``key``, ``get(key)`` reads it back,
``delete(key)`` removes it, and ``read_all()`` rehydrates every row. The durable identity is
the NATURAL ``key`` string (D-06) — deliberately NOT a UUIDv7 surrogate: this store keys on
caller-meaningful names (e.g. ``"runtime_config"``), so ``idgen`` is never imported and there
is no DB autoincrement. Cardinality-1 semantics come from the ``key`` PK: two upserts on the
same key leave ONE row.

A disciplined clone of the ``HaltRecordStore`` template (STORE-04 / D-01): it *composes* a
``SqlEngine`` by reference (has-a — never a cross-concern god base), owns its
``build_system_store_table`` registrar (the single source of truth feeding BOTH this store's
``create_all`` and Plan 04-03's ``migrations/env.py`` ``target_metadata``), and calls
``create_all(checkfirst=True)`` so schema creation is idempotent (the live path migrates via
Alembic; ``create_all`` is the test / no-op-if-present path). All SQL is parameterized
SQLAlchemy Core against the constant ``Table`` object — never f-string SQL (SEC-01 /
T-04-02). The upsert is a portable delete-then-insert in one ``engine.begin()`` transaction.
The caller supplies ``at`` (D-07 — clock-free store) stored via ``UtcIsoText``. 4-space
indentation (matches the ``itrader/storage`` spine layer this file sits in).
"""

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import Column, MetaData, String, Table, delete, insert, select
from sqlalchemy.engine import Engine

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant


def build_system_store_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``system_store`` table on ``metadata`` and return it.

    Idempotent on a shared backend (reuse an already-registered table) — the same
    shared-backend guard as ``build_halt_records_table`` / ``build_order_tables``. This
    function is the SINGLE SOURCE OF TRUTH for the ``system_store`` schema: the test-path
    ``create_all`` and the deploy-path Alembic ``--autogenerate`` (``migrations/env.py`` in
    Plan 04-03) derive from one definition.

    Columns: ``key`` (natural String PK — D-06, NOT a UUIDv7 surrogate), ``value_json``
    (portable JSON blob — D-08), ``updated_at`` (deterministic UTC-isoformat business
    timestamp — D-07).
    """
    if "system_store" in metadata.tables:
        return metadata.tables["system_store"]
    return Table(
        "system_store",
        metadata,
        Column("key", String, primary_key=True),
        Column("value_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )


class SystemStore:
    """Namespaced KV upsert / get / delete / read-all on the shared SQL spine.

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is selected by config at
        wiring; this store registers its one table on ``sql_engine.metadata`` and creates it
        idempotently (``checkfirst=True``).
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.system_store: Table = build_system_store_table(sql_engine.metadata)
        # Idempotent, ephemeral-friendly schema creation (the live path migrates via
        # Alembic; create_all is the test / no-op-if-present path).
        sql_engine.metadata.create_all(self.engine, checkfirst=True)
        self.logger = get_itrader_logger().bind(component="SystemStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(self, key: str, value: dict[str, Any], at: datetime) -> None:
        """Persist (or overwrite) the JSON ``value`` under ``key`` with the ``updated_at`` ``at``.

        Portable delete-then-insert in ONE transaction (SQLite has no native
        ``INSERT ... ON CONFLICT`` parity across every dialect we target), so a second upsert
        on the same key leaves ONE row (cardinality-1 by the ``key`` PK). Parameterized Core
        against the constant ``Table`` — never f-string SQL (SEC-01).
        """
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.system_store).where(self.system_store.c.key == key)
            )
            connection.execute(
                insert(self.system_store),
                [{"key": key, "value_json": value, "updated_at": at}],
            )

    def get(self, key: str) -> Optional[Mapping[str, Any]]:
        """The ``{"key", "value", "updated_at"}`` row for ``key``, or None when absent."""
        statement = select(
            self.system_store.c.key,
            self.system_store.c.value_json,
            self.system_store.c.updated_at,
        ).where(self.system_store.c.key == key)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return {
            "key": row["key"],
            "value": row["value_json"],
            "updated_at": row["updated_at"],
        }

    def delete(self, key: str) -> None:
        """Remove the row for ``key`` (no-op when absent)."""
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.system_store).where(self.system_store.c.key == key)
            )

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every ``{"key", "value", "updated_at"}`` row — the rehydrate read."""
        statement = select(
            self.system_store.c.key,
            self.system_store.c.value_json,
            self.system_store.c.updated_at,
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "key": row["key"],
                "value": row["value_json"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
