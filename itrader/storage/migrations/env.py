"""Alembic environment for the live Postgres operational store (MIG-01, D-14).

This migration chain is scoped to the DURABLE operational store ONLY. The ephemeral
research/results store is built by ``MetaData.create_all()`` and never runs Alembic, so it
carries no ``alembic_version`` table — the create_all-vs-Alembic split is the heart of
MIG-01 (D-14).

``render_as_batch=True`` is set in BOTH the offline and online configure paths so that any
future ALTER is emitted in batch ("move-and-copy") form — portable across SQLite / libSQL,
whose in-place ALTER support is limited.

Import-time inertness (T-01-11 / Pitfall 8): the DB URL is resolved LAZILY inside the run
functions, never at import. On the operational arm the URL comes from the spine's
``SqlSettings`` Postgres arm, which only touches ``Settings.database_url`` at run time — an
unset ``ITRADER_DATABASE_URL`` therefore cannot break import or collection. A URL supplied
on the Alembic ``Config`` (tests / ops override) takes precedence. No credential-bearing
URL is ever written into ``alembic.ini`` (T-01-09 / SEC-01).

This module is executed by Alembic, never imported on the backtest runtime path, so the
spine's migration tooling stays off the hot-loop import graph (GATE-01 inertness).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.storage.backend import SqlBackend

# The Alembic Config object — access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging (sets up loggers).
# disable_existing_loggers=False so running Alembic IN-PROCESS (the migrations test, or
# any embedded ops tooling) does NOT clobber the host application's already-configured
# loggers — the stock template default (True) would disable iTrader's structlog-backed
# stdlib loggers and contaminate later caplog assertions in the same interpreter.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Autogenerate target: the spine's SqlBackend MetaData. The default (SQLite, ``:memory:``)
# settings build the backend ENV-FREE — no ``Settings()`` is touched here — so future
# autogen sees exactly the Tables registered on the spine. No operational tables exist yet
# (empty ``versions/``, D-14).
target_metadata = SqlBackend(SqlSettings.default()).metadata


def _resolve_url() -> str:
    """Lazily resolve the operational DB URL (T-01-11 — never at import).

    Precedence: an explicit ``sqlalchemy.url`` on the Alembic ``Config`` (tests / ops
    override) wins; otherwise the live operational URL is built from the spine's
    ``SqlSettings`` Postgres arm, which reads ``Settings.database_url`` only here at
    migration time. The chain is scoped to live Postgres (D-14).
    """
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2).engine_url()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (URL only, no Engine)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # portable ALTER (SQLite/libSQL limits) — D-14
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (Engine + bound connection)."""
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # portable ALTER (SQLite/libSQL limits) — D-14
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
