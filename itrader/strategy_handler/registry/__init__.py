"""
Strategy registry subdomain package.

Re-exports the strategy reconstruction collaborators — the D-01 injected type catalog and
the D-04/D-20 authoring-param codec — so consumer import paths stay short. Together they
are the ``catalog x row x codec -> Strategy`` seam that rehydrate (Plan 05) and the runtime
``add`` verb (Plan 07) both reduce to.

It is NOT added to the ``strategy_handler`` top barrel (D-05/GATE-01): it is a
reconstruction implementation detail that reaches the store, and barrel-exporting it would
pull SQL onto the backtest import graph — exactly the inertness property
``tests/integration/test_okx_inertness.py`` locks.

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

__all__ = [
	"CONFIG_VERSION",
	"StrategyCatalog",
	"StrategyConfigError",
	"UnknownStrategyTypeError",
	"decode_strategy_config",
	"encode_strategy_config",
	"resolve_strategy_class",
]
