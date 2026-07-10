"""system store

Add the durable ``system_store`` table — the cardinality-1 runtime-config KV spine
(STORE-01, D-06/D-08). One JSON blob per NATURAL ``key`` string (no UUIDv7 surrogate,
no autoincrement): two upserts on the same key leave ONE row (cardinality-1 by the
``key`` PK). Derived from the ``build_system_store_table`` registrar
(``itrader/storage/system_store.py``) — the single source of truth the test-path
``create_all`` and this deploy-path migration both reproduce (D-11).

Chained (NOT branched) onto the current operational head so the migration order stays
linear: ``down_revision="d10_halt_records"``.

Revision ID: system_store
Revises: d10_halt_records
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Hand-authored custom-type import: the ``updated_at`` column uses the spine's
# ``UtcIsoText`` TypeDecorator, rendered by its fully-qualified name below. Autogenerate
# does NOT emit this import (the standard custom-type gotcha — Pitfall 2), so it is added
# by hand so ``alembic upgrade head`` resolves the name instead of raising ``NameError``.
import itrader.storage.types

# revision identifiers, used by Alembic.
revision: str = "system_store"
down_revision: Union[str, Sequence[str], None] = "d10_halt_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create the durable ``system_store`` KV table (D-06/D-08)."""
    op.create_table(
        "system_store",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column(
            "value_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_store")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``system_store`` table."""
    op.drop_table("system_store")
