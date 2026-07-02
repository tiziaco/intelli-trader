"""p05 venue order id

Add the nullable ``venue_order_id`` column to the ``orders`` table (05-07,
RECON-05 / Open Question 3). The venue's order id is persisted on the order mirror
so a rehydrated bracket leg re-links CONFIDENTLY to a venue resting order across a
restart (venue-id-first match; symbol+side+price+qty fallback). Nullable so
backtest/paper orders (no venue id) are unaffected and the spot path stays
byte-exact.

Revision ID: p05_venue_order_id
Revises: 47f2b41f3ffe
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "p05_venue_order_id"
down_revision: Union[str, Sequence[str], None] = "47f2b41f3ffe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add the nullable ``venue_order_id`` column."""
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("venue_order_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema — drop the ``venue_order_id`` column."""
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("venue_order_id")
