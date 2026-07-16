"""system stats

Add the durable append-only engine-operational stats series — the ``system_stats`` table
(RTCFG-06, D-17/D-18). The ONE new table this phase's read-model needs: an append-only
time-series of the engine-operational counters no domain store owns (P7 throttle-breach
counter, error counts by severity, event-bus queue depth, uptime, connector/stream
health). It holds NOTHING a domain store already persists (D-17 — NO entity duplication)
and only NON-sensitive counters (V7).

Clones the ``equity_snapshots`` append-only shape (D-18): a ``seq`` Integer PK with
``autoincrement=False`` (the engine writes the monotonic seq — no second ID scheme) and a
``UtcIsoText`` business ``timestamp`` (D-07). Derived from the ``build_system_stats_table``
registrar (``itrader/storage/system_stats_store.py``) — the single source of truth the
test-path ``create_all`` and this deploy-path migration both reproduce (D-11/D-18).

Chained (NOT branched) onto ``module_config`` so the migration order stays linear:
``down_revision="module_config"``. This is the new single head (the full P9 schema chain is
``strategy_registry → module_config → system_stats``).

Revision ID: system_stats
Revises: module_config
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Hand-authored custom-type import (Pitfall 2/8): the ``timestamp`` column uses the spine's
# ``UtcIsoText`` TypeDecorator; autogenerate omits this import, so it is added by hand so
# ``alembic upgrade head`` resolves the name instead of raising ``NameError``.
import itrader.storage.types

# revision identifiers, used by Alembic.
revision: str = "system_stats"
down_revision: Union[str, Sequence[str], None] = "module_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the append-only ``system_stats`` counter series (seq PK, no autoincrement)."""
    op.create_table(
        "system_stats",
        # Engine-written monotonic seq PK (D-18) — autoincrement=False keeps the
        # single-UUIDv7 / no-second-ID-scheme rule (the store writes seq, not the DB).
        sa.Column("seq", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("timestamp", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.Column("throttle_breach_count", sa.Integer(), nullable=False),
        sa.Column("error_count_warning", sa.Integer(), nullable=False),
        sa.Column("error_count_error", sa.Integer(), nullable=False),
        sa.Column("error_count_critical", sa.Integer(), nullable=False),
        sa.Column("queue_depth", sa.Integer(), nullable=False),
        sa.Column("uptime_seconds", sa.Numeric(), nullable=False),
        sa.Column("connector_up", sa.Boolean(), nullable=False),
        sa.Column("stream_up", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_system_stats")),
    )


def downgrade() -> None:
    """Downgrade schema — drop the ``system_stats`` table."""
    op.drop_table("system_stats")
