"""Durable strategy registry — a name-keyed registry + normalized subscriptions (STORE-03).

TWO tables on the shared ``SqlEngine`` spine (D-04 / D-06):

* ``strategy_registry`` — one row per strategy, keyed on the NATURAL ``strategy_name`` PK
  (config + enabled flag + updated_at). The durable identity is the strategy NAME, never the
  ephemeral runtime ``strategy_id`` UUIDv7: that id is minted per-construction
  (``strategy_handler/base.py``) and is NOT restart-stable, so persisting/keying on it would
  corrupt rehydrate across a restart. ``STRATEGY_COMMAND`` addresses strategies by name.
* ``strategy_subscriptions`` — a normalized child, ``strategy_name`` FK'd on
  ``strategy_registry.strategy_name``, with a natural composite PK
  ``(strategy_name, venue, symbol, timeframe)`` — no surrogate UUID, no autoincrement (D-06
  spirit / RESEARCH A3). Rehydrate JOINs both.

A disciplined clone of the ``HaltRecordStore`` template (STORE-04 / D-01), with the
multi-table registrar shape of ``build_order_tables``: composes ``SqlEngine`` by reference,
owns ``build_strategy_registry_tables`` (single source of truth for BOTH the test-path
``create_all`` and Plan 04-03's ``migrations/env.py``), schema-pure (WR-03/D-14 — no runtime
``create_all``; Alembic-owned in production, ``provision_schema`` in tests), caller-supplied
``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only (SEC-01 / T-04-02).
4-space indentation (matches the ``itrader/storage`` spine layer).
"""

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, json_variant

# A subscription is a (venue, symbol, timeframe) triple — the normalized child row shape.
Subscription = tuple[str, str, str]


def build_strategy_registry_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the registry + subscriptions tables on ``metadata``.

    Per-table idempotency guards on a shared backend (reuse an already-registered table) —
    the same shape as ``build_order_tables``. Single source of truth for BOTH tables' schema
    feeding the test-path ``create_all`` and the Plan 04-03 Alembic autogenerate.

    Returns ``{"strategy_registry": ..., "strategy_subscriptions": ...}``.
    """
    tables: dict[str, Table] = {}

    if "strategy_registry" in metadata.tables:
        tables["strategy_registry"] = metadata.tables["strategy_registry"]
    else:
        tables["strategy_registry"] = Table(
            "strategy_registry",
            metadata,
            # Natural NAME PK (D-06) — NOT the ephemeral runtime strategy_id UUID.
            Column("strategy_name", String, primary_key=True),
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )

    if "strategy_subscriptions" in metadata.tables:
        tables["strategy_subscriptions"] = metadata.tables["strategy_subscriptions"]
    else:
        tables["strategy_subscriptions"] = Table(
            "strategy_subscriptions",
            metadata,
            # FK back to the registry natural name key; part of the composite PK.
            Column(
                "strategy_name",
                String,
                ForeignKey("strategy_registry.strategy_name"),
                primary_key=True,
                nullable=False,
            ),
            Column("venue", String, primary_key=True, nullable=False),
            Column("symbol", String, primary_key=True, nullable=False),
            Column("timeframe", String, primary_key=True, nullable=False),
        )

    return tables


class StrategyRegistryStore:
    """Name-keyed strategy registry + normalized subscriptions on the shared SQL spine.

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is config-selected at wiring;
        this store registers its two tables on ``sql_engine.metadata`` but does NOT create
        them — the durable schema is Alembic-owned in production (WR-03/D-14) and provisioned
        by the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        tables = build_strategy_registry_tables(sql_engine.metadata)
        self.strategy_registry: Table = tables["strategy_registry"]
        self.strategy_subscriptions: Table = tables["strategy_subscriptions"]
        # WR-03/D-14 — schema-pure: register the tables, never create them (Alembic-owned
        # in production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="StrategyRegistryStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(
        self, strategy_name: str, config: dict[str, Any], enabled: bool, at: datetime
    ) -> None:
        """Persist (or overwrite) a strategy's config + enabled flag with ``updated_at`` ``at``.

        Portable update-in-place-or-insert on the REGISTRY table in ONE transaction. The
        parent row is UPDATED (never deleted) when it already exists: deleting it would
        violate the ``strategy_subscriptions`` FK once child rows exist — the live re-config
        path ``upsert`` → ``set_subscriptions`` → ``upsert`` — which the SQLite
        ``PRAGMA foreign_keys=ON`` hook (WR-02) now enforces on both dialects (CR-01).
        Subscriptions are managed separately via ``set_subscriptions``. Parameterized Core
        (SEC-01).
        """
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(self.strategy_registry)
                .where(self.strategy_registry.c.strategy_name == strategy_name)
                .values(enabled=enabled, config_json=config, updated_at=at)
            )
            if updated.rowcount == 0:
                connection.execute(
                    insert(self.strategy_registry),
                    [
                        {
                            "strategy_name": strategy_name,
                            "enabled": enabled,
                            "config_json": config,
                            "updated_at": at,
                        }
                    ],
                )

    def set_subscriptions(
        self,
        strategy_name: str,
        subscriptions: Sequence[Subscription],
        at: datetime,
    ) -> None:
        """Replace-all the subscription set for ``strategy_name`` and touch its ``updated_at``.

        Deletes every existing child row for the strategy then inserts the new set in ONE
        transaction, and bumps the parent registry ``updated_at`` to ``at`` so the row's
        timestamp reflects the latest mutation (config or subscriptions). Parameterized Core.
        """
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.strategy_subscriptions).where(
                    self.strategy_subscriptions.c.strategy_name == strategy_name
                )
            )
            if subscriptions:
                connection.execute(
                    insert(self.strategy_subscriptions),
                    [
                        {
                            "strategy_name": strategy_name,
                            "venue": venue,
                            "symbol": symbol,
                            "timeframe": timeframe,
                        }
                        for (venue, symbol, timeframe) in subscriptions
                    ],
                )
            connection.execute(
                update(self.strategy_registry)
                .where(self.strategy_registry.c.strategy_name == strategy_name)
                .values(updated_at=at)
            )

    def get(self, strategy_name: str) -> Optional[Mapping[str, Any]]:
        """The registry row for ``strategy_name`` (config/enabled/updated_at), or None."""
        statement = select(
            self.strategy_registry.c.strategy_name,
            self.strategy_registry.c.enabled,
            self.strategy_registry.c.config_json,
            self.strategy_registry.c.updated_at,
        ).where(self.strategy_registry.c.strategy_name == strategy_name)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return {
            "strategy_name": row["strategy_name"],
            "config": row["config_json"],
            "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"],
        }

    def delete(self, strategy_name: str) -> None:
        """Remove a strategy — subscriptions FIRST (FK child order), then the registry row."""
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.strategy_subscriptions).where(
                    self.strategy_subscriptions.c.strategy_name == strategy_name
                )
            )
            connection.execute(
                delete(self.strategy_registry).where(
                    self.strategy_registry.c.strategy_name == strategy_name
                )
            )

    def list_active(self) -> list[Mapping[str, Any]]:
        """Every registry row with ``enabled=True`` — the typed-column query (D-09)."""
        statement = select(
            self.strategy_registry.c.strategy_name,
            self.strategy_registry.c.enabled,
            self.strategy_registry.c.config_json,
            self.strategy_registry.c.updated_at,
        ).where(self.strategy_registry.c.enabled.is_(True))
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "strategy_name": row["strategy_name"],
                "config": row["config_json"],
                "enabled": bool(row["enabled"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def strategies_subscribed_to(self, symbol: str) -> list[str]:
        """Distinct strategy names subscribing to ``symbol`` (subscription lookup, D-09)."""
        statement = (
            select(self.strategy_subscriptions.c.strategy_name)
            .where(self.strategy_subscriptions.c.symbol == symbol)
            .distinct()
            .order_by(self.strategy_subscriptions.c.strategy_name.asc())
        )
        with self.engine.connect() as connection:
            names = connection.execute(statement).scalars().all()
        return list(names)

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every strategy with its subscriptions — the FK-join rehydrate (D-04).

        LEFT OUTER JOIN so a strategy with no subscriptions still appears; grouped by
        ``strategy_name`` in Python into one record per strategy.
        """
        join = self.strategy_registry.outerjoin(
            self.strategy_subscriptions,
            self.strategy_registry.c.strategy_name
            == self.strategy_subscriptions.c.strategy_name,
        )
        statement = (
            select(
                self.strategy_registry.c.strategy_name,
                self.strategy_registry.c.enabled,
                self.strategy_registry.c.config_json,
                self.strategy_registry.c.updated_at,
                self.strategy_subscriptions.c.venue,
                self.strategy_subscriptions.c.symbol,
                self.strategy_subscriptions.c.timeframe,
            )
            .select_from(join)
            # IN-01 — deterministic rehydrate order. strategy_name ASC drives the RECORD
            # order (records dict is populated in row order), and (venue, symbol, timeframe)
            # ASC drives each record's subscription-list append order. Mirrors the .asc()
            # idiom in strategies_subscribed_to. Guards future golden/byte-exact callers.
            .order_by(
                self.strategy_registry.c.strategy_name.asc(),
                self.strategy_subscriptions.c.venue.asc(),
                self.strategy_subscriptions.c.symbol.asc(),
                self.strategy_subscriptions.c.timeframe.asc(),
            )
        )

        records: dict[str, dict[str, Any]] = {}
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        for row in rows:
            name = row["strategy_name"]
            record = records.get(name)
            if record is None:
                record = {
                    "strategy_name": name,
                    "config": row["config_json"],
                    "enabled": bool(row["enabled"]),
                    "updated_at": row["updated_at"],
                    "subscriptions": [],
                }
                records[name] = record
            # An outer-join row with no matching child has NULL subscription columns.
            if row["venue"] is not None:
                record["subscriptions"].append(
                    (row["venue"], row["symbol"], row["timeframe"])
                )
        return list(records.values())
