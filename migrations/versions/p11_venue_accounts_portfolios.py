"""venue accounts + portfolio definitions

Create the two W1-schema-boundary tables of Phase 11 (MPORT-02, D-28/D-29):

1. ``venue_accounts`` — one row per ``(venue_name, account_id)`` COMPOSITE natural key
   (D-01), carrying the D-05 three-lifecycle split ``secret_ref`` (operator-rotated
   POINTER at a credential, never the credential itself — D-02/T-11-01) / ``venue_uid``
   (engine-written trust-on-first-use, D-04, written by plan 11-04) / ``config_json``
   (operator-authored connection config), plus the typed ``enabled`` Boolean and the
   ``updated_at`` UTC-isoformat business timestamp.
2. ``portfolios`` — the DEFINITION row that seven portfolio-scoped child tables never had
   (D-07). ``portfolio_id`` is a ``Uuid`` matching ``orders.portfolio_id`` and
   ``portfolio_account_state.portfolio_id`` (the handle stays the UUIDv7 the id generator
   mints; it is never re-schemed). There is deliberately NO ``exchange`` column: a
   portfolio's venue IS the ``venue_name`` half of its account reference, and storing it a
   second time creates two sources of truth with no tiebreaker.

**CREATE ORDER IS LOAD-BEARING (D-29).** ``venue_accounts`` is created FIRST because
``portfolios`` carries a composite ``ForeignKeyConstraint(['venue_name','account_id'])``
referencing it; the reverse order fails on an unresolvable FK. ``downgrade()`` is the exact
inverse in reverse order — ``portfolios`` (the child) is dropped before its parent.

This revision is PURE DDL: it creates two brand-new tables and touches no existing data, so
it needs no guard. The DESTRUCTIVE half of this phase's schema work (the B2 ``String`` ->
``Uuid`` type change on ``strategy_portfolio_subscriptions`` and the D-09 config data move)
lives in the NEXT revision, ``p11_b2_uuid_fk_config_move``, behind its own refuse-if-non-empty
guard. Splitting "create new tables" from "modify existing data" puts the risk and the guards
where they belong, under separate downgrade paths (D-29).

Derived from the ``build_venue_accounts_table`` (``itrader/storage/venue_account_store.py``)
and ``build_portfolio_definition_tables``
(``itrader/storage/portfolio_definition_store.py``) registrars — the SINGLE SOURCE OF TRUTH
that the test-path ``create_all`` and this deploy-path migration both reproduce (D-11); a
divergence here silently splits the test-path and prod schemas, which is exactly what the
create_all-vs-migration parity gate exists to catch.

Chained (NOT branched) onto ``p10_strategy_portfolio_subs`` — the MEASURED chain head
(``alembic heads`` prints it as the single head) — so the migration order stays linear and
there is exactly ONE head.

Hand-authored custom-type import (Pitfall 2): the ``updated_at`` columns use the spine's
``UtcIsoText`` TypeDecorator, which autogenerate omits — the module-level
``import itrader.storage.types`` below is the chain's established convention for that
(``venue_config.py``, ``system_stats.py``). The STORE modules are deliberately NOT imported:
that would put their runtime dependencies on the migration import path.

Revision ID: p11_venue_accounts_portfolios
Revises: p10_strategy_portfolio_subs
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Hand-authored custom-type import (Pitfall 2) — resolves ``UtcIsoText`` at upgrade time.
import itrader.storage.types

# revision identifiers, used by Alembic.
revision: str = "p11_venue_accounts_portfolios"
down_revision: Union[str, Sequence[str], None] = "p10_strategy_portfolio_subs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``venue_accounts`` THEN ``portfolios`` — the FK direction forces the order."""
    # 1. The PARENT. Composite natural PK (venue_name, account_id) — D-01, no surrogate id.
    op.create_table(
        "venue_accounts",
        sa.Column("venue_name", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        # D-02/D-05 — a POINTER at the credential, never the credential. NULL for the D-06
        # paper account, which has nothing to point at.
        sa.Column("secret_ref", sa.String(), nullable=True),
        # D-04/D-05 — engine-written trust-on-first-use; NULL until first observation.
        sa.Column("venue_uid", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint(
            "venue_name", "account_id", name=op.f("pk_venue_accounts")
        ),
    )

    # 2. The CHILD. Created second: its composite FK references venue_accounts, so the
    # parent must already exist (D-29 — reversing these two statements fails on the FK).
    op.create_table(
        "portfolios",
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        # The (venue_name, account_id) account reference — D-01's pair. NOT NULL on both
        # halves (D-06) is what makes the FK unconditional and the unique index PLAIN.
        sa.Column("venue_name", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        # Money — Numeric so it reads back as Decimal, never float (D-04).
        sa.Column("initial_cash", sa.Numeric(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        # D-09's destination for the per-portfolio config blob; nullable because
        # load_config() explicitly handles None.
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        # Composite reference — the TABLE-level form is REQUIRED for a two-column key.
        sa.ForeignKeyConstraint(
            ["venue_name", "account_id"],
            ["venue_accounts.venue_name", "venue_accounts.account_id"],
            name=op.f("fk_portfolios_venue_name_venue_accounts"),
        ),
        sa.PrimaryKeyConstraint("portfolio_id", name=op.f("pk_portfolios")),
        # D-14 / T-11-02 — PLAIN (never partial, conditional or deferrable). Two portfolios
        # sharing one venue account would conflate buying power the venue cannot split back
        # out; at the DB layer this also binds out-of-band writers.
        sa.UniqueConstraint(
            "venue_name", "account_id", name=op.f("uq_portfolios_venue_name")
        ),
    )


def downgrade() -> None:
    """The exact inverse in reverse order — the CHILD drops before its PARENT."""
    op.drop_table("portfolios")
    op.drop_table("venue_accounts")
