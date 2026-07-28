"""Durable portfolio DEFINITIONS — what a portfolio IS.

The finding that motivated this module: seven portfolio-scoped child tables all record what a
portfolio HAS (positions, cash operations, transactions, account state, …) and none record
what it IS. This module adds that missing definition row on the shared ``SqlEngine`` spine.

``portfolios`` is keyed on ``portfolio_id`` (``Uuid``, matching ``orders.portfolio_id`` and
``portfolio_account_state.portfolio_id`` — the handle stays the UUIDv7 the id generator mints
and is never re-schemed) and carries ``name``, the ``(venue_name, account_id)`` account
reference, ``initial_cash``, ``enabled``, ``is_deleted``, ``config_json`` and ``updated_at``.

**TWO lifecycle flags, not one.** They are deliberately NOT collapsed:

* ``enabled`` = **PAUSED**. The portfolio KEEPS its venue account, so re-enabling it always
  works and can never collide with anything.
* ``is_deleted`` = **RETIRED**. The portfolio RELEASES the ``(venue_name, account_id)`` pair
  so a successor can take the account over. Deletion is SOFT — the row, its history and its
  seven child tables all survive.

Collapsing them into one flag would make a merely PAUSED portfolio release its account, and
re-enabling it could then collide with whatever took the account.

**There is deliberately NO ``exchange`` column.** A portfolio's venue is the ``venue_name``
half of its account reference; storing it a second time creates two sources of truth that can
drift apart, and the drifted pair has no tiebreaker.

**Two table-level guarantees.** The FK requires the TABLE-level form because the key is
composite (a column-level ``ForeignKey`` cannot express a two-column reference):

* ``ForeignKeyConstraint(['venue_name','account_id']) -> venue_accounts`` — UNCONDITIONAL,
  which the NOT NULL ``account_id`` makes possible: paper portfolios get real
  ``venue_accounts`` rows rather than NULLs, so there is no partial case to special-case.
* ``Index('uq_portfolios_live_account', 'venue_name', 'account_id', unique=True)`` — now
  **PARTIAL over the LIVE rows** (``WHERE NOT is_deleted``).

  **Why partial is still the same guarantee.** The plain-index rationale was about
  **SIMULTANEOUS** sharing: two portfolios trading one venue account at once would conflate
  buying power the venue cannot split back out — a money-losing wrong answer. The partial
  index refuses that case unchanged, because both rows would be live and therefore both
  indexed. A merely PAUSED portfolio (``enabled=False``) is still live for this purpose and
  still holds its account. What the partial form newly permits is only **SEQUENTIAL** reuse:
  once a portfolio is RETIRED it leaves the indexed set, and a successor may take the account
  over. The index is self-enforcing in both directions — un-retiring a row while a successor
  holds the pair violates it exactly as a fresh insert would.

  **The "binds out-of-band writers" half survives intact.** Uniqueness is still a DATABASE
  constraint, not an application check, so a writer that never reaches the application (the
  future integrations page) is still bound. Nothing moved to an application-level check,
  which would be TOCTOU and would not bind such a writer at all.

  **BOTH dialect predicates are declared** (``postgresql_where`` and ``sqlite_where``): the
  test suite runs SQLite and production runs Postgres, so a single-dialect predicate would
  silently degrade to a PLAIN index on the other engine — and the degradation on the SQLite
  side would be invisible to every test in the tree.

A disciplined clone of the spine store template, with the multi-table registrar shape of
``build_strategy_registry_tables``: composes ``SqlEngine`` by reference, owns
``build_portfolio_definition_tables`` (single source of truth for BOTH the test-path
provisioning helper and ``migrations/env.py``), schema-pure (this module never creates its own
schema at runtime; Alembic-owned in production, ``provision_schema`` in tests),
caller-supplied ``at`` via ``UtcIsoText`` (clock-free), parameterized Core only.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKeyConstraint,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    delete,
    insert,
    select,
    update,
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
        portfolios = Table(
            "portfolios",
            metadata,
            Column("portfolio_id", Uuid(as_uuid=True), primary_key=True),
            Column("name", String, nullable=False),
            # The (venue_name, account_id) account reference. NOT NULL on both halves is
            # what makes the FK unconditional and lets the unique index be partial on
            # is_deleted alone rather than on a nullable pair.
            Column("venue_name", String, nullable=False),
            Column("account_id", String, nullable=False),
            # Money — read back as Decimal (Numeric), never float.
            Column("initial_cash", Numeric, nullable=False),
            Column("enabled", Boolean, nullable=False),
            # NO server_default here, deliberately: the migration adds one only to backfill
            # existing rows and then drops it inside batch_alter_table, so the deployed schema
            # and this registrar agree. A default left on one side is exactly the silent
            # test-path/prod split the create_all-vs-migration parity gate exists to catch.
            Column("is_deleted", Boolean, nullable=False),
            # Destination for the per-portfolio config blob; nullable because
            # load_config() explicitly handles None.
            Column("config_json", json_variant(), nullable=True),
            Column("updated_at", UtcIsoText, nullable=False),
            # Composite reference — the table-level form is REQUIRED for a two-column key.
            ForeignKeyConstraint(
                ["venue_name", "account_id"],
                ["venue_accounts.venue_name", "venue_accounts.account_id"],
            ),
        )
        # PARTIAL over the LIVE rows (see module docstring). Declared AFTER the Table so
        # the predicate can name the real bound Column; an Index built from a table's own
        # columns attaches itself to that table, so create_all still emits it.
        Index(
            "uq_portfolios_live_account",
            portfolios.c.venue_name,
            portfolios.c.account_id,
            unique=True,
            postgresql_where=~portfolios.c.is_deleted,
            sqlite_where=~portfolios.c.is_deleted,
        )
        tables["portfolios"] = portfolios

    return tables


class PortfolioDefinitionStore:
    """Portfolio definition rows — upsert / get / read-all.

    Parameters
    ----------
    sql_engine:
        The shared spine (Engine + MetaData). The driver/URL is config-selected at wiring;
        this store registers its tables on ``sql_engine.metadata`` but does NOT create them
        — the durable schema is Alembic-owned in production and provisioned by
        the shared ``provision_schema`` test fixture in tests.
    """

    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        tables = build_portfolio_definition_tables(sql_engine.metadata)
        self.portfolios: Table = tables["portfolios"]
        self.logger = get_itrader_logger().bind(component="PortfolioDefinitionStore")

    def dispose(self) -> None:
        """Dispose the shared backend engine (delegate, never engine.dispose())."""
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
        is_deleted: bool = False,
    ) -> None:
        """Persist (or overwrite) one portfolio definition with ``updated_at`` ``at``.

        Portable delete-then-insert on ``portfolio_id`` in ONE transaction, so re-defining a
        portfolio replaces its row rather than duplicating it. ``initial_cash`` enters the
        Decimal domain via ``to_money`` — never ``Decimal(float)``. A duplicate LIVE
        ``(venue_name, account_id)`` or a missing ``venue_accounts`` parent raises
        ``IntegrityError`` from the DB (the composite FK). Parameterized Core.

        ``is_deleted`` defaults to ``False``: defining a portfolio makes it LIVE, and
        every existing caller therefore keeps its current meaning unchanged. The column is
        written explicitly rather than left to a server default — the registrar declares no
        server_default, so an omitted key would fail the NOT NULL. Retiring an EXISTING
        portfolio is a lifecycle transition, not a redefinition, and gets its own writer
        (``set_deleted``); this parameter exists so the definition of a portfolio is complete
        at the point it is written.
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
                        "is_deleted": is_deleted,
                        "config_json": config,
                        "updated_at": at,
                    }
                ],
            )

    def get(self, portfolio_id: UUID) -> Optional[Mapping[str, Any]]:
        """The definition row for ``portfolio_id``, or None when absent.

        Deliberately NOT filtered on ``is_deleted`` (unlike ``read_all``): this read is
        id-addressed, so a caller already holding the handle is asking about that specific
        portfolio and needs to see that it was RETIRED rather than get ``None`` and conclude
        it never existed. The flag is in the returned mapping.
        """
        statement = self._select_columns().where(
            self.portfolios.c.portfolio_id == portfolio_id
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return self._row_to_dict(row)

    def read_all(self) -> list[Mapping[str, Any]]:
        """Every LIVE portfolio definition — the rehydrate read.

        LIVE-ONLY: rows with ``is_deleted`` true are omitted, because this read is what
        rehydrate builds the running system from. A retired portfolio must NOT come back on
        the next boot with its persisted id and its child tables reattached. Deletion stays
        SOFT (the row and its history survive and remain reachable through ``get``); it is
        only invisible to rehydrate. This also keeps the read aligned with the partial unique
        index: a successor may now hold the same ``(venue_name, account_id)`` pair, so
        returning both rows would hand rehydrate two portfolios on one account.

        ORDERING CONTRACT: ``portfolio_id`` ASC. Explicit rather than driver-dependent, so
        the rehydrate REGISTRATION order is reproducible across runs and dialects (an
        unordered SELECT has no guaranteed row order).
        """
        statement = (
            self._select_columns()
            .where(~self.portfolios.c.is_deleted)
            .order_by(self.portfolios.c.portfolio_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._row_to_dict(row) for row in rows]

    def set_enabled(self, portfolio_id: UUID, enabled: bool, at: datetime) -> None:
        """PAUSE / RESUME one portfolio — a TARGETED UPDATE of ``enabled`` only.

        ``enabled`` is the **PAUSED** flag: a paused portfolio KEEPS its
        ``(venue_name, account_id)`` account, so re-enabling it always works and can never
        collide with a successor (contrast ``set_deleted`` — RETIRED — which releases the
        pair). This writer is what makes an operator's deliberate pause DURABLE — without it,
        a paused portfolio would come back ACTIVE and trading on the next boot, since nothing
        else persists ``enabled=False``. ``rehydrate_portfolios``' present-but-inactive branch
        is reachable by a real code path only once this persists ``enabled=False``.

        A TARGETED UPDATE of ``enabled`` (and ``updated_at``) only, leaving ``config_json``,
        ``venue_name``, ``account_id``, ``initial_cash`` and ``is_deleted`` UNTOUCHED. Like
        ``VenueAccountStore.record_venue_uid``, it must NOT travel through the
        operator-authored ``upsert`` path: ``upsert`` is a DELETE-then-INSERT and would
        restate — and therefore be able to clobber — every operator-authored column, wiping
        ``config_json`` on a mere pause.

        Clock-free: the write timestamp is caller-supplied, matching every other durable-write
        verb in the tree. ``portfolio_id`` is matched EXACTLY. A portfolio_id with no row is a
        silent no-op (zero rows matched) — consistent with ``set_deleted`` and with
        ``record_venue_uid``'s sibling contract; the lifecycle callers (``deactivate_portfolio``
        / ``activate_portfolio``) only reach this for a portfolio that already has a definition
        row, so the no-match case is purely defensive. Idempotent: calling it twice with the
        same value leaves the row byte-identical and never raises. Parameterized Core against
        the constant ``Table``.
        """
        with self.engine.begin() as connection:
            connection.execute(
                update(self.portfolios)
                .where(self.portfolios.c.portfolio_id == portfolio_id)
                .values(enabled=enabled, updated_at=at)
            )

    def set_deleted(self, portfolio_id: UUID, is_deleted: bool, at: datetime) -> None:
        """RETIRE one portfolio — a TARGETED UPDATE of ``is_deleted`` only.

        ``is_deleted`` is the **RETIRED** flag: a retired portfolio RELEASES its
        ``(venue_name, account_id)`` pair (it leaves the partial unique index's live set) so a
        SUCCESSOR portfolio can take the real venue account over. Deletion is SOFT: the row,
        its history and its seven child tables all SURVIVE and stay reachable through ``get``;
        ``read_all`` (the rehydrate read) is what stops a retired portfolio returning as a live
        one on the next boot. This is deliberately NOT the same as ``set_enabled`` (PAUSED,
        keeps its account) — collapsing the two flags would make a paused portfolio release
        its account and a re-enable then collide with whatever took it.

        This writer is what ``delete_portfolio`` calls, so a retired portfolio's persisted id
        and child tables stay RELEASED rather than reattaching to a resurrected row on restart.

        A TARGETED UPDATE of ``is_deleted`` (and ``updated_at``) only, leaving every other
        column untouched — same reasoning as ``set_enabled``: never route through the
        DELETE-then-INSERT ``upsert`` (would clobber ``config_json``). Clock-free,
        exact-match ``portfolio_id``, silent no-op on no match (consistent with
        ``set_enabled``), idempotent, parameterized Core.
        """
        with self.engine.begin() as connection:
            connection.execute(
                update(self.portfolios)
                .where(self.portfolios.c.portfolio_id == portfolio_id)
                .values(is_deleted=is_deleted, updated_at=at)
            )

    def live_portfolio_ids_for_account(
        self, venue_name: str, account_id: str
    ) -> list[UUID]:
        """The LIVE portfolios claiming one ``(venue_name, account_id)`` pair.

        A "live" portfolio is one whose row has ``enabled = True AND NOT is_deleted`` — the
        durable equivalent of an ACTIVE in-memory portfolio. This is the read
        ``VenueAccountManager.set_enabled(..., False)`` resolves its refusal against: it
        refuses while ANY live portfolio still references the account, and this read is what
        tells it which ones. Resolving against the DURABLE store — rather than a live
        in-memory portfolio collaborator — keeps the manager free of a portfolio-handler
        back-reference (the one-directional layering).

        A PAUSED portfolio (``enabled=False``) is deliberately EXCLUDED — pausing is the
        sanctioned way to release the block — and so is a RETIRED one (``is_deleted=True``),
        which has already released its pair. Ordered ``portfolio_id`` ASC so the refusal
        message lists the blocking ids reproducibly. Parameterized Core.
        """
        statement = (
            select(self.portfolios.c.portfolio_id)
            .where(
                self.portfolios.c.venue_name == venue_name,
                self.portfolios.c.account_id == account_id,
                self.portfolios.c.enabled.is_(True),
                ~self.portfolios.c.is_deleted,
            )
            .order_by(self.portfolios.c.portfolio_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).all()
        return [row[0] for row in rows]

    def _select_columns(self) -> Any:
        """The shared column projection every read uses (one place to keep them in sync)."""
        return select(
            self.portfolios.c.portfolio_id,
            self.portfolios.c.name,
            self.portfolios.c.venue_name,
            self.portfolios.c.account_id,
            self.portfolios.c.initial_cash,
            self.portfolios.c.enabled,
            self.portfolios.c.is_deleted,
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
            # Both lifecycle flags are coerced to real bools: SQLite stores Boolean as
            # INTEGER, so an uncoerced value would be 0/1 and `is False` identity checks
            # would fail.
            "enabled": bool(row["enabled"]),
            "is_deleted": bool(row["is_deleted"]),
            "config": row["config_json"],
            "updated_at": row["updated_at"],
        }
