"""Unit tests for ``itrader/storage/backend.py`` + the barrel (SPINE-02, D-01).

Asserts the three behaviors of the composition spine:

1. ``SqlBackend(SqlSettings())`` over the default SQLite settings exposes ``.engine``
   (an Engine bound to the resolved URL) and ``.metadata`` (a fresh MetaData), and holds
   NO business / query logic.
2. A throwaway concrete store COMPOSES a ``SqlBackend`` (has-a) and creates a Table on
   ``backend.metadata`` without inheriting any shared storage base — there is no
   ``SqlStorageBase`` symbol to import.
3. ``itrader.storage`` re-exports ``SqlBackend`` and the type helpers; importing the
   barrel does NOT import the quarantined ``sql_store`` and does NOT touch the env.
"""

import os
import subprocess
import sys
from pathlib import Path

import uuid_utils.compat as uc
from sqlalchemy import Column, MetaData, Table, Uuid, insert, select
from sqlalchemy.engine import Engine

from itrader.config.sql import SqlSettings
from itrader.storage import SqlBackend


def test_backend_exposes_engine_and_metadata_no_business_logic() -> None:
    backend = SqlBackend(SqlSettings())
    assert isinstance(backend.engine, Engine)
    assert isinstance(backend.metadata, MetaData)
    assert str(backend.engine.url) == "sqlite+pysqlite:///:memory:"
    # Instance state is exactly engine + metadata — no query caches, no business state.
    assert {name for name in vars(backend) if not name.startswith("_")} == {"engine", "metadata"}
    # The ONLY public method is the engine-lifecycle ``dispose()`` (WR-03): the backend
    # OWNS the engine, so it owns the engine's teardown. There is still NO query/business
    # logic — it remains a pure Engine+MetaData holder otherwise.
    public_methods = {
        name
        for name in dir(SqlBackend)
        if not name.startswith("_") and callable(getattr(SqlBackend, name))
    }
    assert public_methods == {"dispose"}


def test_backend_creates_missing_sqlite_parent_dir(tmp_path: Path) -> None:
    """WR-03 — a file-backed SQLite URL self-provisions its missing parent directory.

    Without this, ``create_engine`` raises ``OperationalError: unable to open database
    file`` on first connect for the documented ``results_default()`` path (``output/``
    absent on a fresh checkout / CI runner).
    """
    db_path = tmp_path / "missing_dir" / "results.db"
    assert not db_path.parent.exists()

    backend = SqlBackend(SqlSettings(database=str(db_path)))
    try:
        # The parent dir now exists, and a real connection actually opens the file.
        assert db_path.parent.is_dir()
        with backend.engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        backend.dispose()


def test_concrete_store_composes_backend_without_god_base() -> None:
    backend = SqlBackend(SqlSettings())

    class _DemoStore:
        """Composes SqlBackend (has-a) — it does NOT inherit a shared storage base."""

        def __init__(self, sql_backend: SqlBackend) -> None:
            self._backend = sql_backend
            self.table = Table(
                "demo",
                sql_backend.metadata,
                Column("id", Uuid(as_uuid=True), primary_key=True),
            )

    store = _DemoStore(backend)
    # has-a, not is-a — composition, never inheritance (SPINE-02 / D-01).
    assert not isinstance(store, SqlBackend)
    assert isinstance(store._backend, SqlBackend)
    assert "demo" in backend.metadata.tables

    # The composed backend actually creates the table and round-trips a UUIDv7.
    backend.metadata.create_all(backend.engine)
    run_id = uc.uuid7()
    with backend.engine.begin() as conn:
        conn.execute(insert(store.table).values(id=run_id))
    with backend.engine.connect() as conn:
        assert conn.execute(select(store.table.c.id)).scalar_one() == run_id

    # There is no cross-concern god base anywhere in the spine.
    import itrader.storage as storage_pkg
    import itrader.storage.backend as backend_mod

    assert not hasattr(storage_pkg, "SqlStorageBase")
    assert not hasattr(backend_mod, "SqlStorageBase")


def test_barrel_reexports_public_surface() -> None:
    import itrader.storage as storage_pkg

    assert storage_pkg.SqlBackend is SqlBackend
    assert hasattr(storage_pkg, "UtcIsoText")
    assert hasattr(storage_pkg, "json_variant")


def test_barrel_import_is_env_free_and_quarantines_sql_store() -> None:
    """Fresh-interpreter import with the secret env unset: succeeds, and never pulls sql_store."""
    env = {key: value for key, value in os.environ.items() if key != "ITRADER_DATABASE_URL"}
    code = (
        "import sys; import itrader.storage; "
        "assert 'itrader.price_handler.store.sql_store' not in sys.modules, "
        "'barrel must not import the quarantined sql_store'; "
        "print('barrel-ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "barrel-ok" in result.stdout
