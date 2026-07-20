"""
Strategy registry subdomain package.

Re-exports the strategy reconstruction collaborators — the D-01 injected type catalog and
the D-04/D-20 authoring-param codec — so consumer import paths stay short. Together they
are the ``catalog x row x codec -> Strategy`` seam that rehydrate (Plan 05) and the runtime
``add`` verb (Plan 07) both reduce to.

It is NOT added to the ``strategy_handler`` top barrel (D-05) for a LAYERING reason: it is a
reconstruction implementation detail that reaches the store through an injected handle, and
the top barrel is 0 bytes and stays that way — mirroring the four ``order_handler``
collaborator subdirs, none of which is added to its domain barrel either.

The reason is NOT an inertness one. This package leaks no SQL: 10.1-03 verified it in a clean
interpreter, and it was re-measured on 2026-07-20 (``import
itrader.strategy_handler.registry`` -> zero ``sqlalchemy`` / ``psycopg2`` / ``alembic``
modules in ``sys.modules``). Since barrel-exporting performs exactly that import, an earlier
SQL-leak claim made here about exporting was false and has been removed (WR-05/IN-06). The
surrounding GATE-01 inertness discipline that
``tests/integration/test_okx_inertness.py`` locks is real and unaffected — only this module's
own SQL-leak assertion was wrong.

**D-05 — why the reconstruction logic lives HERE** and not in the two places it might
otherwise be reached for:

- NOT in the ``Strategy`` base — that is the pure-alpha boundary (D-12). The base must not
  know about catalogs or stores.
- NOT in ``StrategyRegistryStore`` — that is persistence-only. It must not import strategy
  classes, which also keeps the inertness seam clean.
"""

from .catalog import StrategyCatalog, UnknownStrategyTypeError, resolve_strategy_class
from .config_codec import (
	CONFIG_VERSION,
	StrategyConfigError,
	decode_strategy_config,
	encode_strategy_config,
)
from .rehydrate import (
	RehydrateInfrastructureError,
	build_strategy,
	rehydrate_strategies,
)

__all__ = [
	"CONFIG_VERSION",
	"RehydrateInfrastructureError",
	"StrategyCatalog",
	"StrategyConfigError",
	"UnknownStrategyTypeError",
	"build_strategy",
	"decode_strategy_config",
	"encode_strategy_config",
	"rehydrate_strategies",
	"resolve_strategy_class",
]
