"""GATE-02 substrate self-test (D-10/D-11).

Proves the cross-backend ``engine`` fixture is wired correctly: the SQLite arm runs
in-process, and the Postgres arm runs on a testcontainers container when Docker is
available or skips cleanly when it is not (D-11) — so a Dockerless
``poetry run pytest tests`` stays green. The ``--collect-only`` of this parametrized test
also proves the deferred ``testcontainers`` import (collection touches no fixture body).
The SPINE-03 round-trip (01-03) builds on this same ``engine`` parametrization.
"""

import pytest
from sqlalchemy import text


@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)
def test_engine_executes_select_one(engine):
    """Each backend arm yields a live ``Engine`` (the PG arm skips when Dockerless)."""
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
