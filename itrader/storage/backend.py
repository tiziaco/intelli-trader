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
        self.engine: Engine = create_engine(settings.engine_url())
        self.metadata = MetaData()
