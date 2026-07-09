"""strategy registry

Add the durable strategy registry — TWO tables in one upgrade (STORE-03, D-04/D-06):

* ``strategy_registry`` — one row per strategy, keyed on the NATURAL ``strategy_name`` PK
  (config + enabled flag + updated_at). The durable identity is the strategy NAME, never
  the ephemeral runtime ``strategy_id`` UUIDv7.
* ``strategy_subscriptions`` — a normalized child, ``strategy_name`` FK'd on
  ``strategy_registry.strategy_name``, with a natural composite PK
  ``(strategy_name, venue, symbol, timeframe)`` — no surrogate UUID, no autoincrement.

Derived from the ``build_strategy_registry_tables`` registrar
(``itrader/storage/strategy_registry_store.py``) — the single source of truth the
test-path ``create_all`` and this deploy-path migration both reproduce (D-11). The
``downgrade`` drops the FK child (``strategy_subscriptions``) FIRST, then the parent.

Chained (NOT branched) onto ``venue_config`` so the migration order stays linear;
``strategy_registry`` is the new single head: ``down_revision="venue_config"``.

Revision ID: strategy_registry
Revises: venue_config
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
revision: str = "strategy_registry"
down_revision: Union[str, Sequence[str], None] = "venue_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create ``strategy_registry`` then its FK'd ``strategy_subscriptions``."""
    op.create_table(
        "strategy_registry",
        # Natural NAME PK (D-06) — NOT the ephemeral runtime strategy_id UUID.
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "config_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("strategy_name", name=op.f("pk_strategy_registry")),
    )
    op.create_table(
        "strategy_subscriptions",
        # FK back to the registry natural name key; part of the composite PK.
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


def downgrade() -> None:
    """Downgrade schema — drop the FK child ``strategy_subscriptions`` FIRST, then the parent."""
    op.drop_table("strategy_subscriptions")
    op.drop_table("strategy_registry")
