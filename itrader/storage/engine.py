"""The shared SQL spine — ``SqlEngine`` (SPINE-02, D-01).

A single ``SqlEngine`` holds an Engine + a fresh MetaData and NOTHING else — no query
methods, no business logic, no cross-concern god base. Every storage concern *composes*
one ``SqlEngine`` by reference (has-a) rather than inheriting a shared ``SqlStorageBase``:
that base is deliberately ABSENT because it would collapse the per-concern ABC boundary the
seed rejects. The backend (driver/URL) is selected at wiring from ``SqlSettings`` — config,
not code (SPINE-01). The spine is post-loop / live-only; it adds zero per-tick code, so it
is structurally inert on the backtest hot loop (GATE-01).
"""

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine

from itrader.config.sql import SqlSettings


# NAMING_CONVENTION — the SQLAlchemy-standard constraint/index naming convention applied
# to the spine MetaData (research Pitfall 5 / A5). With it, ALL constraint and index names
# become EXPLICIT and DETERMINISTIC for every create_all consumer (results store, price
# store) AND for Plan-05 Alembic ``--autogenerate``, so the test-path ``create_all`` and the
# deploy-path autogenerate emit byte-IDENTICAL names. This module is the SINGLE SOURCE OF
# TRUTH for those names: ``migrations/env.py`` (Plan 05) imports this constant
# for the autogen MetaData. Cosmetic for existing consumers (names are simply made explicit),
# so GATE-01 inertness is preserved.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SqlEngine:
    """Shared SQL spine: a configured Engine + a fresh MetaData. No business logic.

    Parameters
    ----------
    settings:
        The driver-by-config selector; ``engine_url()`` yields the dialect URL passed to
        ``create_engine`` (SQLite research store / Postgres operational store).
    """

    def __init__(self, settings: SqlSettings) -> None:
        # WR-03 — provision the on-disk SQLite parent directory BEFORE create_engine: a
        # file-backed SQLite URL with a missing parent dir raises OperationalError on first
        # connect. No-op for :memory: and Postgres arms.
        settings.ensure_local_storage()
        self.engine: Engine = create_engine(settings.engine_url())
        # MetaData carries the stable NAMING_CONVENTION so test-path create_all and
        # deploy-path Alembic autogenerate (Plan 05) produce byte-identical constraint /
        # index names (research Pitfall 5 / A5).
        self.metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def dispose(self) -> None:
        """Dispose the engine and close all pooled connections.

        Lifecycle lives on the layer that OWNS the engine (WR-03): composing storage
        concerns must delegate here rather than each calling ``self.engine.dispose()`` on
        the shared engine, so one concern's shutdown never flushes the pool out from under
        the others.
        """
        self.engine.dispose()
