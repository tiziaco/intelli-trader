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

This fixes the M1 gap where directory-DOMAIN markers (portfolio/orders/...) were
applied but neither ``unit`` nor ``integration`` reliably was. The boundary (D-15):

* unit        = drives ONE collaborating component (may use a real ``global_queue``
                + several classes from its own domain).
* integration = asserts interaction ACROSS components (cross-domain, cross-manager,
                or the full cascade / smoke / oracle).
"""

import pathlib
import queue

import pytest


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


# --- Cross-cutting fixtures -------------------------------------------------


@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test (constructor convention: ``queue.Queue``)."""
    return queue.Queue()
