"""Clean-interpreter import-quarantine for the backtest storage path (GATE-01).

This is the cross-cutting structural proof of the v1.6 two-part DB-gate's
**hot-path-inertness** half (Gate a): constructing any of the three storage
backends on the ``'backtest'`` arm must pull **NO** SQLAlchemy and must NOT
import any ``cached_sql_storage`` wrapper module.

Why this matters (RETAIN-01 backend-selection at wiring / Pitfall 3): the
backtest backend contains no serialization code at all — zero hot-path cost is
**structural, not disciplined**. The live wrappers (``CachedSql<Concern>Storage``)
and their SQLAlchemy dependency are imported lazily, only inside each factory's
``'live'`` arm. If a future edit hoists an SQL import to module scope (or
re-exports a wrapper from an ``__init__``), the backtest import path would silently
start paying for serialization machinery it never uses — this test fails loudly
when that happens.

Why a subprocess (NOT an in-process ``sys.modules`` assertion): SQLAlchemy is
already imported by sibling ``tests/integration/storage/`` tests within the same
pytest session, so an in-process ``'sqlalchemy' not in sys.modules`` check is
unreliable (it would observe another test's import). The probe therefore runs in
a **fresh** interpreter via ``subprocess.run([sys.executable, "-c", PROBE])`` and
asserts on a clean module table.
"""

import subprocess
import sys

# Probe executed in a clean interpreter: import the three storage factories,
# construct each 'backtest' backend, then assert the SQL/serialization layer was
# never pulled. Prints a sentinel on success so the parent can assert on stdout.
_PROBE = r"""
import sys

from itrader.order_handler.storage.storage_factory import OrderStorageFactory
from itrader.portfolio_handler.storage.storage_factory import (
    PortfolioStateStorageFactory,
)
from itrader.strategy_handler.storage.storage_factory import SignalStorageFactory

# Construct each backtest backend (the hot-path arm). None of these may pull SQL.
OrderStorageFactory.create("backtest")
PortfolioStateStorageFactory.create("backtest")
SignalStorageFactory.create("backtest")

# GATE-01 inertness assertions on a clean module table.
assert "sqlalchemy" not in sys.modules, (
    "GATE-01 VIOLATION: sqlalchemy imported on the backtest storage path"
)
leaked = [name for name in sys.modules if "cached_sql_storage" in name]
assert not leaked, (
    "GATE-01 VIOLATION: cached_sql_storage wrapper imported on the backtest "
    "path: " + repr(leaked)
)

print("QUARANTINE_OK")
"""


def test_backtest_storage_path_imports_no_sql() -> None:
    """The backtest arm of all three factories pulls no SQL/wrapper (GATE-01).

    Runs the probe in a fresh interpreter (``sys.executable``) so the assertion
    is not contaminated by SQLAlchemy already imported by sibling integration
    tests in the same session.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )

    # Surface the probe's stderr on failure so a quarantine break is debuggable.
    assert result.returncode == 0, (
        "import-quarantine probe failed (returncode "
        f"{result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "QUARANTINE_OK" in result.stdout, (
        "quarantine sentinel missing from probe stdout.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
