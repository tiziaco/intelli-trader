"""b2 uuid fk + d-09 config move

The MUTATING half of the Phase 11 W1 schema boundary (D-29/D-09) — everything in this
revision touches data or reshapes an existing table, which is exactly why it is SPLIT from
the pure-DDL ``p11_venue_accounts_portfolios`` that precedes it: the two halves get separate
guards and separate downgrade paths.

``upgrade()`` runs THREE steps, in a load-bearing order:

**Step 1 — the A1 guard, FIRST, before any mutation (T-11-11).** ``strategy_portfolio_subscriptions``
is counted and the migration REFUSES with a ``RuntimeError`` naming the row count when it holds
data. Same house rule as ``p10_strategy_portfolio_subs``: loud rejection over a silent
destructive op on an assumption ("the table is empty in every deployed DB") that could not be
verified from source. The table is NEVER auto-cleared to let the migration proceed.

**Step 2 — the B2 change.** ``portfolio_id`` goes ``String`` -> ``Uuid`` and gains a
``ForeignKey("portfolios.portfolio_id", ondelete="CASCADE")``. CASCADE is right because a
subscription to a nonexistent portfolio has no meaning (unlike ``orders.parent_order_id``,
which uses ``SET NULL`` deliberately: an orphaned bracket child is still a real historical
order). Applied as a DROP + CREATE, which is lossless because the guard above has already
proven the table is empty — see ``_create_subscriptions`` for the full rationale. Neither
``batch_alter_table`` nor a ``USING portfolio_id::uuid`` cast is used: the former is a
passthrough on Postgres that emits an ALTER Postgres refuses, and the latter is exactly the
dialect-specific cast this revision is forbidden to introduce.

**Step 3 — the D-09 config data move.** ``config_json`` moves from the STATE row
(``portfolio_account_state``) to the DEFINITION row (``portfolios``). Config belongs on a
definition row; it only ever lived on the state row because no definition row existed.

**This step is the single highest-regression-risk operation in the phase, and the risk is
that it fails SILENTLY.** ``load_config()`` returning ``None`` is guarded by a truthiness
check and wrapped in a warning-only degrade-clean, so a migration that repoints reads without
actually moving the data produces no exception, no warning, a successful boot, a fully green
test suite — and every live portfolio silently trading on default configuration. There is no
analog anywhere in this chain to copy from: all eleven prior revisions are pure DDL and
nothing has ever moved data between tables here. The move is therefore covered by a dedicated
by-value migration test (``tests/integration/test_p11_migration_chain.py``) that seeds a
distinctive non-default blob and asserts EQUALITY of the migrated value — plus a negative
control proving that test fails when the UPDATE step is skipped. A non-null assertion would
NOT close this gap.

The blob is copied VERBATIM: not reshaped, not validated, no keys filtered, never coerced
into a typed model. It is a free-form PARTIAL override that ``Portfolio.update_config``
merges recursively at load time, so typing it would break the partial-merge contract.

``portfolio_account_state.config_json`` is deliberately NOT dropped here. Leaving the old
column in place keeps the move recoverable and makes the downgrade honest. Retiring the
column is deliberate FUTURE work, not an oversight.

A ``portfolio_account_state`` row whose ``portfolio_id`` has no ``portfolios`` parent is an
already-orphaned pre-Phase-11 row (nothing wrote ``portfolios`` rows before this phase). Such
rows are COUNTED and logged, never fatal — and a parent is never silently fabricated for them.

``downgrade()`` is the exact inverse in reverse order: copy the config back, drop the CASCADE
FK, revert the column type to ``String``.

Revision ID: p11_b2_uuid_fk_config_move
Revises: p11_venue_accounts_portfolios
Create Date: 2026-07-21 00:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "p11_b2_uuid_fk_config_move"
down_revision: Union[str, Sequence[str], None] = "p11_venue_accounts_portfolios"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOG = logging.getLogger("alembic.runtime.migration")

_SUBSCRIPTIONS = "strategy_portfolio_subscriptions"
_FK_NAME = "fk_strategy_portfolio_subscriptions_portfolio_id_portfolios"


def _json_type() -> sa.JSON:
    """The portable JSON column type — ``JSONB`` on Postgres, ``JSON`` on SQLite.

    Mirrors ``itrader.storage.types.json_variant`` by hand rather than importing the store
    module (Pitfall 2 / GATE-01: a migration must not pull store runtime dependencies onto
    the import path).
    """
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _config_tables() -> tuple[sa.Table, sa.Table]:
    """Minimal ``Table`` objects for the D-09 move — SOURCE then DESTINATION.

    Declared with their REAL column types on a throwaway ``MetaData`` (never the app's), so
    the JSON serde and the ``Uuid`` binding run on both ends of the copy. A bare
    ``sa.table``/``sa.column`` pair would carry NullType and move the blob as a raw string,
    landing a DOUBLE-ENCODED value in the destination that ``load_config`` would return as a
    ``str`` instead of a ``dict`` — a silent corruption this shape rules out.
    """
    metadata = sa.MetaData()
    account_state = sa.Table(
        "portfolio_account_state",
        metadata,
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("config_json", _json_type(), nullable=True),
    )
    portfolios = sa.Table(
        "portfolios",
        metadata,
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("config_json", _json_type(), nullable=True),
    )
    return account_state, portfolios


def _create_subscriptions(
    *, portfolio_id_type: sa.types.TypeEngine, with_portfolios_fk: bool
) -> None:
    """Re-create ``strategy_portfolio_subscriptions`` with the given ``portfolio_id`` type.

    **Why DROP + CREATE and not ``batch_alter_table``.** ``batch_alter_table`` only does the
    move-and-copy dance on SQLite; on Postgres it is a passthrough that emits a plain
    ``ALTER TABLE ... ALTER COLUMN portfolio_id TYPE UUID``, which Postgres REFUSES:

        (psycopg2.errors.DatatypeMismatch) column "portfolio_id" cannot be cast
        automatically to type uuid
        HINT: You might need to specify "USING portfolio_id::uuid".

    (Observed against the testcontainers Postgres arm of
    ``tests/integration/storage/test_migrations.py`` — it is not a hypothetical.) The only
    two ways to make ``ALTER COLUMN TYPE`` work there are the ``USING portfolio_id::uuid``
    cast — which this revision is explicitly forbidden to use — or a drop-and-recreate.

    DROP + CREATE is the right resolution rather than a workaround, because
    ``_refuse_if_subscriptions_hold_data`` has ALREADY proven the table is empty before this
    runs. With zero rows there is nothing for a cast to preserve, so the recreate is provably
    lossless, needs no dialect-specific SQL at all, and behaves identically on SQLite and
    Postgres. It also makes the PK and BOTH foreign keys explicit instead of depending on
    SQLite batch-mode reflection to faithfully carry the existing ``strategy_registry`` FK
    across the rebuild.

    Column shape mirrors ``build_strategy_registry_tables``
    (``itrader/storage/strategy_registry_store.py``) — the single source of truth — so the
    create_all and migration paths do not split.
    """
    columns: list[sa.schema.SchemaItem] = [
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("portfolio_id", portfolio_id_type, nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_name"],
            ["strategy_registry.strategy_name"],
            name=op.f(
                "fk_strategy_portfolio_subscriptions_strategy_name_strategy_registry"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "strategy_name",
            "portfolio_id",
            name=op.f("pk_strategy_portfolio_subscriptions"),
        ),
    ]
    if with_portfolios_fk:
        # CASCADE — a subscription to a nonexistent portfolio has no meaning (contrast
        # orders.parent_order_id's deliberate SET NULL: an orphaned bracket child is still a
        # real historical order).
        columns.append(
            sa.ForeignKeyConstraint(
                ["portfolio_id"],
                ["portfolios.portfolio_id"],
                name=op.f(_FK_NAME),
                ondelete="CASCADE",
            )
        )
    op.create_table(_SUBSCRIPTIONS, *columns)


def _refuse_if_subscriptions_hold_data() -> None:
    """A1 GUARD (T-11-11) — raise rather than retype a populated subscriptions table.

    Runs BEFORE any mutation. Parameter-free count via the migration's own bind.
    """
    count = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {_SUBSCRIPTIONS}")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"REFUSING to retype '{_SUBSCRIPTIONS}.portfolio_id': the table holds {count} "
            "row(s). This migration (B2/D-29) changes the column from String to Uuid and "
            "adds an ON DELETE CASCADE foreign key to portfolios.portfolio_id, on the "
            "assumption the table is empty in every deployed DB — an assumption that could "
            "not be verified from source. Any rows that DO exist point at portfolio ids "
            "minted by the pre-Phase-11 id generation, which was not restart-stable, so "
            "they are already orphaned and would fail the new foreign key anyway. Inspect "
            f"the rows (SELECT * FROM {_SUBSCRIPTIONS}), archive anything you need, DELETE "
            "them, then re-run 'alembic upgrade head'. This migration will NOT clear the "
            "table for you."
        )


def _move_config(source: sa.Table, destination: sa.Table) -> None:
    """Copy every non-NULL ``config_json`` from ``source`` onto the matching ``destination`` row.

    Parameterized SQLAlchemy Core (never string SQL). Rows with no matching destination
    parent are counted and logged, never fatal — see the module docstring.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(source.c.portfolio_id, source.c.config_json).where(
            source.c.config_json.is_not(None)
        )
    ).mappings().all()

    moved = 0
    orphaned = 0
    for row in rows:
        result = bind.execute(
            sa.update(destination)
            .where(destination.c.portfolio_id == row["portfolio_id"])
            # VERBATIM — no reshaping, no validation, no key filtering. The blob is a
            # free-form partial override merged recursively at load time.
            .values(config_json=row["config_json"])
        )
        if result.rowcount:
            moved += 1
        else:
            orphaned += 1

    _LOG.info(
        "D-09 config move: %d blob(s) moved onto portfolios.config_json, "
        "%d orphaned account-state row(s) skipped (no portfolios parent)",
        moved,
        orphaned,
    )


def upgrade() -> None:
    """Guard, retype ``portfolio_id`` + add the CASCADE FK, then move the config (D-29/D-09)."""
    # 1. A1 guard FIRST — before any mutation (T-11-11). Nothing below runs if it raises.
    _refuse_if_subscriptions_hold_data()

    # 2. B2 — String -> Uuid + the CASCADE FK, via DROP + CREATE (see _recreate_subscriptions).
    op.drop_table(_SUBSCRIPTIONS)
    _create_subscriptions(portfolio_id_type=sa.Uuid(as_uuid=True), with_portfolios_fk=True)

    # 3. D-09 — move the config blob from the STATE row onto the DEFINITION row.
    account_state, portfolios = _config_tables()
    _move_config(account_state, portfolios)


def downgrade() -> None:
    """The exact inverse in reverse order — config back, FK dropped, column back to String."""
    # 3'. Copy the config back onto the state row (the old column was never dropped).
    account_state, portfolios = _config_tables()
    _move_config(portfolios, account_state)

    # 2'. Drop the CASCADE FK and revert the column type — the same DROP + CREATE, inverted.
    op.drop_table(_SUBSCRIPTIONS)
    _create_subscriptions(portfolio_id_type=sa.String(), with_portfolios_fk=False)
