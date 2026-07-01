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
