"""SQL backend selection — ``SqlSettings`` (SPINE-01, D-02/D-12/D-15).

A minimal Pydantic model that selects the SQL driver *by config, not code* and builds the
engine URL. Mirrors the ``config/order.py`` analog (``BaseModel`` + ``ConfigDict(extra="forbid")``
+ a ``default()`` classmethod + a ``(str, Enum)`` config-domain enum). The surface is
deliberately minimal this milestone — driver enum + URL builder only; write-through /
retention knobs are deferred to a later phase (D-12).

Credential discipline (FL-06 / T-01-03): on the Postgres arm the URL is sourced from
``Settings.database_url.get_secret_value()`` — the single canonical secret seam. ``SecretStr``
masks ``repr``/``str``/``model_dump``; the resolved URL is never logged.

Import-side-effect trap (Pitfall 8 / T-01-04): ``Settings.database_url`` is required-no-default,
so ``Settings()`` raises ``ValidationError`` when ``ITRADER_DATABASE_URL`` is unset. This module
therefore NEVER instantiates ``Settings()`` at import time — it is resolved lazily inside
``engine_url()`` on the Postgres arm only, so the SQLite/backtest path stays env-free.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict

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

    def engine_url(self, settings: Settings | None = None) -> str:
        """Build the SQLAlchemy engine URL for the selected driver.

        On the Postgres arm the URL is resolved lazily from the ``Settings`` secret seam
        (``database_url.get_secret_value()``) — ``Settings()`` is constructed here, never at
        import. Every other (SQLite-family) arm builds a fully local URL with NO env access.

        On the Postgres arm ``driver`` selects this branch ONLY: the env URL's scheme/driver
        is authoritative and is NOT validated against the enum member (IN-02).
        """
        if self.driver is SqlDriver.POSTGRESQL_PSYCOPG2:
            # IN-02 — on the Postgres arm ``driver`` is a BRANCH SELECTOR ONLY: the returned
            # URL is ``Settings.database_url`` VERBATIM, so its scheme/driver (e.g. whether it
            # carries ``+psycopg2``) is whatever ``ITRADER_DATABASE_URL`` supplies — the env
            # URL is authoritative and is NOT reconciled against this enum member (a mismatched
            # env scheme is honored as-is). Contrast the SQLite-family arm below, which builds
            # the URL from ``driver.value`` itself.
            # BaseSettings populates required fields from the ITRADER_* env at runtime;
            # mypy (via pydantic's dataclass_transform) treats database_url as a required
            # ctor arg, so the no-arg env-driven construction needs a narrow ignore.
            resolved = settings or Settings()  # type: ignore[call-arg]
            return resolved.database_url.get_secret_value()
        return f"{self.driver.value}:///{self.database}"
