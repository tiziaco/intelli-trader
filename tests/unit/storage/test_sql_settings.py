"""Unit tests for ``itrader/config/sql.py`` — unified SqlSettings (SPINE-01, D-12/D-15).

Asserts the behaviors of the ONE self-contained config-not-code backend selector
(260629-l0q — supersedes 260629-jh2 / IN-02):

1. ``SqlSettings.default()`` / ``SqlSettings()`` default to ``SQLITE_PYSQLITE`` + ``:memory:``
   and ``engine_url()`` returns ``sqlite+pysqlite:///:memory:`` with NO credential access (the
   backtest path stays env-tolerant and deterministic — driver/database pinned by ``default()``).
2. ``SqlDriver`` carries exactly three members — ``SQLITE_PYSQLITE``,
   ``POSTGRESQL_PSYCOPG2``, and the unwired ``SQLITE_LIBSQL`` slot (Turso-ready, D-15).
3. On the ``POSTGRESQL_PSYCOPG2`` arm ``engine_url()`` ASSEMBLES the URL from the component
   ``ITRADER_DATABASE_*`` fields via ``sqlalchemy.URL.create`` (default port 5544, special-char
   password escaped); ``url`` (``ITRADER_DATABASE_URL``) is the OPTIONAL verbatim escape hatch
   that wins when set; a Postgres path with neither password nor url fails loud
   (``pydantic.ValidationError``) via the ``_require_pg_credentials`` model_validator; and the
   provided password is a ``SecretStr`` (masked in repr, value via ``.get_secret_value()``).
4. Importing ``config/sql.py`` does NOT instantiate ``SqlSettings`` (Pitfall 8 — no
   construction, no validator, env-free at import). Extra keys are forbidden.
"""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from itrader.config.sql import SqlDriver, SqlSettings


def test_default_is_sqlite_memory_and_engine_url_is_credential_free() -> None:
    settings = SqlSettings.default()
    assert settings.driver is SqlDriver.SQLITE_PYSQLITE
    assert settings.database == ":memory:"
    # SQLite arm never touches a credential — engine_url() succeeds with no password set.
    assert settings.engine_url() == "sqlite+pysqlite:///:memory:"


def test_default_classmethod_matches_default_construction() -> None:
    assert SqlSettings.default().engine_url() == "sqlite+pysqlite:///:memory:"
    # results_default() is the on-disk SQLite path; default() stays :memory: (independent).
    assert SqlSettings.results_default().engine_url() == "sqlite+pysqlite:///output/results.db"


def test_driver_enum_has_exactly_three_members_incl_libsql_slot() -> None:
    assert {member.name for member in SqlDriver} == {
        "SQLITE_PYSQLITE",
        "POSTGRESQL_PSYCOPG2",
        "SQLITE_LIBSQL",
    }
    assert SqlDriver.SQLITE_PYSQLITE.value == "sqlite+pysqlite"
    assert SqlDriver.POSTGRESQL_PSYCOPG2.value == "postgresql+psycopg2"
    assert SqlDriver.SQLITE_LIBSQL.value == "sqlite+libsql"


def test_postgres_arm_assembles_url_from_components() -> None:
    """(a) The Postgres arm assembles the URL from the ITRADER_DATABASE_* fields.

    Custom host/port (5544, NOT 5432) flow through. Explicit kwargs override env, so a local
    .env cannot interfere; ``_env_file=None`` belt-and-braces.
    """
    settings = SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        _env_file=None,
        host="db.internal",
        port=5544,
        user="u",
        name="itrader",
        password="secret",
    )
    assert settings.engine_url() == "postgresql+psycopg2://u:secret@db.internal:5544/itrader"


def test_postgres_arm_url_escapes_special_char_password() -> None:
    """(b) A special-char password is URL-escaped via sqlalchemy.URL.create.

    ``@ : / # ?`` → ``%40 %3A %2F %23 %3F`` — an f-string would NOT escape these and would
    corrupt the userinfo segment.
    """
    settings = SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        _env_file=None,
        host="db.internal",
        port=5544,
        user="u",
        name="itrader",
        password="p@ss:w/rd#?",
    )
    resolved = settings.engine_url()
    assert "u:p%40ss%3Aw%2Frd%23%3F@db.internal:5544/itrader" in resolved
    # The raw special chars must NOT appear unescaped after the userinfo.
    assert "p@ss:w/rd#?" not in resolved


def test_postgres_arm_verbatim_url_wins_as_escape_hatch() -> None:
    """(c) ``url`` (ITRADER_DATABASE_URL) is the OPTIONAL verbatim override.

    When set it wins verbatim over component assembly — its scheme/driver authoritative and
    NOT reconciled against the enum member.
    """
    url = "postgresql+psycopg2://dbuser:dbpass@localhost:5432/ops"
    settings = SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2, _env_file=None, url=url)
    resolved = settings.engine_url()
    assert resolved == url
    assert "dbuser:dbpass@localhost" in resolved
    # The verbatim URL is reachable only via SecretStr.get_secret_value(); str()/repr() masks.
    assert "**********" not in resolved


def test_sqlite_arm_is_credential_free() -> None:
    """(d) The SQLite arm builds a fully local URL with no credential access."""
    settings = SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE, _env_file=None, database="local.db")
    assert settings.engine_url() == "sqlite+pysqlite:///local.db"


def test_postgres_arm_without_credentials_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(e) A Postgres path with neither password nor url fails loud (M2-06 preserved).

    The ``_require_pg_credentials`` model_validator raises ``ValueError`` → pydantic wraps it
    into ``pydantic.ValidationError``. With every ITRADER_DATABASE_* env absent and
    ``_env_file=None``, construction must raise — the Postgres path is unreachable without a
    credential.
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
    with pytest.raises(ValidationError):
        SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2, _env_file=None)


def test_password_is_secretstr_masked_in_repr_reachable_via_getter() -> None:
    """(e) A provided password is a SecretStr — masked in repr, value via the getter."""
    settings = SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        _env_file=None,
        password="s3cr3t",
    )
    assert "s3cr3t" not in repr(settings)
    assert settings.password is not None
    assert settings.password.get_secret_value() == "s3cr3t"


def test_import_does_not_instantiate_sqlsettings() -> None:
    """Import the module in a fresh interpreter with the DB env unset (Pitfall 8).

    If ``config/sql.py`` (or the ``itrader`` import chain) constructed ``SqlSettings`` at
    import, the Postgres validator could raise and the subprocess would exit non-zero. A clean
    exit proves lazy, env-free, construction-free import.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ITRADER_DATABASE_")
    }
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
