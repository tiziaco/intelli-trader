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
import tomllib

import pytest
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, inspect, text

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from itrader.config.sql import SqlSettings
from itrader.order_handler.storage.models import build_order_tables
from itrader.order_handler.storage.sql_storage import build_order_config_table
from itrader.portfolio_handler.storage.models import build_portfolio_tables
from itrader.storage import SqlEngine
from itrader.storage.engine import NAMING_CONVENTION
from itrader.storage.halt_record_store import build_halt_records_table
from itrader.storage.strategy_registry_store import build_strategy_registry_tables
from itrader.storage.system_stats_store import build_system_stats_table
from itrader.storage.system_store import build_system_store_table
from itrader.storage.venue_store import build_venue_store_table
from itrader.strategy_handler.storage.models import build_signal_tables

# The NEW tables the migration chain adds on top of the operational baseline — the SQL-02 /
# RTCFG-06 gate asserts they exist after ``upgrade head`` and that their columns match the
# registrar-built (``create_all``) schema. Plan 04-03 added the first four; Phase 9's
# migration-owner plan (09-04) chains ``module_config`` (creates ``order_config``) then
# ``system_stats`` on top (D-25/D-18). The ``portfolio_account_state.config_json`` column is
# NOT a new table — it is an ADD COLUMN checked separately below.
_NEW_TABLES = (
    "system_store",
    "venue_store",
    "strategy_registry",
    "strategy_subscriptions",
    "order_config",
    "system_stats",
)

# Repo-root-anchored paths so the Alembic Config is cwd-INDEPENDENT: Alembic resolves a
# RELATIVE ``script_location`` against the process cwd (not the ini location), so the test
# pins the absolute migrations dir on the Config below.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_MIGRATIONS_DIR = _REPO_ROOT / "migrations"


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


def test_migrations_relocated_out_of_wheel() -> None:
    """SQL-01: ``migrations/`` lives at repo root, OUTSIDE the shipped ``itrader`` wheel.

    Fast, structural, build-free proxy for "migrations are repo-shipped, not
    installed-package-shipped" (LR-18): a full ``poetry build`` + wheel inspection stays an
    optional manual check (04-VALIDATION). This asserts three observable properties:

    1. The relocated tree exists at project-root ``migrations/env.py``.
    2. The old in-package tree ``itrader/storage/migrations`` is GONE (not re-nested).
    3. ``pyproject.toml`` ``tool.poetry.packages`` includes ONLY ``itrader`` — so no rule
       re-adds a project-root ``migrations`` path to the wheel, and the tree now sits outside
       ``itrader/``. Fails loud (red) if a future edit re-nests migrations or adds a second
       ``packages`` include.
    """
    assert (_REPO_ROOT / "migrations" / "env.py").exists()
    assert not (_REPO_ROOT / "itrader" / "storage" / "migrations").exists()

    with (_REPO_ROOT / "pyproject.toml").open("rb") as fh:
        pyproject = tomllib.load(fh)
    packages = pyproject["tool"]["poetry"]["packages"]
    assert packages == [{"include": "itrader"}]


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


def test_migration_chain_is_single_head() -> None:
    """SQL-02/RTCFG-06: the relocated chain has exactly ONE head — ``system_stats``.

    A branched/forked chain (two heads) would make ``upgrade head`` ambiguous and let the
    deploy schema drift. The 04-03 revisions chain linearly off ``d10_halt_records``
    (``system_store`` → ``venue_config`` → ``strategy_registry``); Phase 9's migration-owner
    plan chains ``module_config`` → ``system_stats`` on top, so the single head is the last
    link. ``get_heads()`` returns a list; a tuple compare pins the exact singleton.
    """
    url = "sqlite+pysqlite:///:memory:"  # URL is unused for a script-only head read
    heads = ScriptDirectory.from_config(_alembic_config(url)).get_heads()
    assert tuple(heads) == ("system_stats",)


def test_full_chain_upgrade_creates_new_stores_sqlite(tmp_path: pathlib.Path) -> None:
    """SQL-02/RTCFG-06: ``upgrade head`` on a clean SQLite DB creates every new store table.

    A file-backed SQLite DB (not ``:memory:``) so the schema survives after the
    Alembic-internal engine is disposed and can be inspected on a fresh connection. After
    the full chain every new table (incl. Phase 9's ``order_config`` + ``system_stats``) is
    present, the ``portfolio_account_state.config_json`` ADD COLUMN is applied, and
    ``alembic_version`` holds exactly ONE row (stamped at the single head ``system_stats``).
    """
    db_path = tmp_path / "full_chain.db"
    url = f"sqlite+pysqlite:///{db_path}"
    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert set(_NEW_TABLES) <= names  # the chain built every new table
        # D-25: the portfolio-scope config carrier rides the EXISTING account-state table.
        pas_cols = {c["name"] for c in inspect(engine).get_columns("portfolio_account_state")}
        assert "config_json" in pas_cols
        with engine.connect() as conn:
            applied = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
        assert len(applied) == 1  # single head — one stamped revision row ...
        assert applied[0][0] == "system_stats"  # ... exactly the new single head
    finally:
        engine.dispose()


def test_create_all_vs_migration_parity(tmp_path: pathlib.Path) -> None:
    """SQL-02: the registrar ``create_all`` schema equals the ``upgrade head`` schema.

    The ``build_*`` registrars are the SINGLE SOURCE OF TRUTH for BOTH paths. Engine A is
    built by calling EVERY registrar on a ``MetaData(naming_convention=NAMING_CONVENTION)``
    then ``create_all``; engine B is built by ``upgrade head``. Their table sets (minus the
    Alembic-only ``alembic_version``) must be identical, and the per-table column-name sets
    for the 4 new tables must match — proving the migrations reproduce the registrars.

    Removing any of the 3 ``env.py`` registrar calls makes autogenerate emit a spurious
    drop; hand-authored migrations that diverge from the registrar break this parity.
    """
    # Engine A — registrar-built schema via create_all.
    a_path = tmp_path / "create_all.db"
    a_url = f"sqlite+pysqlite:///{a_path}"
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    build_order_tables(metadata)
    # build_portfolio_tables already carries the D-25 ``config_json`` column on
    # ``portfolio_account_state`` (Plan 03's extended registrar), so engine A's account-state
    # table matches the ``module_config`` ADD COLUMN with NO separate portfolio registrar.
    build_portfolio_tables(metadata)
    build_signal_tables(metadata)
    build_halt_records_table(metadata)
    build_system_store_table(metadata)
    build_venue_store_table(metadata)
    build_strategy_registry_tables(metadata)
    # Phase 9 (09-04): the two NEW P9 registrars — ``order_config`` (module_config migration)
    # + ``system_stats`` (system_stats migration). Their inclusion here makes the
    # ``tables_a == tables_b`` set-equality AND the per-``_NEW_TABLES`` column loop cover
    # both new tables (registrar == migration).
    build_order_config_table(metadata)
    build_system_stats_table(metadata)
    engine_a = create_engine(a_url)

    # Engine B — migration-built schema via upgrade head.
    b_path = tmp_path / "upgrade_head.db"
    b_url = f"sqlite+pysqlite:///{b_path}"
    engine_b = create_engine(b_url)
    try:
        metadata.create_all(engine_a)
        command.upgrade(_alembic_config(b_url), "head")

        inspector_a = inspect(engine_a)
        inspector_b = inspect(engine_b)
        tables_a = set(inspector_a.get_table_names())
        tables_b = set(inspector_b.get_table_names()) - {"alembic_version"}
        assert tables_a == tables_b  # same table set across both paths ...

        # ... and the same column-name set per new table (registrar == migration).
        for table in _NEW_TABLES:
            cols_a = {c["name"] for c in inspector_a.get_columns(table)}
            cols_b = {c["name"] for c in inspector_b.get_columns(table)}
            assert cols_a == cols_b, f"column drift on {table}: {cols_a} != {cols_b}"

        # D-25 ADD COLUMN parity: ``config_json`` is added to the EXISTING
        # ``portfolio_account_state`` (NOT a new table) — create_all built it from the
        # extended registrar; ``upgrade head`` built it via the ``module_config``
        # ``op.add_column``. Assert the column is present on BOTH engines so parity accounts
        # for the column-add, not just the new tables.
        pas_cols_a = {c["name"] for c in inspector_a.get_columns("portfolio_account_state")}
        pas_cols_b = {c["name"] for c in inspector_b.get_columns("portfolio_account_state")}
        assert "config_json" in pas_cols_a
        assert "config_json" in pas_cols_b
        assert pas_cols_a == pas_cols_b, (
            f"portfolio_account_state column drift: {pas_cols_a} != {pas_cols_b}")
    finally:
        engine_a.dispose()
        engine_b.dispose()
