"""Boot-time portfolio reconstruction collaborators (11-08, D-08/D-14/D-15).

DELIBERATELY EMPTY — nothing is re-exported here. Both modules in this package are
reached only from inside ``build_live_system``'s ``system_store is not None`` gate, via
a LAZY import, and ``portfolio_rehydrate`` pulls the SQLAlchemy-backed
``PortfolioDefinitionStore`` transitively through its injected store handle. Barrel-
exporting either one would put the live storage stack back on the backtest import graph
and redden the GATE-01 inertness gate (``tests/integration/test_okx_inertness.py``) —
the recurring regression in this milestone.

4-space indentation.
"""
