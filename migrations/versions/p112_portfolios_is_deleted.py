"""portfolios.is_deleted + partial unique index over the LIVE rows

Phase 11.2's ONLY schema migration (D-32). Two changes to ``portfolios``:

1. ADD ``is_deleted`` (``Boolean``, NOT NULL) — the second of D-32's two lifecycle flags.
   ``enabled`` means **PAUSED** (the portfolio KEEPS its venue account, so re-enabling it
   always works); ``is_deleted`` means **RETIRED** (the portfolio RELEASES its
   ``(venue_name, account_id)`` pair so a successor can take the account over). Deletion is
   SOFT — the row, its history and its seven child tables all survive.

2. REPLACE the plain ``UNIQUE(venue_name, account_id)`` constraint with a PARTIAL unique
   index over the live rows only: ``uq_portfolios_live_account ... WHERE NOT is_deleted``.

**Why partial is still the same guarantee.** The original D-14 rationale is about
**SIMULTANEOUS** sharing: two portfolios trading one venue account at once would conflate
buying power the venue cannot split back out (T-11-02). The partial index refuses that case
unchanged — both rows would be live and therefore both indexed, and a merely PAUSED portfolio
is still live for this purpose. What becomes possible is only **SEQUENTIAL** reuse, after a
retirement. The index is self-enforcing in both directions: un-retiring a row while a
successor holds the pair violates it exactly as a fresh insert would. Uniqueness also remains
a DATABASE constraint rather than an application check, so the "binds out-of-band writers"
half of the original rationale survives intact.

**BOTH dialect predicates are emitted** (``postgresql_where`` and ``sqlite_where``). The test
suite runs SQLite and production runs Postgres; a single-dialect predicate would silently
degrade to a PLAIN index on the other engine, and a degradation on the SQLite side would be
invisible to every test in the tree.

Derived from the ``build_portfolio_definition_tables``
(``itrader/storage/portfolio_definition_store.py``) registrar — the SINGLE SOURCE OF TRUTH
that the test-path ``create_all`` and this deploy-path migration both reproduce (D-11); a
divergence here silently splits the test-path and prod schemas, which is exactly what the
create_all-vs-migration parity gate exists to catch. In particular the registrar declares NO
``server_default`` on ``is_deleted``: the one added below exists ONLY to backfill existing
rows and is dropped again in the same batch, so both sides agree.

The constraint being dropped was created NAMED by ``p11_venue_accounts_portfolios.py``
(``name=op.f("uq_portfolios_venue_name")``) even though the registrar declared it UNNAMED —
the name comes from the spine's ``NAMING_CONVENTION`` (``migrations/env.py``). It must
therefore be dropped BY THAT NAME.

No data migration or backfill beyond the ``server_default``: the deployment is confirmed
greenfield and a backfill was explicitly declined.

Chained (NOT branched) onto ``p11_b2_uuid_fk_config_move`` — the MEASURED chain head
(``alembic heads`` prints it as the single head) — so the migration order stays linear and
there is exactly ONE head.

``op.batch_alter_table`` is the only mechanism used for the constraint/index swap: SQLite
cannot ALTER a constraint in place, and ``render_as_batch=True`` is already configured in
BOTH ``migrations/env.py`` configure paths. No ALTER TABLE string is hand-written.

Revision ID: p112_portfolios_is_deleted
Revises: p11_b2_uuid_fk_config_move
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "p112_portfolios_is_deleted"
down_revision: Union[str, Sequence[str], None] = "p11_b2_uuid_fk_config_move"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The partial-index predicate, as a SQLAlchemy expression rather than a raw string, so ONE
# object serves both dialect kwargs and the two dialects cannot drift apart. Mirrors the
# registrar's ``~portfolios.c.is_deleted``.
_LIVE_ROWS_ONLY = ~sa.column("is_deleted", sa.Boolean())


def upgrade() -> None:
    """Add ``is_deleted``, then swap the plain unique constraint for the partial index."""
    # 1. The column. NOT NULL needs a default to satisfy any EXISTING portfolios row — the
    # deployment is greenfield, but a NOT NULL ADD COLUMN against a non-empty table would
    # fail outright and this migration must not depend on that assumption holding.
    op.add_column(
        "portfolios",
        sa.Column(
            "is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    with op.batch_alter_table("portfolios") as batch_op:
        # 2. Drop the backfill default so the deployed schema matches the registrar, which
        # declares NO server_default. A default left on only one side is a silent
        # test-path/prod split.
        batch_op.alter_column("is_deleted", server_default=None)
        # 3. Out with the PLAIN constraint (created NAMED by p11_venue_accounts_portfolios) ...
        batch_op.drop_constraint(
            op.f("uq_portfolios_venue_name"), type_="unique"
        )
        # 4. ... in with the PARTIAL unique index over the LIVE rows (D-32).
        batch_op.create_index(
            op.f("uq_portfolios_live_account"),
            ["venue_name", "account_id"],
            unique=True,
            postgresql_where=_LIVE_ROWS_ONLY,
            sqlite_where=_LIVE_ROWS_ONLY,
        )


def downgrade() -> None:
    """The exact inverse in reverse order — index out, plain constraint back, column dropped.

    DESTRUCTIVE BEYOND THE SCHEMA (why D-32 is rated one-way): restoring the PLAIN constraint
    re-binds every ``(venue_name, account_id)`` pair to the FIRST portfolio that ever used it.
    Any deployment that has already retired-and-reused an account will either fail this
    downgrade on a duplicate pair or, once ``is_deleted`` is dropped, lose the distinction
    between the retired portfolio and its live successor entirely — the exact defect D-32
    exists to remove. Recovering forward needs a second migration, not this one.
    """
    with op.batch_alter_table("portfolios") as batch_op:
        batch_op.drop_index(op.f("uq_portfolios_live_account"))
        batch_op.create_unique_constraint(
            op.f("uq_portfolios_venue_name"), ["venue_name", "account_id"]
        )
    op.drop_column("portfolios", "is_deleted")
