"""SQL backend selection — unified ``SqlSettings`` (SPINE-01, D-02/D-12/D-15).

ONE self-contained ``BaseSettings`` (``env_prefix="ITRADER_DATABASE_"``) that owns the SQL
connection surface end-to-end: the driver switch, the connection params, the conditional
Postgres validation, and the engine-URL builder. There is deliberately NO separate
``DatabaseSettings`` and no DB fields anywhere else in the config surface — a single cohesive
class is the whole DB config (260629-l0q — supersedes 260629-jh2, and transitively IN-02).

Connection model: on the Postgres arm the URL is PRIMARILY assembled from the component-level
``ITRADER_DATABASE_*`` env vars (host/port/user/name/password, default port ``5544`` — NOT
5432, which is taken by another DB on the target machine) via ``sqlalchemy.URL.create``, which
URL-escapes special chars in the password (``@ : / # ?`` → ``%40 %3A %2F %23 %3F``; an f-string
would NOT). ``ITRADER_DATABASE_URL`` is the OPTIONAL verbatim escape hatch: when set it is
returned as-is (its scheme/driver authoritative), preserving the original IN-02 path now demoted
to an override.

Fail-loud (M2-06 "no working secret defaults"): the ``_require_pg_credentials`` model_validator
raises ``pydantic.ValidationError`` when ``driver=POSTGRESQL`` is selected with neither a
password nor a verbatim url — so a live Postgres path can never silently ship a working default.
The fail-loud lives on a driver-conditional validator (not a required field), so the SQLite /
backtest path stays env-tolerant and deterministic: ``default()`` / ``results_default()`` pin
``driver``+``database`` via init kwargs (init outranks env), so the env can never flip them and
no password is ever needed.

Import-side-effect trap (Pitfall 8): this module NEVER constructs ``SqlSettings`` at import
time — construction (and thus the env-source pipeline + validator) runs only when a caller
explicitly instantiates it, so importing ``itrader.config.sql`` is inert and env-free.
"""

from enum import Enum
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

from itrader.core.exceptions import ConfigurationError


class SqlDriver(str, Enum):
    """SQLAlchemy driver tokens — the config-not-code backend switch (SPINE-01).

    Config-enum exception (CONVENTIONS.md): this config-domain ``(str, Enum)`` lives in
    ``config/`` by design (relocating to ``core/`` would invert the core->config dependency).
    Pydantic validates the field by value, so a raw string token coerces to the member.

    - ``SQLITE_PYSQLITE``     — the research-store default (in-process SQLite).
    - ``POSTGRESQL_PSYCOPG2`` — the operational store (creds from ``ITRADER_DATABASE_*``).
    - ``SQLITE_LIBSQL``       — Turso-ready SLOT only (D-15); the libSQL driver is NOT added
                                this milestone — the escape path is one URL change, zero code
                                change.
    """

    SQLITE_PYSQLITE = "sqlite+pysqlite"
    POSTGRESQL_PSYCOPG2 = "postgresql+psycopg2"
    SQLITE_LIBSQL = "sqlite+libsql"


class SqlSettings(BaseSettings):
    """Unified, self-contained SQL backend config (D-12).

    One class owns the whole DB surface: backend selection, connection params, conditional
    Postgres validation, and the engine-URL builder. ``extra`` is forbidden so an unknown key
    is rejected (mass-assignment defense, T-04-01) rather than silently absorbed. The
    ``database`` field is the path / db-name used by the SQLite-family arms; it is ignored on
    the Postgres arm (a component URL is assembled there).
    """

    model_config = SettingsConfigDict(env_prefix="ITRADER_DATABASE_", extra="forbid")

    # Backend selection — code config (pinned by default()/results_default() via init kwargs).
    driver: SqlDriver = SqlDriver.SQLITE_PYSQLITE
    database: str = ":memory:"  # sqlite path (ITRADER_DATABASE_DATABASE — rarely set)
    strict_persist: bool = False
    """Dump-failure policy for the results store (D-17).

    ``False`` (the default) → log-and-warn: a persist failure is logged
    (``self.logger.error(..., exc_info=True)``) and swallowed so a results-store dump
    can never abort the run. ``True`` → re-raise so the failure is surfaced. This knob
    lives on the store/settings, NOT on ``run()`` (the run loop stays persist-agnostic).
    """

    # Connection — env-driven (single-underscore names preserved; no .env migration).
    host: str = "localhost"  # ITRADER_DATABASE_HOST
    port: int = 5544  # ITRADER_DATABASE_PORT — NOT 5432 (5432 is taken)
    user: str = "postgres"  # ITRADER_DATABASE_USER
    name: str = "itrader"  # ITRADER_DATABASE_NAME (pg dbname)
    password: SecretStr | None = None  # ITRADER_DATABASE_PASSWORD
    url: SecretStr | None = None  # ITRADER_DATABASE_URL (verbatim escape hatch)

    @model_validator(mode="after")
    def _require_pg_credentials(self) -> "SqlSettings":
        """Fail loud when Postgres is selected without a password or a verbatim url.

        Guard-clause / early-exit: cheap exits first, raise last. Raises ``ValueError`` so
        pydantic wraps it into ``pydantic.ValidationError`` (M2-06 "no working secret
        defaults"). The SQLite-family arms early-return — they need no credentials.
        """
        if self.driver is not SqlDriver.POSTGRESQL_PSYCOPG2:
            return self
        if self.url is not None:
            return self
        if self.password is not None:
            return self
        raise ValueError(
            "Postgres requires ITRADER_DATABASE_PASSWORD or ITRADER_DATABASE_URL"
        )

    @classmethod
    def default(cls) -> "SqlSettings":
        """The backtest/research default — in-process SQLite, env-tolerant + deterministic.

        Pins ``driver``+``database`` via init kwargs (init outranks env) so the env can never
        flip the backtest store; no password is ever needed on the SQLite arm.
        """
        return cls(driver=SqlDriver.SQLITE_PYSQLITE, database=":memory:")

    @classmethod
    def results_default(cls) -> "SqlSettings":
        """The results-store default — an on-disk SQLite file (D-12).

        Unlike the generic ``default()`` (``:memory:``), the results store gets its OWN
        on-disk path that accumulates runs across invocations. ``default()`` stays
        ``:memory:`` so other consumers and the tests are unaffected. Pinned via init kwargs
        for the same env-tolerant determinism.
        """
        return cls(driver=SqlDriver.SQLITE_PYSQLITE, database="output/results.db")

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

    def engine_url(self) -> str:
        """Build the SQLAlchemy engine URL for the selected driver (self-contained).

        Guard-clause / early-exit (no cascading/nested if). Reads ``self.*`` only.

        Postgres URL resolution (260629-l0q — supersedes 260629-jh2 / IN-02):
        1. If ``url`` is set it is returned VERBATIM (the optional escape hatch — its
           scheme/driver authoritative, NOT reconciled against the enum member).
        2. Otherwise the URL is ASSEMBLED from the component ``ITRADER_DATABASE_*`` fields
           (host/port/user/name/password, default port 5544) via ``sqlalchemy.URL.create``,
           which URL-escapes special chars in the password (an f-string would NOT escape
           ``@ : / # ?``).

        Every SQLite-family arm builds a fully local URL with NO credential access.
        """
        if self.driver is not SqlDriver.POSTGRESQL_PSYCOPG2:
            return f"{self.driver.value}:///{self.database}"
        if self.url is not None:
            return self.url.get_secret_value()
        if self.password is None:
            # Defensive — _require_pg_credentials guarantees this is unreachable; the guard
            # also narrows ``SecretStr | None`` -> ``SecretStr`` for mypy.
            raise ConfigurationError(
                config_key="ITRADER_DATABASE_PASSWORD",
                reason="Postgres password missing despite validator",
            )
        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        ).render_as_string(hide_password=False)
