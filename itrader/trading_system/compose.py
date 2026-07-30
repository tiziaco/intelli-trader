"""Transitional bundle-shaped adapter over ``build_handler_graph``.

``compose_engine`` is the seam the live root still consumes. It owns nothing but the
translation from the OLD venue-bundle shape into the arguments
``trading_system/graph.py::build_handler_graph`` requires — seed the paper exchange out
of the bundle memo, and build a default ``PortfolioFactory`` when the caller passes
none. The handler graph itself lives in ``graph.py`` and is built there once.

Indentation: TABS.
"""

from typing import Any, Optional

from itrader.execution_handler.execution_handler import seed_exchange_registry
from itrader.portfolio_handler.portfolio_factory import (
	AccountFactory,
	PortfolioFactory,
)
from itrader.results import ResultsStore
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.graph import Engine, build_handler_graph
# Deliberately NOT taken from the ``itrader.venues`` barrel — see the module
# docstring of ``venues/bundles.py``.
from itrader.venues.bundles import VenueBundles


def compose_engine(
	ctx: "EngineContext", *,
	venue_bundles: "VenueBundles",
	results_store: Optional["ResultsStore"] = None,
	alert_sink: Optional[Any] = None,
	system_store: Optional[Any] = None,
	error_policy: Optional[Any] = None,
	strategy_catalog: Optional[Any] = None,
	exchange_registry: Optional[dict[tuple[str, str], Any]] = None,
	portfolio_factory: Optional[Any] = None) -> Engine:
	"""Seed the bundle-derived exchange registry, then build the handler graph.

	Parameters
	----------
	venue_bundles : VenueBundles
		The already-built ``(venue, account_id)`` bundle memo the paper exchange is
		read out of.
	exchange_registry : dict | None
		The ``(venue, account_id) -> exchange`` map. ``None`` creates it here; the live
		root passes its OWN reference so ``VenueAccountManager.bring_online`` writes the
		SAME map ``ExecutionHandler`` reads.
	portfolio_factory : Any | None
		``None`` builds one over a validator-less ``AccountFactory`` (never raises); the
		live root injects one holding the real ``assert_available`` validator.

	The remaining parameters are forwarded to ``build_handler_graph`` unchanged.
	"""
	if exchange_registry is None:
		exchange_registry = {}
	seed_exchange_registry(exchange_registry, venue_bundles)
	if portfolio_factory is None:
		portfolio_factory = PortfolioFactory(
			account_factory=AccountFactory(),
			environment=ctx.environment,
			sql_engine=ctx.sql_engine)
	return build_handler_graph(
		ctx,
		exchange_registry=exchange_registry,
		portfolio_factory=portfolio_factory,
		results_store=results_store,
		alert_sink=alert_sink,
		system_store=system_store,
		error_policy=error_policy,
		strategy_catalog=strategy_catalog)
