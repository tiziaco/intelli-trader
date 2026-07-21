"""Durable portfolio DEFINITIONS — what a portfolio IS (D-07/D-08/D-14, MPORT-02).

The finding that motivated Phase 11: seven portfolio-scoped child tables all record what a
portfolio HAS (positions, cash operations, transactions, account state, …) and none record
what it IS. This module adds that missing definition row on the shared ``SqlEngine`` spine.

**Shape (D-07).** ``portfolios`` is keyed on ``portfolio_id`` (``Uuid``, matching
``orders.portfolio_id`` and ``portfolio_account_state.portfolio_id`` — the handle stays the
UUIDv7 the id generator mints and is never re-schemed) and carries ``name``, the
``(venue_name, account_id)`` account reference, ``initial_cash``, ``enabled``, ``config_json``
and ``updated_at``.

**There is deliberately NO ``exchange`` column (D-07).** A portfolio's venue is the
``venue_name`` half of its account reference; storing it a second time creates two sources of
truth that can drift apart, and the drifted pair has no tiebreaker.

**Two table-level constraints**, both requiring the TABLE-level form because the key is
composite (a column-level ``ForeignKey`` cannot express a two-column reference):

* ``ForeignKeyConstraint(['venue_name','account_id']) -> venue_accounts`` — UNCONDITIONAL,
  which D-06's NOT NULL ``account_id`` is what makes possible: paper portfolios get real
  ``venue_accounts`` rows rather than NULLs, so there is no partial case to special-case.
* ``UniqueConstraint('venue_name','account_id')`` — the D-14 DB half, PLAIN (never partial,
  conditional or deferrable). Two portfolios sharing one venue account would conflate buying
  power that the venue cannot split back out — a money-losing wrong answer (T-11-02). At the
  DB layer it also binds out-of-band writers (the future integrations page), where an
  application-only check would be silently bypassed.

A disciplined clone of the spine store template, with the multi-table registrar shape of
``build_strategy_registry_tables``: composes ``SqlEngine`` by reference, owns
``build_portfolio_definition_tables`` (single source of truth for BOTH the test-path
provisioning helper and ``migrations/env.py``), schema-pure (WR-03/D-14 — this module never
creates its own schema at runtime; Alembic-owned in production, ``provision_schema`` in
tests), caller-supplied ``at`` via ``UtcIsoText`` (D-07 — clock-free), parameterized Core only
(SEC-01).

4-space indentation (matches the ``itrader/storage`` spine layer).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKeyConstraint,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    delete,
    insert,
    select,
)
from sqlalchemy.engine import Engine, RowMapping

from itrader.core.money import to_money
from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, Uuid, UtcIsoText, json_variant
from itrader.storage.venue_account_store import build_venue_accounts_table


def build_portfolio_definition_tables(metadata: MetaData) -> dict[str, Table]:
    """Register (idempotently) the portfolio-definition tables on ``metadata``.

    Per-table idempotency guards on a shared backend (reuse an already-registered table) —
    the same shape as ``build_strategy_registry_tables``. Single source of truth for the
    schema, feeding the test-path provisioning helper and the Alembic ``target_metadata`` in
    ``migrations/env.py``: a divergence between this registrar and a migration silently splits
    the test-path and prod schemas.

    The PARENT ``venue_accounts`` table is registered here too (via its own registrar, so
    there is still exactly one definition of it). The composite ``ForeignKeyConstraint``
    resolves by table NAME at schema-emit / DDL time, so a consumer that registered only
    ``portfolios`` would fail on an unresolvable reference; delegating keeps the FK valid for
    every consumer without duplicating the parent's column definitions.

    Returns ``{"venue_accounts": ..., "portfolios": ...}``.
    """
    tables: dict[str, Table] = {
        "venue_accounts": build_venue_accounts_table(metadata),
    }

    if "portfolios" in metadata.tables:
        tables["portfolios"] = metadata.tables["portfolios"]
    else:
        tables["portfolios"] = Table(
            "portfolios",
            metadata,
            # The durable handle, matching orders.portfolio_id / portfolio_account_state.
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("name", String, nullable=False),
            # The (venue_name, account_id) account reference — D-01's pair. NOT NULL on both
            # halves (D-06) is what makes the FK unconditional and the unique index PLAIN.
            Column("venue_name", String, nullable=False),
            Column("account_id", String, nullable=False),
            # Money — read back as Decimal (Numeric), never float.
            Column("initial_cash", Numeric, nullable=False),
            Column("enabled", Boolean, nullable=False),
            # D-09's destination for the per-portfolio config blob; nullable because
            # load_config() explicitly handles None.
            Column("config_json", json_variant(), nullable=True),
            Column("updated_at", UtcIsoText, nullable=False),
            # Composite reference — the table-level form is REQUIRED for a two-column key.
            ForeignKeyConstraint(
                ["venue_name", "account_id"],
                ["venue_accounts.venue_name", "venue_accounts.account_id"],
            ),
            # D-14 / T-11-02 — PLAIN, so no portfolio pair can ever collide, including on an
            # out-of-band write that never reaches the application check.
            UniqueConstraint("venue_name", "account_id"),
        )

    return tables


class PortfolioDefinitionStore:
    """Portfolio definition rows — upsert / get / read-all (D-07/D-08).

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is config-selected at wiring;
        this store registers its tables on ``sql_engine.metadata`` but does NOT create them
        — the durable schema is Alembic-owned in production (WR-03/D-14) and provisioned by
        the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        tables = build_portfolio_definition_tables(sql_engine.metadata)
        self.portfolios: Table = tables["portfolios"]
        # WR-03/D-14 — schema-pure: register the tables, never create them here
        # (Alembic-owned in production; tests provision via provision_schema).
        self.logger = get_itrader_logger().bind(component="PortfolioDefinitionStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (WR-03 — delegate, never engine.dispose())."""
        self.backend.dispose()

    def upsert(
        self,
        portfolio_id: UUID,
        *,
        name: str,
        venue_name: str,
        account_id: str,
        initial_cash: Decimal | int | str,
        enabled: bool,
        config: Optional[dict[str, Any]],
        at: datetime,
    ) -> None:
        """Persist (or overwrite) one portfolio definition with ``updated_at`` ``at``.

        Portable delete-then-insert on ``portfolio_id`` in ONE transaction, so re-defining a
        portfolio replaces its row rather than duplicating it. ``initial_cash`` enters the
        Decimal domain via ``to_money`` — never ``Decimal(float)``. A duplicate
        ``(venue_name, account_id)`` or a missing ``venue_accounts`` parent raises
        ``IntegrityError`` from the DB (D-14 / the composite FK). Parameterized Core (SEC-01).
        """
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.portfolios).where(
                    self.portfolios.c.portfolio_id == portfolio_id
                )
            )
            connection.execute(
                insert(self.portfolios),
                [
                    {
                        "portfolio_id": portfolio_id,
                        "name": name,
                        "venue_name": venue_name,
                        "account_id": account_id,
                        "initial_cash": to_money(initial_cash),
                        "enabled": enabled,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )

    def get(self, portfolio_id: UUID) -> Optional[Mapping[str, Any]]:
        """The definition row for ``portfolio_id``, or None when absent."""
        statement = self._select_columns().where(
            self.portfolios.c.portfolio_id == portfolio_id
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every portfolio definition — the rehydrate read.

        ORDERING CONTRACT: ``portfolio_id`` ASC. Explicit rather than driver-dependent, so
        the rehydrate REGISTRATION order is reproducible across runs and dialects (an
        unordered SELECT has no guaranteed row order).
        """
        statement = self._select_columns().order_by(
            self.portfolios.c.portfolio_id.asc()
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_dict(row) for row in rows]

    def _select_columns(self) -> Any:
        """The shared column projection every read uses (one place to keep them in sync)."""
        return select(
            self.portfolios.c.portfolio_id,
            self.portfolios.c.name,
            self.portfolios.c.venue_name,
            self.portfolios.c.account_id,
            self.portfolios.c.initial_cash,
            self.portfolios.c.enabled,
            self.portfolios.c.config_json,
            self.portfolios.c.updated_at,
        )

    @staticmethod
    def _row_to_dict(row: "RowMapping") -> dict[str, Any]:
        """Map a result row to the store's public dict shape (money stays Decimal)."""
        return {
            "portfolio_id": row["portfolio_id"],
            "name": row["name"],
            "venue_name": row["venue_name"],
            "account_id": row["account_id"],
            "initial_cash": to_money(row["initial_cash"]),
            "enabled": bool(row["enabled"]),
            "config": row["config_json"],
            "updated_at": row["updated_at"],
        }
