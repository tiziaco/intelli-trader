"""module config

Finalize Plan 03's module-owned durable config surface into the Alembic chain (D-25).
Plan 03 added the metadata registrars (schema-pure — no runtime ``create_all``) but
DEFERRED the migration to this plan (the phase's migration-owner). This revision performs
the two schema changes the mutation-path + restart-layering actually need:

* CREATE ``order_config`` — the NEW cardinality-1 order-scope config table (constant
  single-row String ``id`` PK, portable JSON ``config_json`` blob, ``updated_at``),
  reproducing ``build_order_config_table``
  (``itrader/order_handler/storage/sql_storage.py``) EXACTLY. Order config is a GLOBAL
  singleton today; the dedicated table leaves room to expand to a per-portfolio/account
  key later without touching the account-state carrier.
* ALTER ``portfolio_account_state`` ADD the nullable ``config_json`` COLUMN — the
  portfolio-scope config rides the EXISTING single-row-per-``portfolio_id`` account-state
  table (NO new ``portfolio_config`` table), reproducing Plan 03's extended
  ``build_portfolio_tables`` (``itrader/portfolio_handler/storage/models.py``). Nullable +
  no-default so ``ADD COLUMN`` is natively portable on SQLite + Postgres, and an
  account-state row can exist with no config (and a config can be saved before any fill).

``downgrade`` reverses in dependency order: drop the ``config_json`` column FIRST, then
drop the ``order_config`` table.

Chained (NOT branched) onto ``strategy_registry`` (the prior single head) so the migration
order stays linear: ``down_revision="strategy_registry"``. The new head is ``system_stats``
(chained after this revision).

Revision ID: module_config
Revises: strategy_registry
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Hand-authored custom-type import (Pitfall 2/8): the ``updated_at`` column uses the spine's
# ``UtcIsoText`` TypeDecorator; autogenerate omits this import, so it is added by hand so
# ``alembic upgrade head`` resolves the name instead of raising ``NameError``.
import itrader.storage.types

# revision identifiers, used by Alembic.
revision: str = "module_config"
down_revision: Union[str, Sequence[str], None] = "strategy_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ``order_config`` + ADD ``portfolio_account_state.config_json`` (D-25)."""
    op.create_table(
        "order_config",
        # Constant single-row String PK (cardinality-1) — NOT a UUIDv7 surrogate.
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_config")),
    )
    # ADD the nullable portfolio-scope config carrier to the EXISTING account-state table
    # (D-25 — NO new portfolio_config table). Nullable + no-default → natively portable
    # ADD COLUMN on both SQLite and Postgres.
    op.add_column(
        "portfolio_account_state",
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Reverse in dependency order — drop the added column FIRST, then ``order_config``."""
    op.drop_column("portfolio_account_state", "config_json")
    op.drop_table("order_config")
