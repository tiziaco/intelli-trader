"""strategy portfolio subscriptions

Reshape the strategy registry to the D-06 data model — THREE operations in one upgrade
(STRAT-01, D-06/D-18/D-02):

1. ADD ``strategy_registry.strategy_type`` (non-null) — the catalog key rehydrate resolves to
   a class (``catalog[strategy_type]``, D-01). ``strategy_name`` stays the SOLE PK (D-02): no
   second durable id column is added, and the ephemeral runtime ``strategy_id`` UUIDv7 is
   never persisted. ``enabled`` stays its OWN column (D-06) — runtime state with a different
   lifecycle from the authoring params in ``config_json``.
2. CREATE ``strategy_portfolio_subscriptions`` ``(strategy_name FK, portfolio_id)`` composite
   PK — the portfolio fan-out edge. Per-portfolio "off" is ROW PRESENCE, not a per-row flag.
3. DROP the P4 ``strategy_subscriptions`` (venue, symbol, timeframe) table — it modelled the
   wrong edge: its columns are derivable from (the live venue, ``config_json.tickers``,
   ``config_json.timeframe``) and its only unique job (a symbol→strategies reverse index) is
   an in-memory dict built at rehydrate. ``tickers`` stay IN ``config_json`` (D-06).

The table stays named ``strategy_registry`` (D-18) — catalog = types (code), registry =
registered instances (DB); no rename, no migration cost.

**THE A1 GUARD (T-10-08).** ``upgrade()`` REFUSES to drop ``strategy_subscriptions`` when the
table holds rows: it counts FIRST and raises naming the row count, before any destructive op.
RESEARCH A1 asserted "the tables are empty in every deployed DB" — but that is a DB-STATE
claim that could NOT be verified from source. The store has no production writer today (high
confidence the claim holds), yet a silent destructive drop on a wrong assumption is
UNRECOVERABLE. So this migration applies the house rule — loud rejection over a silent
no-op — to a destructive schema op: count, then refuse loudly rather than destroy data on an
unverifiable assumption.

Derived from the ``build_strategy_registry_tables`` registrar
(``itrader/storage/strategy_registry_store.py``) — the SINGLE SOURCE OF TRUTH that the
test-path ``create_all`` and this deploy-path migration both reproduce (D-11); a divergence
here silently splits the test-path and prod schemas.

Chained (NOT branched) onto ``system_stats`` — the MEASURED chain head — so the migration
order stays linear and there is exactly ONE head. NOTE: ``10-CONTEXT.md`` says the chain ends
at ``strategy_registry``; that is STALE — two revisions (``module_config``, ``system_stats``)
landed after it. The full chain is
``... → venue_config → strategy_registry → module_config → system_stats →
p10_strategy_portfolio_subs``.

No custom-type import is needed here (Pitfall 2/8): every column this migration adds or
creates is a plain ``sa.String`` — the spine's ``UtcIsoText`` / ``json_variant`` columns are
untouched on the existing ``strategy_registry`` table.

Revision ID: p10_strategy_portfolio_subs
Revises: system_stats
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "p10_strategy_portfolio_subs"
down_revision: Union[str, Sequence[str], None] = "system_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _refuse_if_subscriptions_hold_data() -> None:
    """A1 GUARD (T-10-08) — raise rather than drop a ``strategy_subscriptions`` with rows.

    Runs BEFORE any destructive op. Parameter-free count via the migration's own bind.
    """
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM strategy_subscriptions")
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"REFUSING to drop 'strategy_subscriptions': the table holds {count} row(s). "
            "This migration (D-06) drops the table on the assumption it is empty in every "
            "deployed DB — an assumption that could not be verified from source, and a "
            "wrong drop is unrecoverable. Inspect the rows "
            "(SELECT * FROM strategy_subscriptions), migrate or archive anything you need "
            "(its (venue, symbol, timeframe) data is derivable from the live venue + "
            "config_json.tickers + config_json.timeframe), then DELETE the rows and re-run "
            "'alembic upgrade head'."
        )


def upgrade() -> None:
    """Add ``strategy_type``, create the portfolio-subscription child, drop the P4 table."""
    # 1. A1 guard FIRST — before any destructive op (T-10-08).
    _refuse_if_subscriptions_hold_data()

    # 2. Non-null ADD COLUMN needs a default to satisfy any EXISTING strategy_registry row
    # (the guard above counts the CHILD table, so it does not prove the parent is empty).
    # Backfilled rows land as 'UNKNOWN', which rehydrate quarantines loudly (D-19) rather
    # than silently mis-instantiating. The default is then dropped so the column matches the
    # registrar, which declares NO server_default. batch_alter_table: SQLite cannot ALTER a
    # column in place (the store's test path runs on SQLite; the migration test asserts this).
    op.add_column(
        "strategy_registry",
        sa.Column(
            "strategy_type", sa.String(), nullable=False, server_default="UNKNOWN"
        ),
    )
    with op.batch_alter_table("strategy_registry") as batch_op:
        batch_op.alter_column("strategy_type", server_default=None)

    # 3. The portfolio fan-out edge. Column types match build_strategy_registry_tables
    # exactly (the registrar is the single source of truth). portfolio_id is String, NOT
    # Uuid: Strategy.subscribed_portfolios is typed list[PortfolioId | int].
    op.create_table(
        "strategy_portfolio_subscriptions",
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("portfolio_id", sa.String(), nullable=False),
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
    )

    # 4. Drop the redundant P4 child (guarded empty above).
    op.drop_table("strategy_subscriptions")


def downgrade() -> None:
    """The exact inverse, in reverse order — restore the P4 table, undo the D-06 adds."""
    # Restore the P4 (venue, symbol, timeframe) child with its original composite-PK shape
    # (copied from migrations/versions/strategy_registry.py). Data is NOT restored: the
    # upgrade only ever ran against an empty table (the A1 guard).
    op.create_table(
        "strategy_subscriptions",
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("venue", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["strategy_name"],
            ["strategy_registry.strategy_name"],
            name=op.f("fk_strategy_subscriptions_strategy_name_strategy_registry"),
        ),
        sa.PrimaryKeyConstraint(
            "strategy_name",
            "venue",
            "symbol",
            "timeframe",
            name=op.f("pk_strategy_subscriptions"),
        ),
    )
    op.drop_table("strategy_portfolio_subscriptions")
    with op.batch_alter_table("strategy_registry") as batch_op:
        batch_op.drop_column("strategy_type")
