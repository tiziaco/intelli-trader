"""SQL backend selection — ``SqlSettings`` (SPINE-01, D-02/D-12/D-15).

A minimal Pydantic model that selects the SQL driver *by config, not code* and builds the
engine URL. Mirrors the ``config/order.py`` analog (``BaseModel`` + ``ConfigDict(extra="forbid")``
+ a ``default()`` classmethod + a ``(str, Enum)`` config-domain enum). The surface is
deliberately minimal this milestone — driver enum + URL builder only; write-through /
retention knobs are deferred to a later phase (D-12).

Credential discipline (FL-06 / T-01-03): on the Postgres arm the URL is assembled from the
component-level ``Settings`` secret seam (``database_password.get_secret_value()`` plus the
host/port/user/name fields) — the single canonical secret seam. ``SecretStr`` masks
``repr``/``str``/``model_dump``; the resolved URL is never logged.

Connection model (260629-jh2 — supersedes IN-02): on the Postgres arm the URL is now PRIMARILY
assembled from component-level ``ITRADER_DATABASE_*`` env vars (host/port/user/name/password,
default port ``5544``) via ``sqlalchemy.URL.create`` — which URL-escapes special chars in the
password (``@ : / # ?`` → ``%40 %3A %2F %23 %3F``). ``ITRADER_DATABASE_URL`` remains an OPTIONAL
verbatim escape hatch: when set it is returned as-is (its scheme/driver authoritative), preserving
the original IN-02 path. This supersedes IN-02 ("driver is a branch selector only and the env URL
is authoritative"): the env URL is now the override, not the sole source.

Import-side-effect trap (Pitfall 8 / T-01-04): ``Settings.database_password`` is
required-no-default, so ``Settings()`` raises ``ValidationError`` when
``ITRADER_DATABASE_PASSWORD`` is unset. This module therefore NEVER instantiates ``Settings()``
at import time — it is resolved lazily inside ``engine_url()`` on the Postgres arm only, so the
SQLite/backtest path stays env-free.
"""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import URL

from itrader.config.settings import Settings


class SqlDriver(str, Enum):
    """SQLAlchemy driver tokens — the config-not-code backend switch (SPINE-01).

    Config-enum exception (CONVENTIONS.md): this config-domain ``(str, Enum)`` lives in
    ``config/`` by design (relocating to ``core/`` would invert the core->config dependency).
    Pydantic validates the field by value, so a raw string token coerces to the member.

    - ``SQLITE_PYSQLITE``     — the research-store default (in-process SQLite).
    - ``POSTGRESQL_PSYCOPG2`` — the operational store (creds from ``Settings``).
    - ``SQLITE_LIBSQL``       — Turso-ready SLOT only (D-15); the libSQL driver is NOT added
                                this milestone — the escape path is one URL change, zero code
                                change.
    """

    SQLITE_PYSQLITE = "sqlite+pysqlite"
    POSTGRESQL_PSYCOPG2 = "postgresql+psycopg2"
    SQLITE_LIBSQL = "sqlite+libsql"


class SqlSettings(BaseModel):
    """Minimal SQL backend selector (D-12).

    ``extra`` is forbidden so an unknown key is rejected (mass-assignment defense, T-04-01)
    rather than silently absorbed. The ``database`` field is the path / db-name used by the
    SQLite-family arms; it is ignored on the Postgres arm (a full URL is supplied there).
    """

    model_config = ConfigDict(extra="forbid")

    driver: SqlDriver = SqlDriver.SQLITE_PYSQLITE
    database: str = ":memory:"
    strict_persist: bool = False
    """Dump-failure policy for the results store (D-17).

    ``False`` (the default) → log-and-warn: a persist failure is logged
    (``self.logger.error(..., exc_info=True)``) and swallowed so a results-store dump
    can never abort the run. ``True`` → re-raise so the failure is surfaced. This knob
    lives on the store/settings, NOT on ``run()`` (the run loop stays persist-agnostic).
    """

    @classmethod
    def default(cls) -> "SqlSettings":
        """The backtest/research default — in-process SQLite, env-free."""
        return cls()

    @classmethod
    def results_default(cls) -> "SqlSettings":
        """The results-store default — an on-disk SQLite file (D-12).

        Unlike the generic ``default()`` (``:memory:``), the results store gets its OWN
        on-disk path that accumulates runs across invocations. ``default()`` stays
        ``:memory:`` so other consumers and the tests are unaffected.
        """
        return cls(database="output/results.db")

    def ensure_local_storage(self) -> None:
        """Create the parent directory for an on-disk SQLite database (WR-03).

        A file-backed SQLite URL (e.g. ``sqlite+pysqlite:///output/results.db``, the
        ``results_default()`` path) creates the database FILE but NOT its parent directory;
        on a fresh checkout / CI runner without ``output/`` the first ``create_engine``
        connection raises ``OperationalError: unable to open database file``. Creating the
        parent up front makes the documented results-store default self-provisioning.

        No-op on the Postgres arm (no local parent) and on the in-memory ``:memory:`` arm
        (no file). Idempotent (``exist_ok=True``).
        """
        if self.driver is SqlDriver.POSTGRESQL_PSYCOPG2:
            return
        if not self.database or self.database == ":memory:":
            return
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)

    def engine_url(self, settings: Settings | None = None) -> str:
        """Build the SQLAlchemy engine URL for the selected driver.

        On the Postgres arm the URL is resolved lazily from the ``Settings`` secret seam —
        ``Settings()`` is constructed here, never at import. Every other (SQLite-family) arm
        builds a fully local URL with NO env access.

        Postgres URL resolution (260629-jh2 — supersedes IN-02):
        1. If ``Settings.database_url`` is set, it is returned VERBATIM (the optional escape
           hatch — its scheme/driver authoritative, NOT reconciled against the enum member;
           this is the original IN-02 path, now demoted to an override).
        2. Otherwise the URL is ASSEMBLED from the component-level ``ITRADER_DATABASE_*`` fields
           (host/port/user/name/password, default port 5544) via ``sqlalchemy.URL.create``,
           which URL-escapes special chars in the password (an f-string would NOT escape
           ``@ : / # ?``).
        """
        if self.driver is SqlDriver.POSTGRESQL_PSYCOPG2:
            # BaseSettings populates required fields from the ITRADER_* env at runtime; mypy
            # (via pydantic's dataclass_transform) treats database_password as a required ctor
            # arg, so the no-arg env-driven construction needs a narrow ignore.
            resolved = settings or Settings()  # type: ignore[call-arg]
            # 260629-jh2 — supersedes IN-02: ITRADER_DATABASE_URL is now an OPTIONAL verbatim
            # escape hatch (scheme/driver authoritative, honored as-is). When unset, the URL is
            # assembled from the ITRADER_DATABASE_* components below (the primary source).
            if resolved.database_url is not None:
                return resolved.database_url.get_secret_value()
            return URL.create(
                drivername="postgresql+psycopg2",
                username=resolved.database_user,
                password=resolved.database_password.get_secret_value(),
                host=resolved.database_host,
                port=resolved.database_port,
                database=resolved.database_name,
            ).render_as_string(hide_password=False)
        return f"{self.driver.value}:///{self.database}"
