"""Clean-interpreter import-inertness gate for the OKX live stack (CONN-04 / GATE-01).

This is the recurring milestone-gate proof for Phase 2: the OKX order/data
machinery must be **inert on the backtest hot path**. Importing the backtest
composition root (``itrader.trading_system.backtest_trading_system``) must pull
**NO** OKX connector concretion and **NO** ``ccxt.pro`` — those are lazy-imported
inside ``LiveTradingSystem.__init__`` only (Plan 02-05), so they never touch the
backtest import graph.

Why this matters (Pitfall / hot-path inertness, carried from v1.6): the backtest
path imports no async/connector code — that is what keeps the W1/W2 perf gate green
and the SMA_MACD oracle byte-exact. If a future edit hoists an OKX/ccxt import to
module scope (or re-exports the concretion from an ``__init__`` on the backtest
path), the backtest import path would silently start pulling asyncio + ccxt.pro
machinery it never uses — this test fails loudly when that happens.

Why a subprocess (NOT an in-process ``sys.modules`` assertion): the running pytest
session has already imported the OKX stack via the ``tests/unit/connectors`` and
``tests/unit/execution`` suites, so an in-process ``'ccxt.pro' not in sys.modules``
check would observe another test's import. The probe therefore runs in a **fresh**
interpreter via ``subprocess.run([sys.executable, "-c", PROBE])`` and asserts on a
clean module table.
"""

import subprocess
import sys

# Probe executed in a clean interpreter: import ONLY the backtest composition root,
# then assert the OKX connector concretion and ccxt.pro were never pulled. Prints a
# sentinel on success so the parent can assert on stdout.
_PROBE = r"""
import sys

# The backtest composition root — the hot path. Importing it must NOT pull the OKX
# stack (lazy-imported inside LiveTradingSystem.__init__, never on this path).
import itrader.trading_system.backtest_trading_system  # noqa: F401

_FORBIDDEN = ("itrader.connectors.okx", "ccxt.pro", "ccxt")
leaked = [name for name in _FORBIDDEN if name in sys.modules]
assert not leaked, (
    "CONN-04 INERTNESS VIOLATION: the backtest import path pulled the OKX/async "
    "stack: " + repr(leaked) + " (must be lazy-imported inside the live path only)"
)

print("INERTNESS_OK")
"""


def test_backtest_path_imports_no_okx_stack() -> None:
    """Importing the backtest root pulls no OKX connector / ccxt.pro (CONN-04).

    Runs the probe in a fresh interpreter (``sys.executable``) so the assertion is
    not contaminated by the OKX stack already imported by sibling connector/
    execution tests in the same session.
    """
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )

    # Surface the probe's stderr on failure so an inertness break is debuggable.
    assert result.returncode == 0, (
        "OKX import-inertness probe failed (returncode "
        f"{result.returncode}).\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "INERTNESS_OK" in result.stdout, (
        "inertness sentinel missing from probe stdout.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
