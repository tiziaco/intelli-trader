"""The shared SQL spine — ``SqlBackend`` (SPINE-02, D-01).

A single ``SqlBackend`` holds an Engine + a fresh MetaData and NOTHING else — no query
methods, no business logic, no cross-concern god base. Every storage concern *composes*
one ``SqlBackend`` by reference (has-a) rather than inheriting a shared ``SqlStorageBase``:
that base is deliberately ABSENT because it would collapse the per-concern ABC boundary the
seed rejects. The backend (driver/URL) is selected at wiring from ``SqlSettings`` — config,
not code (SPINE-01). The spine is post-loop / live-only; it adds zero per-tick code, so it
is structurally inert on the backtest hot loop (GATE-01).
"""

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine

from itrader.config.sql import SqlSettings


class SqlBackend:
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
        self.metadata = MetaData()

    def dispose(self) -> None:
        """Dispose the engine and close all pooled connections.

        Lifecycle lives on the layer that OWNS the engine (WR-03): composing storage
        concerns must delegate here rather than each calling ``self.engine.dispose()`` on
        the shared backend, so one concern's shutdown never flushes the pool out from under
        the others.
        """
        self.engine.dispose()
