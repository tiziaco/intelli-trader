"""
Connectors package — live trading venue interfaces (D-13).

A new top-level package (NOT a portfolio concern): it spans the data + order arms,
broader than execution. Phase 1 shipped the ``LiveConnector`` structural Protocol marker
(D-10); Phase 2 added ``connectors/okx.py`` (``OkxConnector`` — the shared authenticated
session/transport primitive) and Phase 4 adds ``connectors/paper.py`` (``PaperConnector``),
both implementing ``LiveConnector``.

Barrel posture (Phase 11.1 / D-04 / GATE-01) — this barrel exports ONLY the structural
``LiveConnector`` Protocol marker (``connectors/base.py`` is a pure ``typing`` module with
no heavy imports). Every connector CONCRETION (``OkxConnector``, ``PaperConnector``) is
imported DIRECTLY from its own module — ``from itrader.connectors.okx import OkxConnector``
— and is deliberately NOT re-exported here. A barrel re-export of a ccxt-backed concretion
makes importing ANY module under ``itrader.connectors`` heavy, because the import machinery
runs this file first and pulls ``ccxt`` with it. Phase 11.1's D-04 puts
``itrader.connectors.provider`` on the BACKTEST import graph, so an eager re-export here
would redden the GATE-01 inertness gate (``tests/integration/test_okx_inertness.py``, whose
``_FORBIDDEN`` tuple lists both ``ccxt`` and ``itrader.connectors.okx``) on its first
commit. No lazy ``__getattr__`` compatibility shim is provided: a shim would re-create that
exact heaviness the moment anything touched it.
"""

from .base import LiveConnector

__all__ = ["LiveConnector"]
