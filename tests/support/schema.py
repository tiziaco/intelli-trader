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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from itrader.storage import SqlEngine


def provision_schema(sql_engine: "SqlEngine") -> None:
    """Create every table registered on ``sql_engine.metadata`` (light D-14 variant).

    Calls ``metadata.create_all(engine, checkfirst=True)`` — the fast, Dockerless test-side
    provisioning path. Must be called AFTER store construction (tables registered by the
    store's ``build_*`` registrar) and BEFORE the first query; ``checkfirst=True`` makes a
    reopen/restart a clean no-op.
    """
    sql_engine.metadata.create_all(sql_engine.engine, checkfirst=True)
