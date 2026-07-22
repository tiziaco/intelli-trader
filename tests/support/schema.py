"""Shared test-side schema provisioning — the single ``provision_schema`` seam (WR-03/D-14).

The seven DURABLE stores no longer self-create their schema in ``__init__`` (WR-03): in
production the durable operational schema is Alembic-owned end-to-end (D-14), so a runtime
store object never contradicts that by calling ``create_all``. Tests provision explicitly
instead, through this ONE helper.

This is the LIGHT variant per D-14: ``metadata.create_all(checkfirst=True)`` — fast and
Dockerless. It is deliberately NOT ``alembic upgrade head``: migration fidelity is already
covered by ``tests/integration/storage/test_migrations.py`` (which runs the real chain on
both SQLite and testcontainers Postgres), so running the chain per unit test is overkill.

CONTRACT — call ``provision_schema(sql_engine)`` AFTER the store is constructed (so the
store's ``build_*`` registrar has registered its tables on the shared ``metadata``) and
BEFORE the first query. ``checkfirst=True`` makes the reopen / restart case a clean no-op,
so provisioning twice against the same live engine is safe.

Import-light: the ``SqlEngine`` annotation is under a ``TYPE_CHECKING`` guard (no top-level
``itrader`` import), so ``tests.support`` stays collectable early without pulling SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from itrader.storage import SqlEngine

_SEED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def provision_schema(sql_engine: "SqlEngine") -> None:
    """Create every table registered on ``sql_engine.metadata`` (light D-14 variant).

    Calls ``metadata.create_all(engine, checkfirst=True)`` — the fast, Dockerless test-side
    provisioning path. Must be called AFTER store construction (tables registered by the
    store's ``build_*`` registrar) and BEFORE the first query; ``checkfirst=True`` makes a
    reopen/restart a clean no-op.
    """
    sql_engine.metadata.create_all(sql_engine.engine, checkfirst=True)


def seed_portfolio_definitions(
    sql_engine: "SqlEngine", portfolio_ids: Iterable[uuid.UUID]
) -> None:
    """Insert a ``portfolios`` definition row (plus its account parent) per id.

    B2 (Phase 11, 11-03): ``strategy_portfolio_subscriptions.portfolio_id`` is a ``Uuid``
    column with an ``ON DELETE CASCADE`` foreign key to ``portfolios.portfolio_id``, so a
    test that subscribes a strategy to a portfolio now needs that portfolio to EXIST — an
    unparented id raises ``IntegrityError`` (the SQLite ``PRAGMA foreign_keys=ON`` hook makes
    this bite on both dialects). This helper is the one place that knows the minimum row shape.

    D-14 pins ``(venue_name, account_id)`` UNIQUE across portfolios, so each id gets its OWN
    ``venue_accounts`` row under a shared ``paper`` venue; the accounts are inserted FIRST
    because ``portfolios`` carries an unconditional composite FK onto them.

    Call AFTER ``provision_schema``. Idempotent per id, so a dispose→reopen restart test can
    call it again over the same file.
    """
    metadata = sql_engine.metadata
    accounts = metadata.tables["venue_accounts"]
    portfolios = metadata.tables["portfolios"]
    with sql_engine.engine.begin() as connection:
        for portfolio_id in portfolio_ids:
            existing = connection.execute(
                portfolios.select().where(portfolios.c.portfolio_id == portfolio_id)
            ).first()
            if existing is not None:
                continue
            account_id = str(portfolio_id)
            connection.execute(accounts.insert(), [{
                "venue_name": "paper", "account_id": account_id, "secret_ref": None,
                "venue_uid": None, "enabled": True, "config_json": {},
                "updated_at": _SEED_AT,
            }])
            connection.execute(portfolios.insert(), [{
                "portfolio_id": portfolio_id, "name": account_id, "venue_name": "paper",
                "account_id": account_id, "initial_cash": Decimal("10000"),
                "enabled": True, "config_json": None, "updated_at": _SEED_AT,
            }])
