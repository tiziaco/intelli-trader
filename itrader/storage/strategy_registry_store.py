"""Durable strategy registry — the instance registry + portfolio fan-out edge (STRAT-01).

TWO tables on the shared ``SqlEngine`` spine (D-06 / D-18):

* ``strategy_registry`` — one row per strategy INSTANCE, keyed on the NATURAL
  ``strategy_name`` PK (``strategy_type`` + ``config_json`` + ``enabled`` + ``updated_at``).
  The durable identity is the strategy NAME, never the ephemeral runtime ``strategy_id``
  UUIDv7 (D-02): that id is minted per-construction (``strategy_handler/base.py``) and is NOT
  restart-stable, so persisting/keying on it would corrupt rehydrate across a restart.
  ``STRATEGY_COMMAND`` addresses strategies by name. ``strategy_type`` is the catalog key
  rehydrate resolves (``catalog[rec["strategy_type"]]`` → the class to instantiate, D-01).
  ``enabled`` stays its OWN column — NEVER inside ``config_json`` — because it is RUNTIME
  state with a different lifecycle from the authoring params in the blob, and it keeps
  ``list_active()`` a ``WHERE enabled=True`` query instead of a JSON scan (D-06).
* ``strategy_portfolio_subscriptions`` — the portfolio fan-out edge: a normalized child with
  ``strategy_name`` FK'd on ``strategy_registry.strategy_name`` and a natural composite PK
  ``(strategy_name, portfolio_id)`` — no surrogate UUID, no autoincrement. The engine runs ONE
  strategy object whose ``subscribed_portfolios`` fans out to N portfolios, so "same params on
  3 portfolios" is 1 instance row + 3 portfolio rows. Per-portfolio "off" is ROW PRESENCE (not
  a per-row enabled flag); whole-instance "off" is the ``enabled`` column. Rehydrate JOINs both.

``portfolio_id`` is a ``String`` because the stored form is a string by the round trip's own
construction: ``Strategy.to_dict`` serializes each handle via ``str(pid)`` (``base.py``) and
``registry/rehydrate.py::_resolve_portfolio_id`` parses it back. Unlike the portfolio-owned
tables — whose key is a ``PortfolioId`` written directly, hence their ``Uuid`` column — this
column stores the serialized projection of that handle, not the handle itself. Whether it
should instead become a ``Uuid`` column (the handle is now homogeneously ``PortfolioId``, so
nothing type-level forbids it) is a separate open question, filed as B2 and NOT settled here.

**DROPPED (D-06): the P4 ``strategy_subscriptions`` (venue, symbol, timeframe) table.** It
modelled the wrong edge and was redundant: its columns are derivable from (the live venue,
``config_json.tickers``, ``config_json.timeframe``) — a strategy has ONE timeframe and no
per-ticker venue — and its only unique job, a symbol→strategies reverse index, is an in-memory
dict built at rehydrate. ``tickers`` stay IN ``config_json`` (an authoring param); no
``strategy_symbols`` table is created. Revisit only if per-symbol venue divergence
(multi-venue strategies) is ever modelled.

The table stays named ``strategy_registry`` and the class stays ``StrategyRegistryStore``
(D-18): catalog = types (code), registry = registered instances (DB) — no rename, no migration
cost, verbatim match to the STRAT-01 / ROADMAP wording.

A disciplined clone of the ``HaltRecordStore`` template (STORE-04 / D-01), with the
multi-table registrar shape of ``build_order_tables``: composes ``SqlEngine`` by reference,
owns ``build_strategy_registry_tables`` (single source of truth for BOTH the test-path
``create_all`` and ``migrations/env.py``), schema-pure (WR-03/D-14 — no runtime
``create_all``; Alembic-owned in production, ``provision_schema`` in tests), caller-supplied
``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only (SEC-01 / T-10-07).
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


def build_strategy_registry_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the registry + portfolio-subscription tables on ``metadata``.

    Per-table idempotency guards on a shared backend (reuse an already-registered table) —
    the same shape as ``build_order_tables``. Single source of truth for BOTH tables' schema,
    feeding the test-path ``create_all`` and the Alembic ``target_metadata`` in
    ``migrations/env.py``: a divergence between this registrar and a migration silently splits
    the test-path and prod schemas (gated by the create_all-vs-migration parity test).

    D-06 shape: ``strategy_registry`` carries ``strategy_type``; the child is
    ``strategy_portfolio_subscriptions`` ``(strategy_name FK, portfolio_id)``. The P4
    ``strategy_subscriptions`` (venue, symbol, timeframe) table is DROPPED — see the module
    docstring for why.

    Returns ``{"strategy_registry": ..., "strategy_portfolio_subscriptions": ...}``.
    """
    tables: dict[str, Table] = {}

    if "strategy_registry" in metadata.tables:
        tables["strategy_registry"] = metadata.tables["strategy_registry"]
    else:
        tables["strategy_registry"] = Table(
            "strategy_registry",
            metadata,
            # Natural NAME PK (D-02) — the SOLE PK. NOT the ephemeral runtime strategy_id
            # UUID, and no second durable id column alongside it.
            Column("strategy_name", String, primary_key=True),
            # D-06 — the catalog key rehydrate resolves to a class (D-01).
            Column("strategy_type", String, nullable=False),
            # D-06 — runtime state, its OWN column (never inside config_json): keeps
            # list_active() a WHERE query rather than a JSON scan.
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )

    if "strategy_portfolio_subscriptions" in metadata.tables:
        tables["strategy_portfolio_subscriptions"] = metadata.tables[
            "strategy_portfolio_subscriptions"
        ]
    else:
        tables["strategy_portfolio_subscriptions"] = Table(
            "strategy_portfolio_subscriptions",
            metadata,
            # FK back to the registry natural name key; part of the composite PK.
            Column(
                "strategy_name",
                String,
                ForeignKey("strategy_registry.strategy_name"),
                primary_key=True,
                nullable=False,
            ),
            # String (not Uuid): to_dict serializes each handle via str(pid) and
            # rehydrate parses it back. A Uuid column is open as B2, not decided.
            Column("portfolio_id", String, primary_key=True, nullable=False),
        )

    return tables


class StrategyRegistryStore:
    """Name-keyed strategy-instance registry + the portfolio fan-out edge (D-06/D-18).

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
        self.strategy_portfolio_subscriptions: Table = tables[
            "strategy_portfolio_subscriptions"
        ]
        # WR-03/D-14 — schema-pure: register the tables, never create them (Alembic-owned
        # in production; tests provision via tests.support.schema.provision_schema).
        self.logger = get_itrader_logger().bind(component="StrategyRegistryStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(
        self,
        strategy_name: str,
        strategy_type: str,
        config: dict[str, Any],
        enabled: bool,
        at: datetime,
    ) -> None:
        """Persist (or overwrite) an instance's type/config/enabled with ``updated_at`` ``at``.

        Portable update-in-place-or-insert on the REGISTRY table in ONE transaction. The
        parent row is UPDATED (never deleted) when it already exists: deleting it would
        violate the ``strategy_portfolio_subscriptions`` FK once child rows exist — the live
        re-config path ``upsert`` → ``set_portfolio_subscriptions`` → ``upsert`` — which the
        SQLite ``PRAGMA foreign_keys=ON`` hook (WR-02) now enforces on both dialects (CR-01).
        Portfolio subscriptions are managed separately via the ``*_portfolio_subscription(s)``
        verbs. Parameterized Core (SEC-01).
        """
        with self.engine.begin() as connection:
            updated = connection.execute(
                update(self.strategy_registry)
                .where(self.strategy_registry.c.strategy_name == strategy_name)
                .values(
                    strategy_type=strategy_type,
                    enabled=enabled,
                    config_json=config,
                    updated_at=at,
                )
            )
            if updated.rowcount == 0:
                connection.execute(
                    insert(self.strategy_registry),
                    [
                        {
                            "strategy_name": strategy_name,
                            "strategy_type": strategy_type,
                            "enabled": enabled,
                            "config_json": config,
                            "updated_at": at,
                        }
                    ],
                )

    def set_portfolio_subscriptions(
        self,
        strategy_name: str,
        portfolio_ids: Sequence[str],
        at: datetime,
    ) -> None:
        """Replace-all the portfolio fan-out for ``strategy_name`` and touch ``updated_at``.

        Deletes every existing child row for the strategy then inserts the new set in ONE
        transaction, and bumps the parent registry ``updated_at`` to ``at`` so the row's
        timestamp reflects the latest mutation (config or subscriptions). An EMPTY set clears
        the fan-out. Parameterized Core (SEC-01).
        """
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.strategy_portfolio_subscriptions).where(
                    self.strategy_portfolio_subscriptions.c.strategy_name == strategy_name
                )
            )
            if portfolio_ids:
                connection.execute(
                    insert(self.strategy_portfolio_subscriptions),
                    [
                        {
                            "strategy_name": strategy_name,
                            "portfolio_id": portfolio_id,
                        }
                        for portfolio_id in portfolio_ids
                    ],
                )
            connection.execute(
                update(self.strategy_registry)
                .where(self.strategy_registry.c.strategy_name == strategy_name)
                .values(updated_at=at)
            )

    def add_portfolio_subscription(self, strategy_name: str, portfolio_id: str) -> None:
        """Subscribe ``strategy_name`` to ``portfolio_id`` — idempotent (D-09).

        Probes for the row and inserts only when absent, so a double-subscribe is a silent
        no-op rather than a composite-PK IntegrityError (mirrors the idempotent
        ``Strategy.subscribe_portfolio`` guard in ``base.py``). An FK violation (no parent
        registry row) still raises — that is a real error, not a duplicate.
        """
        table = self.strategy_portfolio_subscriptions
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(table.c.portfolio_id).where(
                    table.c.strategy_name == strategy_name,
                    table.c.portfolio_id == portfolio_id,
                )
            ).first()
            if existing is None:
                connection.execute(
                    insert(table),
                    [{"strategy_name": strategy_name, "portfolio_id": portfolio_id}],
                )

    def remove_portfolio_subscription(self, strategy_name: str, portfolio_id: str) -> None:
        """Unsubscribe ``strategy_name`` from ``portfolio_id`` — a no-op when absent (D-09).

        Per-portfolio "off" is ROW PRESENCE (D-06), so the unsubscribe verb is a plain DELETE;
        deleting a row that is not there is a silent no-op (mirrors the idempotent
        ``Strategy.unsubscribe_portfolio`` guard in ``base.py``).
        """
        table = self.strategy_portfolio_subscriptions
        with self.engine.begin() as connection:
            connection.execute(
                delete(table).where(
                    table.c.strategy_name == strategy_name,
                    table.c.portfolio_id == portfolio_id,
                )
            )

    def portfolio_subscriptions(self, strategy_name: str) -> list[str]:
        """The portfolio ids ``strategy_name`` fans out to, ``portfolio_id`` ASC (IN-01)."""
        table = self.strategy_portfolio_subscriptions
        statement = (
            select(table.c.portfolio_id)
            .where(table.c.strategy_name == strategy_name)
            .order_by(table.c.portfolio_id.asc())
        )
        with self.engine.connect() as connection:
            portfolio_ids = connection.execute(statement).scalars().all()
        return list(portfolio_ids)

    def get(self, strategy_name: str) -> Optional[Mapping[str, Any]]:
        """The registry row for ``strategy_name`` (type/config/enabled/updated_at), or None."""
        statement = select(
            self.strategy_registry.c.strategy_name,
            self.strategy_registry.c.strategy_type,
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
            "strategy_type": row["strategy_type"],
            "config": row["config_json"],
            "enabled": bool(row["enabled"]),
            "updated_at": row["updated_at"],
        }

    def delete(self, strategy_name: str) -> None:
        """Remove a strategy — child rows FIRST (FK order, P-6), then the registry row.

        The children-before-parent order is load-bearing: with the SQLite
        ``PRAGMA foreign_keys=ON`` hook (WR-02) the FK is enforced on BOTH dialects, so
        deleting the parent first would raise on a strategy holding subscriptions.
        """
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.strategy_portfolio_subscriptions).where(
                    self.strategy_portfolio_subscriptions.c.strategy_name == strategy_name
                )
            )
            connection.execute(
                delete(self.strategy_registry).where(
                    self.strategy_registry.c.strategy_name == strategy_name
                )
            )

    def list_active(self) -> list[Mapping[str, Any]]:
        """Every registry row with ``enabled=True`` — the typed-column query (D-06/D-09).

        ``enabled`` is its own column, so this is a ``WHERE`` query, not a JSON scan. Ordered
        by ``strategy_name`` ASC so the rehydrate REGISTRATION order is reproducible across
        runs and dialects (an unordered SELECT has no guaranteed row order).
        """
        statement = (
            select(
                self.strategy_registry.c.strategy_name,
                self.strategy_registry.c.strategy_type,
                self.strategy_registry.c.enabled,
                self.strategy_registry.c.config_json,
                self.strategy_registry.c.updated_at,
            )
            .where(self.strategy_registry.c.enabled.is_(True))
            .order_by(self.strategy_registry.c.strategy_name.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            {
                "strategy_name": row["strategy_name"],
                "strategy_type": row["strategy_type"],
                "config": row["config_json"],
                "enabled": bool(row["enabled"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every strategy with its portfolio fan-out — the FK-join rehydrate (D-06).

        LEFT OUTER JOIN so a strategy with no portfolio subscriptions still appears (with an
        empty ``portfolio_ids`` list); grouped by ``strategy_name`` in Python into one record
        per strategy.
        """
        join = self.strategy_registry.outerjoin(
            self.strategy_portfolio_subscriptions,
            self.strategy_registry.c.strategy_name
            == self.strategy_portfolio_subscriptions.c.strategy_name,
        )
        statement = (
            select(
                self.strategy_registry.c.strategy_name,
                self.strategy_registry.c.strategy_type,
                self.strategy_registry.c.enabled,
                self.strategy_registry.c.config_json,
                self.strategy_registry.c.updated_at,
                self.strategy_portfolio_subscriptions.c.portfolio_id,
            )
            .select_from(join)
            # IN-01 — deterministic rehydrate order. strategy_name ASC drives the RECORD
            # order (records dict is populated in row order), and portfolio_id ASC drives
            # each record's portfolio_ids append order. Guards byte-exact/golden callers.
            .order_by(
                self.strategy_registry.c.strategy_name.asc(),
                self.strategy_portfolio_subscriptions.c.portfolio_id.asc(),
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
                    "strategy_type": row["strategy_type"],
                    "config": row["config_json"],
                    "enabled": bool(row["enabled"]),
                    "updated_at": row["updated_at"],
                    "portfolio_ids": [],
                }
                records[name] = record
            # An outer-join row with no matching child has a NULL portfolio_id column.
            if row["portfolio_id"] is not None:
                record["portfolio_ids"].append(row["portfolio_id"])
        return list(records.values())
