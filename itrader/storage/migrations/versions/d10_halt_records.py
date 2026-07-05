"""d10 halt records

Add the durable ``halt_records`` table (D-10 / ARCH-4 Layer 2). Phase 05.1 D-05 landed an
IN-PROCESS ``HALTED`` latch, but a supervised auto-restart builds a FRESH ``LiveTradingSystem``
whose in-process status is ``STOPPED`` — so a breaker-class halt would be silently cleared.
This durable record on the operational spine is what latches across a restart: ``halt()``
persists an unresolved record, ``start()`` refuses RUNNING while one exists, and
``reset_halt()`` resolves it.

Secret-scrub (V7 / T-05.2-18): the table carries ONLY the machine-readable ``reason`` literal,
the ``created_at`` timestamp, and a ``resolved`` flag — deliberately NO free-form exception /
payload column, so ``str(exc)`` or a connector payload can never leak into persistence.

Chained (NOT branched) onto the existing operational head so the migration order stays linear
(T-05.2-20): ``down_revision="hl5_transaction_venue_trade_id"``.

Revision ID: d10_halt_records
Revises: hl5_transaction_venue_trade_id
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d10_halt_records"
down_revision: Union[str, Sequence[str], None] = "hl5_transaction_venue_trade_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create the durable ``halt_records`` table (secret-scrub schema)."""
    op.create_table(
        "halt_records",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_halt_records")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``halt_records`` table."""
    op.drop_table("halt_records")
