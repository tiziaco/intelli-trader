"""
Strategy-lifecycle subdomain package (DECOMP-01/DECOMP-02).

Re-exports the StrategyLifecycleManager — the STRATEGY_COMMAND control-plane
collaborator — so consumer import paths stay short after the strategies-handler
decomposition (pure code motion). It is NOT added to the strategy_handler top
barrel (which is 0 bytes and stays that way): the manager is a StrategiesHandler
implementation detail, mirroring all four order_handler collaborator subdirs,
which barrel at subpackage level and none of which is added to the domain barrel.

No inertness caveat applies to this barrel. Importing this package pulls NO SQL:
10.1-03 verified in a clean interpreter that the whole moved import set leaks
zero sqlalchemy / psycopg2 / alembic. It is on the backtest import graph BY DESIGN — StrategiesHandler
constructs the manager unconditionally in __init__ from a module-top import — which
is exactly why `itrader.strategy_handler.lifecycle.manager` is deliberately absent
from test_okx_inertness.py's `_FORBIDDEN` tuple. The invariant that gate protects
is SQL-absence, asserted positively there.
"""

from .manager import StrategyLifecycleManager

__all__ = ["StrategyLifecycleManager"]
