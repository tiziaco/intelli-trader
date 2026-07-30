"""
Connectors package — live trading venue sessions (D-13).

A top-level package (NOT a portfolio concern): it spans the data + order arms, broader
than execution. It holds the ``LiveConnector`` structural Protocol (``base.py``), the
``OkxConnector`` session/transport primitive (``okx.py``), the ``ConnectorPool`` that
memoizes one session per ``(venue, account_id)`` (``pool.py``) and the stream supervisor.

Barrel posture (GATE-01) — this barrel exports ONLY the structural ``LiveConnector``
Protocol marker (``connectors/base.py`` is a pure ``typing`` module with no heavy
imports). Every concretion — ``OkxConnector``, ``ConnectorPool`` — is imported DIRECTLY
from its own module and is deliberately NOT re-exported here. A barrel re-export of a
ccxt-backed concretion makes importing ANY module under ``itrader.connectors`` heavy,
because the import machinery runs this file first and pulls ``ccxt`` with it. The whole
package is a forbidden root on the backtest import graph
(``tests/integration/test_okx_inertness.py``), so an eager re-export would redden that
gate outright. No lazy ``__getattr__`` compatibility shim is provided: a shim would
re-create that exact heaviness the moment anything touched it.
"""

from .base import LiveConnector

__all__ = ["LiveConnector"]
