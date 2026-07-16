"""Durable append-only engine-operational stats series (RTCFG-06, D-17/D-18).

``system_stats`` is the ONE new durable table this phase's read-model needs: an
append-only time-series of the engine-operational counters that no domain store owns —
the P7 throttle-breach counter, error counts by severity, event-bus queue depth, uptime,
and connector/stream health. It deliberately holds NOTHING a domain store already
persists (D-17 — NO entity duplication): portfolio equity/positions come from
``portfolio_account_state``/``equity_snapshots``, orders from the order store, halts from
``halt_records``. A UI reader (the future FastAPI layer) reads all of these — plus the
``state.*`` KV in ``SystemStore`` — as plain lock-free DB reads, no aggregation layer.

The table clones the ``equity_snapshots`` append-only shape (D-18): a ``seq`` Integer PK
with ``autoincrement=False`` — the engine writes the monotonic seq, not the DB, so the
single-UUIDv7 / no-second-ID-scheme rule holds — plus a ``UtcIsoText`` business
``timestamp`` (never wall-clock; the caller supplies ``at``, D-07). The store itself is a
disciplined clone of the ``SystemStore`` template: it *composes* a ``SqlEngine`` by
reference (has-a), owns its ``build_system_stats_table`` registrar (the single source of
truth feeding BOTH the test-path ``create_all`` and ``migrations/env.py``
``target_metadata``), and is schema-pure (WR-03/D-14 — it registers the table but never
runs ``create_all``: production schema is Alembic-owned, tests provision via
``provision_schema``). All SQL is parameterized SQLAlchemy Core against the constant
``Table`` object — never f-string SQL (SEC-01). Reads use a plain lock-free
``engine.connect()`` (RTCFG-06 — a UI read can never stall the engine thread's hot path).

Only NON-sensitive engine-operational counters are stored here (V7 / T-9-stats-secret):
no credential, no PII, no domain-entity data. 4-space indentation (matches the
``itrader/storage`` spine layer this file sits in).
"""

from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    Numeric,
    Table,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText

# The minimal engine-operational counter set (D-18 — extensible; start minimal). These
# are the counters the engine already holds in memory and that NO domain store owns.
_COUNTER_COLUMNS: tuple[str, ...] = (
    "throttle_breach_count",
    "error_count_warning",
    "error_count_error",
    "error_count_critical",
    "queue_depth",
    "uptime_seconds",
    "connector_up",
    "stream_up",
)


def build_system_stats_table(metadata: MetaData) -> Table:
    """Register (idempotently) the single ``system_stats`` table on ``metadata`` and return it.

    Idempotent on a shared backend (reuse an already-registered table) — the same
    shared-backend guard as ``build_system_store_table`` / ``build_order_config_table``.
    This function is the SINGLE SOURCE OF TRUTH for the ``system_stats`` schema: the
    test-path ``create_all`` and the deploy-path Alembic ``--autogenerate``
    (``migrations/env.py``) derive from one definition.

    Columns clone the ``equity_snapshots`` append-only shape (D-18): a ``seq`` Integer PK
    with ``autoincrement=False`` (the engine writes seq — no second ID scheme), a
    ``timestamp`` ``UtcIsoText`` business time (D-07), and the minimal engine-operational
    counter set. ``uptime_seconds`` is ``Numeric`` (Decimal end-to-end); the health flags
    are ``Boolean``.
    """
    if "system_stats" in metadata.tables:
        return metadata.tables["system_stats"]
    return Table(
        "system_stats",
        metadata,
        Column("seq", Integer, primary_key=True, autoincrement=False),
        Column("timestamp", UtcIsoText, nullable=False),
        Column("throttle_breach_count", Integer, nullable=False),
        Column("error_count_warning", Integer, nullable=False),
        Column("error_count_error", Integer, nullable=False),
        Column("error_count_critical", Integer, nullable=False),
        Column("queue_depth", Integer, nullable=False),
        Column("uptime_seconds", Numeric, nullable=False),
        Column("connector_up", Boolean, nullable=False),
        Column("stream_up", Boolean, nullable=False),
    )


class SystemStatsStore:
    """Append-only engine-operational stats series on the shared SQL spine (D-18).

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
        self.system_stats: Table = build_system_stats_table(sql_engine.metadata)
        # WR-03/D-14 — schema-pure: the constructor registers the table but never creates
        # it. Production live Postgres is Alembic-owned end-to-end; tests provision
        # explicitly via tests.support.schema.provision_schema.
        self.logger = get_itrader_logger().bind(component="SystemStatsStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def append(self, row: Mapping[str, Any], at: datetime) -> int:
        """Append one counter ``row`` stamped ``at`` (the engine writes the next ``seq``).

        The engine assigns the monotonic ``seq`` (``max(seq) + 1`` in the same
        transaction — no DB autoincrement, no second ID scheme), so the append is a
        SELECT-max-then-INSERT in ONE ``engine.begin()``. ``row`` supplies the counter
        columns; ``at`` is the caller-supplied business timestamp (D-07 — clock-free
        store). Parameterized Core against the constant ``Table`` — never f-string SQL.

        Returns the assigned ``seq``.
        """
        payload = {name: row[name] for name in _COUNTER_COLUMNS}
        with self.engine.begin() as connection:
            current_max = connection.execute(
                select(func.max(self.system_stats.c.seq))
            ).scalar()
            next_seq = 0 if current_max is None else int(current_max) + 1
            payload["seq"] = next_seq
            payload["timestamp"] = at
            connection.execute(insert(self.system_stats), [payload])
        return next_seq

    def read_recent(self, n: int) -> list[Mapping[str, Any]]:
        """The ``n`` most-recent rows, newest first (lock-free read — RTCFG-06).

        A plain ``engine.connect()`` read ordered by ``seq`` descending — no hot-path lock
        is touched, so a UI read can never stall the engine thread.
        """
        statement = (
            select(self.system_stats)
            .order_by(self.system_stats.c.seq.desc())
            .limit(n)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every row in stable ``seq`` order (chronological) — the rehydrate read.

        Lock-free ``engine.connect()`` read ordered by ``seq`` ascending (RTCFG-06).
        """
        statement = select(self.system_stats).order_by(self.system_stats.c.seq.asc())
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [dict(row) for row in rows]
