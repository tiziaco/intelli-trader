"""Storage-suite fixtures: the GATE-02 cross-backend test substrate (D-10/D-11).

This package is the home of the SQL-spine round-trip / cross-backend-parity tests. It
ships two fixtures, both consumed by the SPINE-03 round-trip (01-03) and reused by
Phase 3's operational-store tests:

* ``pg_engine`` — a SESSION-scoped testcontainers Postgres ``Engine`` (D-10). The
  ``testcontainers``/``docker`` imports are DEFERRED into the fixture body (mirroring the
  ``backtest_engine`` factory in ``tests/integration/conftest.py``) so ``--collect-only``
  never needs a Docker daemon. When Docker is absent the fixture ``pytest.skip``s the PG
  arm (D-11) instead of hard-failing, so a Dockerless ``poetry run pytest tests`` stays
  green and the SQLite arm still runs.

* ``engine`` — a function-scoped, ``indirect``-parametrizable ``Engine`` selecting the
  in-process ``sqlite+pysqlite:///:memory:`` backend for the ``"sqlite"`` param and
  ``pg_engine`` for the ``"postgres"`` param. Consume it as::

      @pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)
      def test_roundtrip(engine): ...

* ``pg_backend`` — a function-scoped ``SqlBackend`` (Wave-2 substrate) bound to the SAME
  Postgres database as the session-scoped ``pg_engine`` container. It reuses that container's
  connection URL through the ``SqlSettings`` verbatim-URL escape hatch
  (``url=SecretStr(container_url)``) so NO second container is spun and no password assembly
  is needed; the heavy imports are deferred into the body (mirroring ``pg_engine``) and the
  backend is disposed in a ``finally`` (WR-03 / Pitfall 4 — an undisposed engine would trip a
  ResourceWarning under ``filterwarnings=["error"]``). Dockerless runs skip via ``pg_engine``
  (D-11). The three Phase-3 operational round-trip test files build their Postgres-backed
  ``Sql<Concern>Storage`` over this fixture (D-10 round-trip substrate).

Tests under ``tests/integration/storage/`` are auto-marked ``integration`` (+ ``slow``) by
the folder-derived marker hook in ``tests/conftest.py`` — no marker decorator here.
"""

import pytest


@pytest.fixture(scope="session")
def pg_engine(pg_container_url):
    """Session-scoped Postgres ``Engine`` over the suite-wide shared container (D-10/D-11).

    Refactored to REUSE the single ``pg_container_url`` fixture from
    ``tests/integration/conftest.py`` instead of spinning its OWN container — there is now
    exactly ONE testcontainers Postgres behind the whole integration tree (no second
    competing container). It simply builds a fresh ``Engine`` off the shared URL and disposes
    it in ``finally`` (Pitfall 4 — an undisposed engine trips a ResourceWarning under
    ``filterwarnings=["error"]``). The D-11 Dockerless skip now happens transitively: resolving
    ``pg_container_url`` raises ``Skipped`` before this body runs.
    """
    from sqlalchemy import create_engine

    engine = create_engine(pg_container_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def engine(request):
    """Cross-backend ``Engine`` selected by an ``indirect`` param (D-10).

    ``"sqlite"``   -> a fresh in-process ``sqlite+pysqlite:///:memory:`` Engine.
    ``"postgres"`` -> the session-scoped ``pg_engine`` (skips Dockerless, D-11).
    """
    from sqlalchemy import create_engine

    backend = request.param
    if backend == "sqlite":
        eng = create_engine("sqlite+pysqlite:///:memory:")
        try:
            yield eng
        finally:
            eng.dispose()
    elif backend == "postgres":
        # Delegates to the session-scoped pg_engine; a Dockerless run skips here (D-11).
        yield request.getfixturevalue("pg_engine")
    else:
        raise ValueError(f"Unknown 'engine' backend param: {backend!r}")


@pytest.fixture
def pg_backend(request):
    """Function-scoped ``SqlBackend`` over the session ``pg_engine`` Postgres DB (D-10).

    Wave-2 substrate: the three operational round-trip test files build their
    Postgres-backed ``Sql<Concern>Storage`` over this fixture. It REUSES the session-scoped
    ``pg_engine`` container — its connection URL is wrapped through the ``SqlSettings``
    verbatim-URL escape hatch (``url=SecretStr(...)``), so a second engine binds to the SAME
    database and no second container is ever spun. A Dockerless run skips here transitively
    (resolving ``pg_engine`` raises ``Skipped`` first, D-11).

    The ``itrader``/SQLAlchemy imports are deferred into the body (mirroring ``pg_engine``)
    so ``--collect-only`` stays import-light, and the backend is disposed in a ``finally``
    (WR-03 / Pitfall 4 — an undisposed engine trips a ResourceWarning under
    ``filterwarnings=["error"]``).
    """
    from pydantic import SecretStr

    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage.backend import SqlBackend

    # Resolve the session container first (skips Dockerless, D-11); reuse its URL verbatim
    # so we bind a fresh Engine to the SAME database without spinning a second container.
    pg_engine = request.getfixturevalue("pg_engine")
    container_url = pg_engine.url.render_as_string(hide_password=False)

    settings = SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        url=SecretStr(container_url),
    )
    backend = SqlBackend(settings)
    try:
        yield backend
    finally:
        backend.dispose()
