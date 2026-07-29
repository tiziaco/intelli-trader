"""The LIVE composition root — one of the two roots the redesign separates.

Everything the live operating mode needs to come up lives under this package, and nothing
here is reachable from the backtest root. That boundary is asserted, not merely intended:
the inertness probe checks by PREFIX that no module under ``itrader.trading_system.live``
appears in the backtest import graph, so a leaked submodule trips it even though the
package name itself never appears in a backtest import.

The boundary is what keeps ``import itrader`` and every backtest run free of asyncio,
ccxt and SQLAlchemy — which is why the live side may import those freely at module top
instead of hiding them in function bodies.

Indentation: 4-space, like every new module in the redesign.
"""

from .bootstrap import bootstrap_session, layer_persisted_overrides

__all__ = [
    'bootstrap_session',
    'layer_persisted_overrides',
]
