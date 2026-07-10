"""hl5 transaction venue trade id

Add the nullable ``venue_trade_id`` column to the ``transactions`` table (CR-01,
fill-dedup tail). The venue's own trade id (FIX ExecID / Nautilus TradeId) carried
on the ``Transaction`` struct is persisted on the durable settlement record so the
live recon/dedup path keeps its idempotency key after a restart. Nullable with no
backfill: historical rows and every backtest/simulated (oracle-dark) transaction are
legitimately NULL, and the spot path stays byte-exact.

Follow-up (deliberately NOT in this migration): a partial UNIQUE index
``WHERE venue_trade_id IS NOT NULL`` would enforce venue-trade idempotency at the
schema level, but it is dialect-awkward across the sqlite-compat batch path +
Postgres. p05_venue_order_id set the precedent (plain nullable column, no unique);
mirror it here and leave the partial-UNIQUE constraint as an explicit follow-up.

Revision ID: hl5_transaction_venue_trade_id
Revises: p05_venue_order_id
Create Date: 2026-07-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "hl5_transaction_venue_trade_id"
down_revision: Union[str, Sequence[str], None] = "p05_venue_order_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add the nullable ``venue_trade_id`` column."""
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("venue_trade_id", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema — drop the ``venue_trade_id`` column."""
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_column("venue_trade_id")
