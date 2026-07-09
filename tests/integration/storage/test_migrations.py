"""MIG-01 — the create_all()-vs-Alembic split (D-14).

The DURABLE operational store evolves under the Alembic migration chain; the EPHEMERAL
research/results store is built by ``MetaData.create_all()`` and carries NO
``alembic_version`` bookkeeping. These tests prove that distinction on in-process SQLite
(no Docker needed) and — when Docker is available — on the testcontainers Postgres
``engine``/``pg_engine`` fixture (D-10/D-11).

Indentation: 4 spaces (tests/integration/* convention). This directory is deliberately
package-LESS (no ``__init__.py``): ``test_migrations.py`` is imported by basename under
pytest prepend mode, and adding an ``__init__.py`` re-creates the ``storage``-package
collection collision fixed earlier.
"""

import pathlib

import pytest
from sqlalchemy import Column, String, Table, Uuid, create_engine, inspect, text

from alembic import command
from alembic.config import Config

from itrader.config.sql import SqlSettings
from itrader.storage import SqlEngine

# Repo-root-anchored paths so the Alembic Config is cwd-INDEPENDENT: Alembic resolves a
# RELATIVE ``script_location`` against the process cwd (not the ini location), so the test
# pins the absolute migrations dir on the Config below.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _REPO_ROOT / "itrader" / "storage" / "migrations"


def _alembic_config(url: str) -> Config:
    """Alembic ``Config`` pointed at the repo's ``alembic.ini`` with an explicit URL.

    ``script_location`` is pinned to the ABSOLUTE migrations dir so the test never depends
    on the process cwd; the URL is injected programmatically — no credential is ever
    written into ``alembic.ini`` (SEC-01 / T-01-09).
    """
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_research_store_create_all_has_no_alembic_version() -> None:
    """A create_all()-built (ephemeral) store has NO ``alembic_version`` table (MIG-01/D-14)."""
    backend = SqlEngine(SqlSettings.default())  # in-process sqlite :memory:, env-free
    # A representative results-style table registered on the SPINE metadata, then built by
    # create_all() — exactly how the disposable research/results store is provisioned.
    Table(
        "results_sample",
        backend.metadata,
        Column("run_id", Uuid(as_uuid=True), primary_key=True),
        Column("label", String),
    )
    backend.metadata.create_all(backend.engine)

    names = inspect(backend.engine).get_table_names()
    assert "results_sample" in names           # schema built by create_all() ...
    assert "alembic_version" not in names       # ... with NO migration bookkeeping (D-14)


def test_alembic_chain_stamps_operational_baseline_sqlite(tmp_path: pathlib.Path) -> None:
    """`alembic upgrade head` applies the operational baseline + stamps it (MIG-01 / GATE-02).

    A file-backed SQLite DB (not ``:memory:``) is used so the schema survives after the
    Alembic-internal engine is disposed and can be inspected on a fresh connection. The
    ``render_as_batch=True`` env.py paths make the baseline portable onto SQLite (DDL only —
    SQLite ``Numeric`` decays to float for VALUES, Pitfall 2, which is irrelevant here).
    """
    db_path = tmp_path / "operational.db"
    url = f"sqlite+pysqlite:///{db_path}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert "alembic_version" in names       # the Alembic chain DID create it ...
        with engine.connect() as conn:
            applied = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
        assert len(applied) == 1                 # ... stamped at the one baseline revision
        # The baseline built the operational tables on the durable store.
        assert {"orders", "order_state_changes", "signals", "equity_snapshots"} <= names
    finally:
        engine.dispose()


@pytest.mark.parametrize("engine", ["postgres"], indirect=True)
def test_alembic_chain_applies_operational_baseline_postgres(engine) -> None:
    """The operational-baseline chain applies on testcontainers Postgres (MIG-01 / GATE-02).

    SKIPS cleanly when Docker is absent (D-11): the ``postgres`` arm delegates to the
    session-scoped ``pg_engine`` fixture, which ``pytest.skip``s a Dockerless run. After
    ``upgrade head`` the durable store carries ``alembic_version`` stamped at the single
    baseline revision PLUS the operational tables the migration builds (D-14: the ephemeral
    research/results store, by contrast, runs ``create_all`` and has NO ``alembic_version``).
    The full chain is reversed (``downgrade base`` drops every operational table) and
    ``alembic_version`` is dropped afterwards so the shared session container stays clean for
    the sibling storage tests.
    """
    # SECURITY (IN-01): ``hide_password=False`` renders the credential in PLAINTEXT. This is
    # safe ONLY because ``engine`` is the throwaway testcontainers Postgres — a disposable,
    # ephemeral container password with no value outside this test run. Do NOT copy this
    # pattern to a real or shared/CI credential: keep the default ``hide_password=True`` and
    # pass the live ``engine``/connection to Alembic instead of a rendered URL string.
    url = engine.url.render_as_string(hide_password=False)
    cfg = _alembic_config(url)
    try:
        command.upgrade(cfg, "head")

        names = set(inspect(engine).get_table_names())
        assert "alembic_version" in names           # the Alembic chain created it ...
        # ... stamped at exactly the one applied baseline revision (a non-empty chain now).
        with engine.connect() as conn:
            applied = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
        assert len(applied) == 1                     # one revision => operational baseline
        # The baseline builds the operational tables (orders self-ref FK + six portfolio
        # tables + signals); spot-check a representative set is present after upgrade.
        assert {"orders", "order_state_changes", "signals", "equity_snapshots"} <= names
    finally:
        # Keep the session-scoped PG container pristine for sibling storage tests: reverse the
        # whole migration (downgrade drops every operational table), then drop alembic_version.
        command.downgrade(cfg, "base")
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
