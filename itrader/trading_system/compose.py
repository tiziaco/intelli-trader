"""Shared component-graph wiring seam.

``compose_engine`` is the mode-agnostic seam both ``build_backtest_system`` and
``build_live_system`` consume, returning the wired graph as an ``Engine`` holder.

Boundary: it must NOT hardcode a run-mode backend string. The mode-specific FACTORY
selects the concrete backends — order storage, signal store, venue backends — and
passes them in. Registering a concrete ``PaperVenuePlugin`` here would be exactly the
hardcoded backend this forbids. The seam takes no ``ExchangeConfig``: it builds no
exchange, so it has no use for one.

The commission estimate is split across two owners. The WIRING half is here — a
``FeeModelProvider`` closure dereferencing ``exchange.fee_model`` at CALL time. The
admission CONVENTION (which side and order type an estimate is taken at) lives in
``AdmissionManager._estimate_commission``.

Indentation: TABS.
"""

from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING, cast

from itrader.core.clock import BacktestClock
from itrader.config import OrderConfig
from itrader.events_handler.bus import EventBus
from itrader.events_handler.error_handler import ErrorHandler
from itrader.events_handler.error_policy import FailFastPolicy
from itrader.events_handler.full_event_handler import EventHandler
from itrader.execution_handler.execution_handler import (
	COMPUTE_VENUE,
	ExecutionHandler,
	seed_exchange_registry,
)
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_factory import (
	ComputeAccountAuthority,
	PortfolioFactory,
)
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.price_handler.feed.base import BarFeed
from itrader.price_handler.store.base import PriceStore
from itrader.results import ResultsStore
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.simulation.time_generator import TimeGenerator
from itrader.universe import Universe
# Deliberately NOT taken from the ``itrader.venues`` barrel — see the module
# docstring of ``venues/bundles.py``.
from itrader.venues.bundles import VenueBundles

if TYPE_CHECKING:
	# Annotation-only, so no fee-model or exchange concretion lands on this module's
	# runtime import graph. The annotations are string forward-refs.
	from itrader.execution_handler.fee_model.base import FeeModel
	from itrader.execution_handler.exchanges.base import AbstractExchange


@dataclass
class Engine:
	"""The wired component graph ``compose_engine`` returns.

	A dumb holder of pre-built handlers/read-models. Fields are declared in wiring
	order so the downstream session-setup / run-loop ordering stays byte-exact.
	"""

	global_queue: "EventBus"
	clock: BacktestClock
	# The BASE store/feed types, so live's ``store=None`` + ``LiveBarFeed`` satisfy
	# ``mypy --strict``. No default: a default would break the dataclass
	# required-field ordering that follows.
	store: Optional[PriceStore]
	feed: BarFeed
	strategies_handler: StrategiesHandler
	screeners_handler: ScreenersHandler
	portfolio_handler: PortfolioHandler
	execution_handler: ExecutionHandler
	order_handler: OrderHandler
	event_handler: EventHandler
	time_generator: TimeGenerator
	# The symbol->Instrument read-model, set onto the engine by the runner's session
	# wiring. None until then, populated before the run loop.
	universe: Optional[Universe] = None
	# The OPTIONAL results sink, forwarded already-built by the FACTORY — this seam
	# NEVER constructs one. Only the ResultsStore ABC is referenced, so the concrete
	# SqlResultsStore stays out of the import graph and persist=False is SQL-inert.
	results_store: Optional[ResultsStore] = None


def compose_engine(
	ctx: "EngineContext", *,
	venue_bundles: "VenueBundles",
	results_store: Optional["ResultsStore"] = None,
	alert_sink: Optional[Any] = None,
	system_store: Optional[Any] = None,
	error_policy: Optional[Any] = None,
	strategy_catalog: Optional[Any] = None,
	exchange_registry: Optional[dict[tuple[str, str], "Optional[AbstractExchange]"]] = None,
	portfolio_factory: Optional[Any] = None,
	route_orders_by_account: bool = False) -> Engine:
	"""Wire the shared component graph from a SPEC-FREE infra ``ctx``.

	The seam takes no ``spec``: the store/feed read-models ride on ``ctx``, so compose
	never reads ``data`` / ``start`` / ``end`` / ``timeframe`` and never constructs a
	store or feed itself. The WHAT-to-run description (strategies / portfolios / dates /
	ticker) stays FACTORY-LOCAL and never crosses this seam.

	Several parameters are typed ``Optional[Any]`` rather than their real type so no
	concretion lands on this module's import graph — the backtest-import-inertness gate.

	Parameters
	----------
	ctx : EngineContext
		The frozen mode-injection bundle: ``bus``, ``config``, ``environment`` and
		``sql_engine`` (which select the handler-owned storage backends), ``feed``
		(required, per-mode) and ``store`` (real in backtest, ``None`` in live).
	venue_bundles : VenueBundles
		The REQUIRED, already-built ``(venue, account_id)`` bundle memo. Both
		``ExecutionHandler`` and ``PortfolioHandler`` hold the SAME instance, so each
		venue+account has one exchange and one account factory. Deliberately NOT
		re-surfaced on ``Engine``: a second read path is how two callers end up with
		divergent views.
	results_store : Optional[ResultsStore]
		The results sink forwarded onto ``Engine``. This seam never constructs one.
	alert_sink : Optional[Any]
		The CRITICAL/halt egress injected into ``ErrorHandler``. ``None`` in backtest.
	system_store : Optional[Any]
		The durable KV store for the ``state.last_error`` persist. ``None`` in backtest.
	error_policy : Optional[Any]
		The live publish-and-continue policy, used BOTH as the dispatcher's failure
		policy and as ``ErrorHandler``'s ``failure_sink``. ``None`` builds a
		``FailFastPolicy`` instead and leaves the handler without a tripwire.
	strategy_catalog : Optional[Any]
		The strategy-TYPE allowlist threaded into ``StrategiesHandler``. It can only
		ride in from the caller, since ``itrader`` must not import a concrete strategy
		class. ``None`` leaves ``add``'s LOUD-reject reachable, so no external payload
		can be instantiated.
	exchange_registry : Optional[dict[tuple[str, str], Optional[AbstractExchange]]]
		The composition-root-owned ``(venue, account_id) -> exchange`` map. ``None``
		creates it here; the live root passes its OWN reference so
		``VenueAccountManager.bring_online`` writes the SAME map ``ExecutionHandler``
		reads. Stays a plain dict so the tree-wide ``.exchanges`` readers are untouched.
	portfolio_factory : Optional[Any]
		The factory ``PortfolioHandler`` builds every account leaf through. ``None``
		builds one here over a ``ComputeAccountAuthority`` (bundles-only, never raises);
		the live root injects one holding the real ``VenueAccountManager`` authority,
		where a missing/disabled/not-online account RAISES at materialize.
	route_orders_by_account : bool
		Whether ``ExecutionHandler`` resolves each order's venue account from its
		portfolio. ASYMMETRIC BY DESIGN, and the asymmetry is the point: ``False``
		(backtest) injects no read-model and resolves ``DEFAULT_ACCOUNT_ID``
		unconditionally, because every backtest portfolio has ``account_id=None`` and
		injecting the read-model there would turn the byte-exact oracle route into a
		refusal. ``True`` (live) injects the portfolio handler, so a portfolio naming no
		account is REFUSED rather than routed through whatever session happens to be
		registered as the default. An explicit keyword rather than a read of
		``ctx.environment``, so a live system built with a test environment string
		still routes by account.

	Returns
	-------
	Engine
		The wired graph. Handlers are constructed in dependency order; ``universe`` is
		still ``None`` and is set by the runner's session wiring.
	"""
	store = ctx.store
	feed = ctx.feed

	# Staged determinism seam with no domain consumer yet — result determinism comes
	# from passing the bar time explicitly to record_metrics in the runner.
	clock = BacktestClock()

	# ScreenersHandler is a deferred subsystem (ignore_errors override).
	screeners_handler = ScreenersHandler(ctx.bus, feed)  # type: ignore[no-untyped-call]
	# The oracle drives THIS default arm through compose, so the factory + authority
	# are exercised and a factory-only edit cannot go false-green. COMPUTE_VENUE is the
	# one home of the 'paper' name.
	if portfolio_factory is None:
		portfolio_factory = PortfolioFactory(
			authority=ComputeAccountAuthority(
				venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE),
			environment=ctx.environment,
			sql_engine=ctx.sql_engine)
	portfolio_handler = PortfolioHandler(
		ctx.bus, environment=ctx.environment, sql_engine=ctx.sql_engine,
		portfolio_factory=portfolio_factory)

	# Constructed BEFORE the order handler so the admission gate's fee-model provider
	# can close over the resolved exchange. Construction-order only — runtime stays
	# queue-mediated.
	#
	# The determinism seam rides on ``ctx.rng`` and reaches the exchange through the
	# PLUGIN, so the handler carries no rng of its own: the ctx object itself is what
	# flows, never a fresh equal-seeded one — identity is the contract.
	if exchange_registry is None:
		exchange_registry = {}
	seed_exchange_registry(exchange_registry, venue_bundles)
	execution_handler = ExecutionHandler(
		ctx.bus, exchange_registry=exchange_registry,
		portfolio_read_model=portfolio_handler if route_orders_by_account else None)

	def fee_model_provider(venue: str, account_id: str) -> "Optional[FeeModel]":
		"""The CURRENT fee model of the exchange serving ``(venue, account_id)``.

		Both the lookup and the ``fee_model`` read MUST stay inside the call; the
		closure must never capture an exchange or, worse, ``exchange.fee_model``.
		``SimulatedExchange.update_config`` REBINDS that attribute after its atomic
		config swap, so the object is REPLACED rather than mutated — a captured
		reference would keep pricing admission reservations at a rate the exchange no
		longer charges, silently, with nothing raising. Resolving one exchange at wiring
		time would likewise price EVERY order against it, whatever venue fills it.

		``getattr(..., None)`` is the explicit "this venue exposes no fee model"
		contract, and also covers the unregistered pair. A MISS returns ``None``, never
		raises, because the order domain owns the degrade.
		"""
		return cast("Optional[FeeModel]",
			getattr(execution_handler.exchanges.get((venue, account_id)),
				"fee_model", None))

	# Thread the portfolio's margin settings into the order domain at construction so
	# the admission leverage cap and the margin reservation branch are gated correctly.
	# The Universe is injected later via order_handler.set_universe, since the runner
	# builds it after this construction.
	trading_rules = portfolio_handler.config_data.trading_rules

	# The signal store is handler-OWNED, derived from (environment, sql_engine) and NOT
	# re-surfaced on Engine — post-run accessors reach it through the owning handler,
	# matching every other persistence store.
	#
	# The two shorts-enabling flags read trading_rules, so this must be constructed
	# AFTER that binding. Both seams are passed at construction on BOTH roots, never
	# assigned onto an already-built handler: portfolio_read_model satisfies
	# PortfolioReadModel structurally, so it IS the flat-detect the `remove` verb
	# consults on FILL — a read through an injected read-model, so the queue-only
	# contract holds — and strategy_catalog is the allowlist `add` resolves an
	# untrusted external strategy_type through.
	strategies_handler = StrategiesHandler(
		ctx.bus, feed,
		allow_short_selling=trading_rules.allow_short_selling,
		enable_margin=trading_rules.enable_margin,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine,
		strategy_catalog=strategy_catalog,
		portfolio_read_model=portfolio_handler)

	# order_config stays handler-owned — never a spec field. The order handler likewise
	# OWNS its storage init from (environment, sql_engine); `.storage` is read back below.
	resolved_order_config = OrderConfig.default()
	order_handler = OrderHandler(
		ctx.bus, portfolio_handler,
		order_config=resolved_order_config,
		fee_model_provider=fee_model_provider,
		enable_margin=trading_rules.enable_margin,
		portfolio_max_leverage=trading_rules.max_leverage,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine)

	# The SAME order_storage instance goes to the portfolio handler, so the BAR-route
	# liquidation forced-close registers its real Order in the exact mirror the
	# ReconcileManager reads. Oracle-dark: with no breaches the seam is never written.
	order_storage = order_handler.storage
	portfolio_handler.set_order_storage(order_storage)

	time_generator = TimeGenerator()

	# Both built HERE, the single mode-agnostic site beside the EventHandler. Backtest
	# passes all three None, so the ErrorHandler logs only — no escalate, persist or
	# count — and FailFastPolicy re-raises identically.
	error_handler = ErrorHandler(
		alert_sink=alert_sink,
		system_store=system_store,
		failure_sink=error_policy,
	)
	policy = error_policy if error_policy is not None else FailFastPolicy()

	# The TIME route's BarEvent source is the feed-owned factory.
	event_handler = EventHandler(
		strategies_handler,
		screeners_handler,
		portfolio_handler,
		order_handler,
		execution_handler,
		feed.generate_bar_event,
		ctx.bus,
		policy,
		error_handler,
	)

	return Engine(
		global_queue=ctx.bus,
		clock=clock,
		store=store,
		feed=feed,
		strategies_handler=strategies_handler,
		screeners_handler=screeners_handler,
		portfolio_handler=portfolio_handler,
		execution_handler=execution_handler,
		order_handler=order_handler,
		event_handler=event_handler,
		time_generator=time_generator,
		results_store=results_store,
	)
