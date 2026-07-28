"""Shared component-graph wiring seam.

``compose_engine`` is the SHARED, mode-agnostic wiring seam both
``build_backtest_system`` and ``build_live_system`` consume. It builds the
component graph — queue, clock, store, feed, signal store,
strategies/screeners/portfolio/execution handlers, the fee-model provider, order
handler, event handler — and returns them as a small ``Engine`` holder.

Boundary: ``compose_engine`` must NOT hardcode a run-mode backend string (no
backtest/live literal). The mode-specific FACTORY selects the concrete backends —
order storage, signal store, and the venue backends — and passes them IN. For
venues that means the factory builds an ``ExecutionVenueRegistry``, registers the
concrete plugin(s) with their RUN-DERIVED ``ExchangeConfig``, builds a real
(possibly EMPTY) ``ConnectorProvider``, and hands in a built ``VenueBundles``. A
concrete ``PaperVenuePlugin`` is mode-specific, so registering it here would be
exactly the hardcoded backend this boundary forbids. The seam takes no
``ExchangeConfig`` at all: it does not build an exchange, so it has no use for one.

The commission estimate is split across two owners. The WIRING half is here: a
``FeeModelProvider`` closure that dereferences ``exchange.fee_model`` at CALL time
(LATE BINDING — see the closure for why a captured reference is a silent defect).
The admission CONVENTION — the ``side`` and ``order_type`` an estimate is taken at
— is an admission-policy concern and lives in
``AdmissionManager._estimate_commission``. The golden run pins fees 0
(ZeroFeeModel), so the estimate is ``Decimal("0")``.

Indentation: TABS (``trading_system/`` package convention).
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
	# Concrete-type import for the fee-model PROVIDER annotation ONLY, mirroring
	# the guarded block in ``engine_context.py``. Guarded so no fee-model
	# concretion is pulled onto this module's import graph; the annotation is a
	# string forward-ref and stays unevaluated at runtime.
	from itrader.execution_handler.fee_model.base import FeeModel
	# The registry ELEMENT type, for the ``exchange_registry`` annotation only.
	# Guarded so ``AbstractExchange`` stays off this module's runtime import graph.
	from itrader.execution_handler.exchanges.base import AbstractExchange


@dataclass
class Engine:
	"""The wired component graph ``compose_engine`` returns.

	A dumb holder of the pre-built handlers/read-models. The FACTORY constructs
	the ``BacktestRunner`` over this engine and injects both into the thin
	``BacktestTradingSystem`` holder. Fields are populated in wiring order so the
	downstream session-setup / run-loop ordering stays byte-exact.
	"""

	global_queue: "EventBus"
	clock: BacktestClock
	# The BASE store/feed types, so live's ``store=None`` + ``LiveBarFeed`` satisfy
	# ``mypy --strict`` (backtest injects the concrete ``CsvPriceStore`` +
	# ``BacktestBarFeed``, a safe subtype). No default here: ``compose_engine``
	# always passes both explicitly off ``ctx``, and a default would break the
	# dataclass required-field ordering that follows.
	store: Optional[PriceStore]
	feed: BarFeed
	strategies_handler: StrategiesHandler
	screeners_handler: ScreenersHandler
	portfolio_handler: PortfolioHandler
	execution_handler: ExecutionHandler
	order_handler: OrderHandler
	event_handler: EventHandler
	time_generator: TimeGenerator
	# The symbol->Instrument read-model, constructed at the wiring point in the
	# runner (_initialise_backtest_session) and set onto the engine there. None
	# until wiring — populated before the run loop.
	universe: Optional[Universe] = None
	# The OPTIONAL results sink, forwarded already-built by the FACTORY — this seam
	# NEVER constructs one. Default None keeps the oracle path store-free. Only the
	# ResultsStore ABC is referenced here (SQL-free); the concrete SqlResultsStore
	# stays out of the import graph so persist=False is SQL-import-inert (GATE-01).
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

	Spec-free seam: ``compose_engine`` takes no ``spec``. The store/feed READ-MODELS
	ride on ``ctx`` — the mode factory selects and injects them — so compose never
	reads ``data`` / ``start`` / ``end`` / ``timeframe`` and never constructs a
	``CsvPriceStore`` / ``BacktestBarFeed`` itself. The only two remaining inputs are
	HOW/WHERE to execute + persist, so they are explicit keyword params rather than a
	spec read: ``venue_bundles`` (the built ``(venue, account_id)`` bundle memo,
	because the venue PLUGIN builds the exchange) and ``results_store`` (the OPTIONAL
	sink, ``None`` on the oracle path). The WHAT-to-run description (strategies /
	portfolios / dates / ticker) stays FACTORY-LOCAL and never crosses this shared
	seam — backtest keeps its ``SystemSpec``, live keeps a tiny venue-spec object.

	The shared event transport is ``ctx.bus`` (the composition root owns the bus),
	and the run-mode infra knobs (``ctx.environment`` / ``ctx.sql_engine``) select
	the handler-OWNED storage backends. The ``order_config`` stays handler-owned.

	Parameters
	----------
	ctx : EngineContext
		The frozen mode-injection bundle: ``bus`` (the shared transport injected into
		every handler + the ``Engine`` holder), ``config``, ``environment`` (selects
		handler-owned storage backends), ``feed`` (the REQUIRED per-mode read-model),
		``store`` (REAL in backtest / ``None`` in live), ``sql_engine`` (``None`` for
		backtest — keeps the path SQL-import-inert, GATE-01).
	route_orders_by_account : bool
		Whether ``ExecutionHandler`` resolves each order's VENUE ACCOUNT from its
		portfolio through the injected read-model. The injection is ASYMMETRIC BY
		DESIGN and the asymmetry is the point:

		* ``False`` (the BACKTEST default) injects NO read-model, so ``on_order``
		  resolves ``DEFAULT_ACCOUNT_ID`` unconditionally. Every backtest portfolio
		  has ``account_id=None``, so injecting the read-model there would turn the
		  byte-exact oracle route into a refusal.
		* ``True`` (passed by ``build_live_system``) injects the portfolio handler,
		  which satisfies ``PortfolioReadModel`` structurally. A live portfolio that
		  names no account is then REFUSED rather than routed through whatever
		  session happens to be registered as the default.

		It is an explicit keyword rather than a read of ``ctx.environment`` so a live
		system built with a test environment string still routes by account.
	venue_bundles : VenueBundles
		The REQUIRED, already-built ``(venue, account_id)`` bundle memo. The FACTORY
		constructs the registry, registers the concrete plugin(s) with their
		RUN-DERIVED ``ExchangeConfig``, builds the ``ConnectorProvider`` — a REAL,
		EMPTY one on the backtest path, never ``None`` — and hands the memo in.
		``ExecutionHandler`` then RESOLVES its exchange instead of minting one, and
		``PortfolioHandler`` holds the SAME instance, so both arms see one exchange
		and one account factory per venue+account.

		Deliberately NOT re-surfaced on the ``Engine`` holder: the handlers hold it,
		and a second read path is how two callers end up with divergent views.
	results_store : Optional[ResultsStore]
		The OPTIONAL results sink forwarded onto the ``Engine`` holder. ``None`` on the
		oracle path keeps it store-free AND SQL-import-inert (GATE-01).
	alert_sink : Optional[Any]
		The CRITICAL/halt egress collaborator injected into the ``ErrorHandler``.
		``build_live_system`` passes a ``LogAlertSink``; ``None`` on the backtest path
		(no egress). Typed ``Optional[Any]`` so no ``LogAlertSink`` concrete lands on
		the backtest import graph.
	system_store : Optional[Any]
		The durable KV store for the ``state.last_error`` persist, injected into the
		``ErrorHandler``. ``build_live_system`` passes a gated ``SystemStore``; ``None``
		in backtest (no persist). Typed ``Optional[Any]`` — ``storage.system_store`` is
		in the OKX-inertness _FORBIDDEN list, so it is NEVER module-imported here.
	error_policy : Optional[Any]
		The live publish-and-continue ``HandlerErrorPolicy``, selected here as the
		dispatcher's failure policy AND handed to the ``ErrorHandler`` as its
		``failure_sink`` (the shared tripwire surface for the off-thread okx
		FILL_TRANSLATION count). ``None`` → a ``FailFastPolicy`` is built instead
		(byte-exact oracle re-raise) and the ``ErrorHandler`` gets no tripwire.
	strategy_catalog : Optional[Any]
		The injected strategy-TYPE allowlist threaded into the ``StrategiesHandler``.
		Typed ``Optional[Any]`` for the SAME reason ``system_store`` is: ``itrader``
		must not import a concrete strategy class — proprietary strategies live in a
		private submodule — so the catalog can only ride in from the caller and no
		concrete type may land on this module's import graph. ``None`` (the backtest
		default) leaves the LOUD-reject on a catalog-less ``add`` reachable, so no
		external payload can be instantiated.
	exchange_registry : Optional[dict[tuple[str, str], Optional[AbstractExchange]]]
		The composition-root-owned ``(venue, account_id) -> exchange`` map. On the
		backtest / in-memory default it is ``None`` and CREATED here; the live root
		passes its OWN reference so ``VenueAccountManager.bring_online`` writes the
		SAME map ``ExecutionHandler`` reads. Either way the paper arm is seeded (and
		connected) through ``seed_exchange_registry``, so the handler does not
		privately own the registry. Extracting this map is what dissolves the
		four-node LIVE construction cycle, and it stays a plain dict so the tree-wide
		``.exchanges`` reader sites are untouched.
	portfolio_factory : Optional[Any]
		The REQUIRED, mode-agnostic ``PortfolioFactory`` the ``PortfolioHandler`` builds
		every portfolio's account leaf through. On the backtest / in-memory default it
		is ``None`` and BUILT here over a ``ComputeAccountAuthority`` (bundles-only,
		``account_id`` None, never raises) — so the oracle arm, which drives THIS
		default through compose, exercises the factory and a factory-only edit cannot
		go false-green. The live root injects a factory holding the real
		``VenueAccountManager`` authority, where a missing/disabled/not-online account
		RAISES at materialize. Typed ``Optional[Any]`` (GATE-01) so no venue concretion
		lands on this module's import graph.
	"""
	# store + feed are INJECTED on ctx by the mode factory — compose reads them
	# uniformly (backtest: real CsvPriceStore + BacktestBarFeed; live: store=None +
	# LiveBarFeed). The factory constructs them, so this seam is store/feed-agnostic
	# and never reads a backtest-shaped run description.
	store = ctx.store
	feed = ctx.feed

	# Determinism seam: the BacktestClock is staged here but has no domain consumer
	# yet — result determinism comes from passing the bar time explicitly to
	# record_metrics in the runner.
	clock = BacktestClock()

	# ScreenersHandler is a deferred subsystem (ignore_errors override).
	screeners_handler = ScreenersHandler(ctx.bus, feed)  # type: ignore[no-untyped-call]
	# The PortfolioHandler builds every portfolio's account leaf through the injected
	# PortfolioFactory — its SOLE leaf-builder — never an inline compute-account
	# builder or a handler-held VenueBundles. On the backtest / in-memory default the
	# caller passes no factory, so compose builds one over a ComputeAccountAuthority
	# (bundles-only, account_id None, never raises). The oracle drives THIS default
	# arm through compose, so the factory + authority are exercised and a
	# factory-only edit cannot go false-green. COMPUTE_VENUE is the one home of the
	# 'paper' name.
	if portfolio_factory is None:
		portfolio_factory = PortfolioFactory(
			authority=ComputeAccountAuthority(
				venue_bundles=venue_bundles, compute_venue=COMPUTE_VENUE),
			environment=ctx.environment,
			sql_engine=ctx.sql_engine)
	portfolio_handler = PortfolioHandler(
		ctx.bus, environment=ctx.environment, sql_engine=ctx.sql_engine,
		portfolio_factory=portfolio_factory)

	# Constructed BEFORE the order handler so the admission gate's fee-model
	# provider can close over the resolved exchange. Construction-order only —
	# runtime stays queue-mediated. The read-model is injected ONLY on the
	# account-routing (live) arm — see the route_orders_by_account docstring above
	# for why the backtest arm must stay on the unconditional default account.
	#
	# The handler RESOLVES its exchange through the injected VenueBundles instead of
	# minting one. The determinism seam rides on ``ctx.rng`` and reaches the exchange
	# through the PLUGIN, so the handler carries no rng of its own — the ctx object
	# itself is what flows, never a fresh equal-seeded one: identity is the contract.
	#
	# The (venue, account_id) -> exchange registry is composition-root-owned. On the
	# backtest / in-memory default it is CREATED here; the live root passes its OWN
	# reference so VenueAccountManager.bring_online writes the SAME map this handler
	# reads. Either way the paper arm is seeded (and connected) through the shared
	# execution-domain helper before the handler is built over the map.
	if exchange_registry is None:
		exchange_registry = {}
	seed_exchange_registry(exchange_registry, venue_bundles)
	execution_handler = ExecutionHandler(
		ctx.bus, exchange_registry=exchange_registry,
		portfolio_read_model=portfolio_handler if route_orders_by_account else None)

	# Fee-model PROVIDER for the admission cash-reservation gate. This seam is
	# WIRING only: hand the order domain the venue's CURRENT fee model and let
	# AdmissionManager own the admission convention. The golden run pins fees 0, so
	# the reservation equals price x quantity exactly.
	def fee_model_provider(venue: str, account_id: str) -> "Optional[FeeModel]":
		"""The CURRENT fee model of the exchange serving ``(venue, account_id)``.

		The closure captures ONLY the pair-keyed registry and takes the order's own
		pair as arguments, so the lookup happens INSIDE the call. Resolving a single
		exchange here at wiring time instead would price EVERY order's admission
		reservation against that one exchange, whatever venue actually fills it.

		Both the lookup and the ``fee_model`` read must stay inside the call — the
		closure must NEVER capture an exchange or, worse, ``exchange.fee_model``.
		``SimulatedExchange.update_config`` REBINDS that attribute right after its
		atomic config swap, so the object is REPLACED rather than mutated; a captured
		reference would keep pricing admission reservations at a rate the exchange no
		longer charges, silently, with nothing anywhere raising.

		``getattr(..., None)`` is the explicit "this venue exposes no fee model"
		contract. It ALSO covers the unregistered pair, whose ``.get`` yields ``None``
		— a MISS must return ``None``, never raise, because the order domain owns the
		degrade. AdmissionManager turns either ``None`` into a LOUD ``Decimal("0")``.
		"""
		return cast("Optional[FeeModel]",
			getattr(execution_handler.exchanges.get((venue, account_id)),
				"fee_model", None))

	# Thread the portfolio's margin settings into the order domain at construction
	# so the admission leverage cap and the margin reservation branch are gated
	# correctly. With the default PortfolioConfig (enable_margin=False /
	# max_leverage=1) the order domain stays on the spot byte-exact arm. The
	# Universe is injected later via order_handler.set_universe, since the runner
	# builds it after this construction.
	trading_rules = portfolio_handler.config_data.trading_rules

	# The signal-store sink is handler-OWNED, derived from (environment,
	# sql_engine) — NOT injected here, and NOT re-surfaced on the Engine holder.
	# Post-run accessors reach it through the owning handler
	# (engine.strategies_handler.signal_store), matching the store-access
	# convention every other persistence store follows.
	#
	# The two shorts-enabling flags thread from trading_rules into the registration
	# gate, so this must be constructed AFTER the trading_rules binding. Both
	# default off → SMA_MACD (LONG_ONLY) stays admitted, oracle byte-exact.
	#
	# The two heavy-lifecycle-verb seams are passed at construction on BOTH
	# composition roots, never assigned onto an already-built handler:
	#   - portfolio_read_model: `portfolio_handler` structurally satisfies the
	#     `PortfolioReadModel` Protocol, so it IS the flat-detect the `remove` verb
	#     consults on FILL — a READ through an injected read-model, never a
	#     cross-domain handler call, so the queue-only contract holds. Non-None on
	#     BOTH paths; backtest is unaffected because `strategies_handler.on_fill`
	#     is not on the backtest FILL route and STRATEGY_COMMAND routes to an empty
	#     list, so the pending-removal machinery is never driven there.
	#   - strategy_catalog: the access-control ALLOWLIST the `add` verb resolves an
	#     untrusted external `strategy_type` through. `None` in backtest, which
	#     keeps `add`'s LOUD-reject reachable.
	# Neither changes the oracle: no signal-path code reads either.
	strategies_handler = StrategiesHandler(
		ctx.bus, feed,
		allow_short_selling=trading_rules.allow_short_selling,
		enable_margin=trading_rules.enable_margin,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine,
		strategy_catalog=strategy_catalog,
		portfolio_read_model=portfolio_handler)

	# order_config stays handler-owned — never a spec field.
	resolved_order_config = OrderConfig.default()
	# The order handler OWNS its storage init from (environment, sql_engine) — NOT
	# injected here; `.storage` is read back below.
	order_handler = OrderHandler(
		ctx.bus, portfolio_handler,
		order_config=resolved_order_config,
		fee_model_provider=fee_model_provider,
		enable_margin=trading_rules.enable_margin,
		portfolio_max_leverage=trading_rules.max_leverage,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine)

	# Read the handler-owned storage back for wiring. The SAME order_storage
	# instance is injected into the portfolio handler so the BAR-route liquidation
	# forced-close registers its real Order in the exact mirror the ReconcileManager
	# reads. Oracle-dark: with no breaches the seam is never written.
	order_storage = order_handler.storage
	portfolio_handler.set_order_storage(order_storage)

	time_generator = TimeGenerator()

	# The ERROR-route consumer and the handler-failure policy are both built HERE —
	# the single mode-agnostic site, beside the EventHandler. The live collaborators
	# ride in as ``Optional[Any]`` kwargs; backtest passes all three None, so the
	# ErrorHandler logs only (no escalate/persist/count) and FailFastPolicy re-raises
	# identically. ``error_policy`` doubles as the ErrorHandler's failure_sink — the
	# shared tripwire the off-thread okx FILL_TRANSLATION event counts through.
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
