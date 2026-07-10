"""venue config

Add the durable per-venue config store — the ``venue_store`` table (STORE-02, D-05/D-06).
One row per NATURAL ``venue_name`` (no UUIDv7 surrogate) with a typed ``enabled`` Boolean
(queryable — serves ``list_enabled``) alongside the portable JSON ``config_json`` (D-08).
Derived from the ``build_venue_store_table`` registrar (``itrader/storage/venue_store.py``)
— the single source of truth the test-path ``create_all`` and this deploy-path migration
both reproduce (D-11).

NOTE — the revision slug (``venue_config``) is NOT the table name (Pitfall 5): this
revision builds the table named ``venue_store``.

Chained (NOT branched) onto ``system_store`` so the migration order stays linear:
``down_revision="system_store"``.

Revision ID: venue_config
Revises: system_store
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Hand-authored custom-type import (Pitfall 2): the ``updated_at`` column uses the spine's
# ``UtcIsoText`` TypeDecorator; autogenerate omits this import, so it is added by hand so
# ``alembic upgrade head`` resolves the name instead of raising ``NameError``.
import itrader.storage.types

# revision identifiers, used by Alembic.
revision: str = "venue_config"
down_revision: Union[str, Sequence[str], None] = "system_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create the durable ``venue_store`` table (slug ≠ table name)."""
    op.create_table(
        "venue_store",
        sa.Column("venue_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("venue_name", name=op.f("pk_venue_store")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``venue_store`` table."""
    op.drop_table("venue_store")
