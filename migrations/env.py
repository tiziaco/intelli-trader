"""Alembic environment for the live Postgres operational store (MIG-01, D-14).

This migration chain is scoped to the DURABLE operational store ONLY. The ephemeral
research/results store is built by ``MetaData.create_all()`` and never runs Alembic, so it
carries no ``alembic_version`` table — the create_all-vs-Alembic split is the heart of
MIG-01 (D-14).

``render_as_batch=True`` is set in BOTH the offline and online configure paths so that any
future ALTER is emitted in batch ("move-and-copy") form — portable across SQLite / libSQL,
whose in-place ALTER support is limited.

Import-time inertness (T-01-11 / Pitfall 8): the DB URL is resolved LAZILY inside the run
functions, never at import. On the operational arm the URL comes from the spine's unified
``SqlSettings`` Postgres arm, which assembles the URL from the ``ITRADER_DATABASE_*`` fields
(or the verbatim ``ITRADER_DATABASE_URL`` override) at run time — an unset DB env therefore
cannot break import or collection. A URL supplied on the Alembic ``Config`` (tests / ops
override) takes precedence. No credential-bearing URL is ever written into ``alembic.ini``
(T-01-09 / SEC-01).

This module is executed by Alembic, never imported on the backtest runtime path, so the
spine's migration tooling stays off the hot-loop import graph (GATE-01 inertness).
"""

from logging.config import fileConfig

from sqlalchemy import MetaData, engine_from_config, pool

from alembic import context

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.order_handler.storage.models import build_order_tables
from itrader.order_handler.storage.sql_storage import build_order_config_table
from itrader.portfolio_handler.storage.models import build_portfolio_tables
from itrader.storage.engine import NAMING_CONVENTION
from itrader.storage.halt_record_store import build_halt_records_table
from itrader.storage.strategy_registry_store import build_strategy_registry_tables
from itrader.storage.system_stats_store import build_system_stats_table
from itrader.storage.system_store import build_system_store_table
from itrader.storage.venue_store import build_venue_store_table
from itrader.strategy_handler.storage.models import build_signal_tables

# The Alembic Config object — access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging (sets up loggers).
# disable_existing_loggers=False so running Alembic IN-PROCESS (the migrations test, or
# any embedded ops tooling) does NOT clobber the host application's already-configured
# loggers — the stock template default (True) would disable iTrader's structlog-backed
# stdlib loggers and contaminate later caplog assertions in the same interpreter.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Autogenerate target: the operational MetaData (D-09, MIG-01 continuation). The three
# ``build_*_tables`` registrars are the SINGLE SOURCE OF TRUTH for the operational schema —
# the same functions the test-path ``create_all`` consumers call — so the deploy-path
# ``--autogenerate`` and the test-path ``create_all`` derive from one definition (T-03-19).
# ``NAMING_CONVENTION`` (imported from the spine) pins constraint/index names so autogenerate
# is deterministic and does not churn across regenerations (Pitfall 5 / T-03-18).
#
# Import-inertness (T-01-11 / Pitfall 8 / GATE-01): each registrar only constructs ``Table``
# objects on a fresh ``MetaData`` — no Engine, no ``Settings()``, no connection — so the
# module stays fully import-inert. Building a bare ``MetaData`` here (not a transient
# ``SqlEngine``) also avoids leaking an undisposed SQLite engine at import.
target_metadata = MetaData(naming_convention=NAMING_CONVENTION)
build_order_tables(target_metadata)
build_portfolio_tables(target_metadata)
build_signal_tables(target_metadata)
# D-10 (05.2-06): the durable halt-record table registrar — the same single source of
# truth the store's create_all uses, so autogenerate sees ``halt_records`` and never emits
# a spurious drop for the table the ``d10_halt_records`` migration creates.
build_halt_records_table(target_metadata)
# Phase 4 (04-03, D-02 migration-target wiring): the three new durable-store registrars —
# the SAME single sources of truth the stores' create_all uses — so autogenerate sees
# ``system_store`` / ``venue_store`` / ``strategy_registry`` / ``strategy_subscriptions``
# and never emits a spurious drop for the tables the 04-03 migration chain creates.
# Register-vs-build (Pitfall 8 / GATE-01): each registrar only constructs ``Table`` objects
# on this bare ``MetaData`` — no Engine, no ``Settings()``, no store — so the module stays
# import-inert (store construction is deferred to P6/P9/P10, never here).
build_system_store_table(target_metadata)
build_venue_store_table(target_metadata)
build_strategy_registry_tables(target_metadata)
# Phase 9 (09-04, D-25/D-18 migration-owner): the two NEW P9 registrars — the SAME single
# sources of truth the stores' create_all uses — so autogenerate/parity sees ``order_config``
# (module_config migration) and ``system_stats`` (system_stats migration) and never emits a
# spurious drop. The ``portfolio_account_state.config_json`` column comes for free via the
# already-registered ``build_portfolio_tables`` (Plan 03's extended registrar) at :64.
# Register-vs-build (Pitfall 8 / GATE-01): each registrar only constructs ``Table`` objects
# on this bare ``MetaData`` — no Engine, no ``Settings()``, no store — import-inert.
build_order_config_table(target_metadata)
build_system_stats_table(target_metadata)


def _resolve_url() -> str:
    """Lazily resolve the operational DB URL (T-01-11 — never at import).

    Precedence: an explicit ``sqlalchemy.url`` on the Alembic ``Config`` (tests / ops
    override) wins; otherwise the live operational URL is built from the spine's unified
    ``SqlSettings`` Postgres arm, which reads the ``ITRADER_DATABASE_*`` env only here at
    migration time (fail-loud if neither password nor verbatim url is set). The chain is
    scoped to live Postgres (D-14).
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
