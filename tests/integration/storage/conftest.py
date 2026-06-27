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

Tests under ``tests/integration/storage/`` are auto-marked ``integration`` (+ ``slow``) by
the folder-derived marker hook in ``tests/conftest.py`` — no marker decorator here.
"""

import pytest


@pytest.fixture(scope="session")
def pg_engine():
    """Session-scoped testcontainers Postgres ``Engine`` (D-10); skip if Dockerless (D-11).

    The heavy ``testcontainers``/``docker`` imports live INSIDE the fixture body so
    collection (``--collect-only``) succeeds with no Docker daemon and the SQLite arm of
    the ``engine`` fixture is never coupled to Docker. Any failure to start the container
    (absent daemon, unreachable socket, image-pull/boot failure) is converted to a
    ``pytest.skip`` — the PG arm must never hard-fail a Dockerless run.
    """
    # Deferred imports (mirrors tests/integration/conftest.py::backtest_engine):
    # kept inside the body so --collect-only needs no Docker daemon.
    from docker.errors import DockerException
    from sqlalchemy import create_engine
    from testcontainers.postgres import PostgresContainer

    container = None
    try:
        # NOTE: the PostgresContainer constructor eagerly builds a DockerClient, so
        # an absent/unreachable daemon raises a DockerException as early as
        # construction (NOT in .start()) — construction MUST be inside this try.
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        # D-11 — ANY startup failure (absent daemon, unreachable socket, image
        # pull/boot failure) skips the PG arm; it must never hard-fail a Dockerless
        # run. pytest.skip raises Skipped (a BaseException), so it is not
        # re-swallowed by this broad clause.
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        kind = "Docker" if isinstance(exc, DockerException) else "PostgreSQL container"
        pytest.skip(f"{kind} unavailable — PG arm skipped (D-11): {exc}")

    engine = create_engine(container.get_connection_url())
    try:
        yield engine
    finally:
        engine.dispose()
        container.stop()


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
