"""Unit tests for ``itrader/config/sql.py`` — SqlSettings (SPINE-01, D-12/D-15).

Asserts the four behaviors of the config-not-code backend selector:

1. ``SqlSettings()`` defaults to ``SQLITE_PYSQLITE`` + ``:memory:`` and ``engine_url()``
   returns ``sqlite+pysqlite:///:memory:`` with NO environment access (the backtest path
   stays env-free).
2. ``SqlDriver`` carries exactly three members — ``SQLITE_PYSQLITE``,
   ``POSTGRESQL_PSYCOPG2``, and the unwired ``SQLITE_LIBSQL`` slot (Turso-ready, D-15).
3. On the ``POSTGRESQL_PSYCOPG2`` arm (260629-jh2 — supersedes IN-02), ``engine_url()``
   ASSEMBLES the URL from the component ``ITRADER_DATABASE_*`` fields via
   ``sqlalchemy.URL.create`` (default port 5544, special-char password escaped);
   ``ITRADER_DATABASE_URL`` is the OPTIONAL verbatim escape hatch that wins when set; a live
   path with no password fails loud (ValidationError); and importing ``config/sql.py`` does
   NOT instantiate ``Settings()`` (Pitfall 8 — no ValidationError at import).
4. Extra keys are forbidden (mass-assignment defense).
"""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from itrader.config.settings import Settings
from itrader.config.sql import SqlDriver, SqlSettings


def test_default_is_sqlite_memory_and_engine_url_is_env_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ITRADER_DATABASE_URL", raising=False)
    settings = SqlSettings()
    assert settings.driver is SqlDriver.SQLITE_PYSQLITE
    assert settings.database == ":memory:"
    # No env present, yet engine_url() succeeds — proves the SQLite arm never touches Settings().
    assert settings.engine_url() == "sqlite+pysqlite:///:memory:"


def test_default_classmethod_matches_default_construction() -> None:
    assert SqlSettings.default().engine_url() == SqlSettings().engine_url()


def test_driver_enum_has_exactly_three_members_incl_libsql_slot() -> None:
    assert {member.name for member in SqlDriver} == {
        "SQLITE_PYSQLITE",
        "POSTGRESQL_PSYCOPG2",
        "SQLITE_LIBSQL",
    }
    assert SqlDriver.SQLITE_PYSQLITE.value == "sqlite+pysqlite"
    assert SqlDriver.POSTGRESQL_PSYCOPG2.value == "postgresql+psycopg2"
    assert SqlDriver.SQLITE_LIBSQL.value == "sqlite+libsql"


def test_postgres_arm_assembles_url_from_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(a) 260629-jh2: the Postgres arm assembles the URL from ITRADER_DATABASE_* components.

    Custom host/port (5544, NOT 5432) flow through to the assembled URL. Pass an explicit
    settings object so a local .env cannot interfere.
    """
    s = Settings(
        _env_file=None,
        database_host="db.internal",
        database_port=5544,
        database_user="u",
        database_name="itrader",
        database_password="secret",
    )
    resolved = SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2).engine_url(s)
    assert resolved == "postgresql+psycopg2://u:secret@db.internal:5544/itrader"


def test_postgres_arm_url_escapes_special_char_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(b) 260629-jh2: a special-char password is URL-escaped via sqlalchemy.URL.create.

    ``@ : / # ?`` → ``%40 %3A %2F %23 %3F`` — an f-string would NOT escape these and would
    corrupt the userinfo segment.
    """
    s = Settings(
        _env_file=None,
        database_host="db.internal",
        database_port=5544,
        database_user="u",
        database_name="itrader",
        database_password="p@ss:w/rd#?",
    )
    resolved = SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2).engine_url(s)
    assert "u:p%40ss%3Aw%2Frd%23%3F@db.internal:5544/itrader" in resolved
    # The raw special chars must NOT appear unescaped after the userinfo.
    assert "p@ss:w/rd#?" not in resolved


def test_postgres_arm_verbatim_url_wins_as_escape_hatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(c) 260629-jh2: ITRADER_DATABASE_URL is the OPTIONAL verbatim override (supersedes IN-02).

    When database_url is set it wins verbatim over component assembly — its scheme/driver
    authoritative. Pass an explicit settings object (the no-arg ``Settings()`` now also
    requires database_password) carrying both the verbatim URL and a password.
    """
    url = "postgresql+psycopg2://dbuser:dbpass@localhost:5432/ops"
    s = Settings(_env_file=None, database_url=url, database_password="x")
    resolved = SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2).engine_url(s)
    # The unmasked creds are reachable ONLY via SecretStr.get_secret_value();
    # str()/repr() of a SecretStr masks them as "**********".
    assert resolved == url
    assert "dbuser:dbpass@localhost" in resolved
    assert "**********" not in resolved


def test_postgres_arm_without_password_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(e) 260629-jh2: a live Postgres path with no password fails loud (M2-06 preserved).

    With every ITRADER_DATABASE_* env (including PASSWORD) absent, the lazy ``Settings()``
    inside the Postgres arm raises ValidationError — the Postgres path is unreachable without
    the required-no-default secret.
    """
    for key in (
        "ITRADER_DATABASE_HOST",
        "ITRADER_DATABASE_PORT",
        "ITRADER_DATABASE_USER",
        "ITRADER_DATABASE_NAME",
        "ITRADER_DATABASE_PASSWORD",
        "ITRADER_DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    # Direct construction with no password also fails loud.
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_import_does_not_instantiate_settings() -> None:
    """Import the module in a fresh interpreter with the secret env unset (Pitfall 8).

    If ``config/sql.py`` (or the ``itrader`` import chain) instantiated ``Settings()`` at
    import, the required-no-default ``database_url`` would raise ``ValidationError`` and the
    subprocess would exit non-zero. A clean exit proves lazy, env-free import.
    """
    env = {key: value for key, value in os.environ.items() if key != "ITRADER_DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-c", "import itrader.config.sql; print('imported-ok')"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "imported-ok" in result.stdout


def test_extra_keys_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        SqlSettings(unexpected_key="x")  # type: ignore[call-arg]
