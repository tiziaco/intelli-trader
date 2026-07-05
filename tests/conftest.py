"""Root pytest configuration for the iTrader test suite.

Layered conftests (D-13):

* ``tests/conftest.py`` (this file)  — cross-cutting concerns: folder-derived TYPE
  marker auto-marking and the ``global_queue`` fixture used by both layers.
* ``tests/unit/conftest.py``         — unit-layer documentation/marker anchor.
* ``tests/integration/conftest.py``  — integration-layer fixtures (golden-file paths
  + the ``backtest_engine`` factory) used by the cross-component cascade + oracle.

Marker registration (the ``--strict-markers`` source of truth) lives in EXACTLY ONE
home: ``pyproject.toml`` ``[tool.pytest.ini_options] markers``. This module only
*applies* markers at collection time; it does not register them.

TYPE-axis auto-marking (D-13/D-15)
----------------------------------
A test's marker is derived from its FOLDER, not its domain:

* a file under ``tests/unit/``        -> ``unit``
* a file under ``tests/integration/`` -> ``integration`` (+ ``slow``)
* a file under ``tests/e2e/``         -> ``e2e`` (NOT ``slow`` — D-15)

This fixes the M1 gap where directory-DOMAIN markers (portfolio/orders/...) were
applied but neither ``unit`` nor ``integration`` reliably was. The boundary (D-15):

* unit        = drives ONE collaborating component (may use a real ``global_queue``
                + several classes from its own domain).
* integration = asserts interaction ACROSS components (cross-domain, cross-manager,
                or the full cascade / smoke / oracle).

PURPOSE-axis ``smoke`` marker (NOT folder-derived)
--------------------------------------------------
The ``smoke`` marker is a PURPOSE axis, orthogonal to the folder-derived TYPE axis
above. It is applied MANUALLY (``@pytest.mark.smoke`` or a module-level
``pytestmark = pytest.mark.smoke``), never folder-derived — so it is intentionally
ABSENT from ``pytest_collection_modifyitems`` below. Do NOT auto-apply it here; a
smoke test opts in by hand and thereby joins the ``make test-smoke`` (``-m smoke``)
selection while retaining its folder-derived TYPE marker.
"""

import os
import pathlib
import queue
from datetime import datetime
from decimal import Decimal

import pytest

from itrader.core.bar import Bar
from itrader.events_handler.events import BarEvent


def pytest_collection_modifyitems(config, items):
    """Apply folder-derived TYPE markers (D-13/D-15).

    The whole suite is now pytest-native (D-14); this hook applies the TYPE marker
    to every collected item purely by its folder, independent of how the test is
    authored (``item.add_marker`` runs after collection wrapping).
    """
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        if "integration" in parts:
            item.add_marker(pytest.mark.integration)
            # Integration tests run the full engine — also slow.
            item.add_marker(pytest.mark.slow)
        if "e2e" in parts:
            # D-15: e2e scenarios are tiny (~10-bar) full-engine runs — its OWN
            # marker, NOT slow, so it stays in the default ``make test`` suite.
            item.add_marker(pytest.mark.e2e)


# --- Cross-cutting fixtures -------------------------------------------------


# The six dev-DB env vars (itrader/config/sql.py SqlSettings, env_prefix=
# "ITRADER_DATABASE_") that form the developer's operational-Postgres leak surface.
# The Makefile does `include .env` + `.EXPORT_ALL_VARIABLES`, so under `make test`
# these are exported into the pytest process; any test constructing a
# LiveTradingSystem / Postgres SqlSettings without overriding env would bind to the
# real dev DB at localhost:5544. They are removed session-wide by the guard below.
# NOT ITRADER_DATABASE_DATABASE (the sqlite path) — it is not a dev-DB leak surface
# and default() pins the sqlite arm via init kwargs.
_DEV_DB_ENV_VARS = (
    "ITRADER_DATABASE_PASSWORD",
    "ITRADER_DATABASE_URL",
    "ITRADER_DATABASE_HOST",
    "ITRADER_DATABASE_PORT",
    "ITRADER_DATABASE_USER",
    "ITRADER_DATABASE_NAME",
)


@pytest.fixture(scope="session", autouse=True)
def _block_dev_database_env():
    """Session-wide guarantee that no test can reach the developer's operational Postgres.

    Pops the six ``ITRADER_DATABASE_*`` dev-DB env vars (``_DEV_DB_ENV_VARS``) from
    ``os.environ`` at session start and restores them in ``finally``, so the
    ``LiveTradingSystem`` / ``SqlSettings`` env gate falls back to in-memory unless a
    test EXPLICITLY opts in. This makes "no test can reach the dev DB" a systemic
    guarantee rather than a latent leak that is quiet only because the dev DB is down.

    It uses ``os.environ.pop(..., None)`` directly (NOT the function-scoped
    ``monkeypatch`` fixture, which cannot be session-scoped). It is naturally
    overridable by a function-scoped ``monkeypatch.setenv`` inside a test: that
    later, narrower set wins over this earlier session-scope pop and is undone at the
    test's teardown — so the existing container tests that set their own DB env
    (``test_store_live_drive`` / ``test_two_sided_restart``) keep passing.
    """
    saved = {name: os.environ.pop(name, None) for name in _DEV_DB_ENV_VARS}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test (constructor convention: ``queue.Queue``)."""
    return queue.Queue()


# --- Shared bar helpers (M5-02 Bar-struct payload, D-14) ----------------------


def _bar_struct(open_, high, low, close, time=datetime(2024, 1, 1), volume=1):
    """A bare ``Bar`` with every field entered via ``Decimal(str(x))`` (D-14)."""
    return Bar(
        time=time,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _bar_event(open_, high, low, close, ticker="BTCUSDT",
               time=datetime(2024, 1, 1), volume=1):
    """A one-ticker BarEvent with a ``dict[str, Bar]`` payload.

    Keeps the positional ``(open_, high, low, close)`` signature of the legacy
    per-file ``make_bar`` helpers so test conversions stay mechanical.
    """
    return BarEvent(
        time=time,
        bars={ticker: _bar_struct(open_, high, low, close, time=time, volume=volume)},
    )


@pytest.fixture
def make_bar_struct():
    """Factory fixture: build a bare ``Bar`` value object."""
    return _bar_struct


@pytest.fixture
def make_bar():
    """Factory fixture: build a one-ticker ``BarEvent`` (Bar-struct payload)."""
    return _bar_event


@pytest.fixture
def make_bar_event():
    """Alias of ``make_bar`` for call sites preferring the explicit name."""
    return _bar_event


# --- Shared reconciliation double (Phase 5 / 05-02, D-09 offline gate) ---------


@pytest.fixture
def fake_venue_connector():
    """A connected, teardown-safe ``FakeLiveConnector`` for the reconciliation cluster.

    The single credential-free double every Phase-5 test tree (portfolio / order /
    execution / integration) verifies against (D-09, RECON-06). Yields a CONNECTED
    connector (loop already running on a daemon thread) driving a fake ccxt.pro client
    wired with the canned ``watch_*`` push streams + ``fetch_*`` REST snapshots from
    ``tests/support/fixtures/okx_recon_payloads.json``. Guarantees ``disconnect()`` in
    teardown — cancelling any spawned stream task and closing the client so no
    ResourceWarning/RuntimeWarning escapes into the strict suite (Pitfall 4).

    The import is DEFERRED into the fixture body so the root conftest never depends on
    ``tests.support`` being importable at early collection time.
    """
    from tests.support.fake_venue_connector import make_fake_venue_connector

    connector = make_fake_venue_connector(sandbox=True)
    connector.connect()
    try:
        yield connector
    finally:
        connector.disconnect()
