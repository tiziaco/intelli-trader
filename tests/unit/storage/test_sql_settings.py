"""Unit tests for ``itrader/config/sql.py`` — SqlSettings (SPINE-01, D-12/D-15).

Asserts the four behaviors of the config-not-code backend selector:

1. ``SqlSettings()`` defaults to ``SQLITE_PYSQLITE`` + ``:memory:`` and ``engine_url()``
   returns ``sqlite+pysqlite:///:memory:`` with NO environment access (the backtest path
   stays env-free).
2. ``SqlDriver`` carries exactly three members — ``SQLITE_PYSQLITE``,
   ``POSTGRESQL_PSYCOPG2``, and the unwired ``SQLITE_LIBSQL`` slot (Turso-ready, D-15).
3. On the ``POSTGRESQL_PSYCOPG2`` arm, ``engine_url()`` resolves credentials via
   ``Settings.database_url.get_secret_value()`` — and importing ``config/sql.py`` does NOT
   instantiate ``Settings()`` (no ValidationError when ``ITRADER_DATABASE_URL`` is unset).
4. Extra keys are forbidden (mass-assignment defense).
"""

import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

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


def test_postgres_arm_resolves_unmasked_secret_via_get_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "postgresql+psycopg2://dbuser:dbpass@localhost:5432/ops"
    monkeypatch.setenv("ITRADER_DATABASE_URL", url)
    settings = SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2)
    resolved = settings.engine_url()
    # The unmasked creds are reachable ONLY via SecretStr.get_secret_value();
    # str()/repr() of a SecretStr masks them as "**********".
    assert resolved == url
    assert "dbuser:dbpass@localhost" in resolved
    assert "**********" not in resolved


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
