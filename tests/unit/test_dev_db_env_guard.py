"""Proof that the session-autouse dev-DB env guard removes the leak surface.

The ``_block_dev_database_env`` fixture in ``tests/conftest.py`` (session-scoped,
autouse) pops the six ``ITRADER_DATABASE_*`` dev-DB env vars at session start. This
test asserts they are all absent DURING a test — even when two of them were EXPORTED
into the pytest process on the command line (the verify command does exactly that).
This is what makes "no test can reach the developer's operational Postgres" a
systemic, session-wide guarantee.

Import-light on purpose: it does NOT import ``itrader`` (whose import initializes the
config/logger/idgen singletons) — the guard is a pure ``os.environ`` fact.

4-space indentation (matches ``tests/conftest.py``); folder-derived ``unit`` marker;
NO ``__init__.py`` in this dir (auto-memory: package-collision hazard).
"""

import os

# The six names must match tests/conftest.py::_DEV_DB_ENV_VARS exactly.
_DEV_DB_ENV_VARS = (
    "ITRADER_DATABASE_PASSWORD",
    "ITRADER_DATABASE_URL",
    "ITRADER_DATABASE_HOST",
    "ITRADER_DATABASE_PORT",
    "ITRADER_DATABASE_USER",
    "ITRADER_DATABASE_NAME",
)


def test_dev_db_env_removed_for_session():
    """Every dev-DB env var is unset for the session, even if it was exported."""
    for name in _DEV_DB_ENV_VARS:
        assert os.environ.get(name) is None, (
            f"{name} leaked into a test — the session guard did not remove it"
        )
