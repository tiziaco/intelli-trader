"""Shared component-graph wiring seam + commission adapter (D-14/D-14a/D-15).

``compose_engine`` is the SHARED, mode-agnostic wiring seam both
``build_backtest_system`` (now) and a future ``build_live_system`` (fast-follow)
consume. It builds the component graph extracted from the fat
``BacktestTradingSystem.__init__`` body — queue, clock, store, feed, signal
store, strategies/screeners/portfolio/execution handlers, the commission
adapter, order handler, event handler — and returns them as a small ``Engine``
holder.

D-14a boundary: ``compose_engine`` must NOT hardcode a run-mode backend string
(no backtest/live literal). The mode-specific FACTORY (``build_backtest_system``)
selects the concrete backends (the order-storage + signal-store backends) via
their respective factories, plus the construction-time
``ExchangeConfig`` (with the complete symbol set already folded in — D-13/Trap 1)
and passes them IN. The seam wires the graph from those injected concretes,
staying run-mode-agnostic (mirrors the injected ``CommissionEstimator`` /
``PortfolioReadModel`` DI rationale).

D-15: ``FeeModelCommissionEstimator`` promotes the inline ``_estimate_commission``
closure to a typed adapter conforming to the ``core`` ``CommissionEstimator``
Protocol. It holds the EXCHANGE ref and reads ``exchange.fee_model`` at CALL
time (late binding) — ``update_config`` may rebuild the fee model, and a stale
capture would silently use the wrong estimator. The golden run pins fees 0
(ZeroFeeModel), so the estimate is ``Decimal("0")`` exactly as today.

Indentation: TABS (``trading_system/`` package convention).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from itrader.core.clock import BacktestClock
from itrader.config import OrderConfig
from itrader.events_handler.bus import EventBus
from itrader.events_handler.error_handler import ErrorHandler
from itrader.events_handler.error_policy import FailFastPolicy
from itrader.events_handler.full_event_handler import EventHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.price_handler.feed.base import BarFeed
from itrader.price_handler.store.base import PriceStore
from itrader.results import ResultsStore
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.simulation.time_generator import TimeGenerator
from itrader.universe import Universe


class FeeModelCommissionEstimator:
	"""Typed commission-estimate adapter over the exchange (D-15, Trap 2).

	Promotes the inline ``_estimate_commission`` closure. Holds the EXCHANGE
	REF and reads ``exchange.fee_model`` inside ``__call__`` (LATE BINDING) —
	NEVER captures ``fee_model`` at ``__init__``. ``update_config`` may rebuild
	the exchange's fee model; a construction-time capture would silently use a
	stale estimator. Conforms structurally to the ``core`` ``CommissionEstimator``
	Protocol (``(Decimal, Decimal) -> Decimal``).

	The ``side="buy", order_type="market"`` admission convention is preserved
	(D-04). A non-``SimulatedExchange`` (or a None exchange) yields ``Decimal("0")``
	— byte-identical to the closure's isinstance guard, so the golden run's
	ZeroFeeModel estimate stays exactly 0.
	"""

	def __init__(self, exchange: Optional[Any]) -> None:
		# Hold the REF only — late binding reads exchange.fee_model in __call__.
		self._exchange = exchange

	def __call__(self, quantity: Decimal, price: Decimal) -> Decimal:
		if not isinstance(self._exchange, SimulatedExchange):
			return Decimal("0")
		return self._exchange.fee_model.calculate_fee(
			quantity, price, side="buy", order_type="market")


@dataclass
class Engine:
	"""The wired component graph ``compose_engine`` returns (D-04).

	A dumb holder of the pre-built handlers/read-models. The FACTORY constructs
	the ``BacktestRunner`` over this engine and injects both into the thin
	``BacktestTradingSystem`` holder. Fields are populated in wiring order so the
	downstream session-setup / run-loop ordering stays byte-exact (Trap 4/6).
	"""

	global_queue: "EventBus"
	clock: BacktestClock
	# D-04/D-01: widened to the BASE store/feed types so live's ``store=None`` +
	# ``LiveBarFeed`` satisfy ``mypy --strict`` (backtest injects the concrete
	# ``CsvPriceStore`` + ``BacktestBarFeed``, a safe subtype). No default here:
	# ``compose_engine`` always passes both explicitly off ``ctx``, and a default
	# would break the dataclass required-field ordering that follows.
	store: Optional[PriceStore]
	feed: BarFeed
	strategies_handler: StrategiesHandler
	screeners_handler: ScreenersHandler
	portfolio_handler: PortfolioHandler
	execution_handler: ExecutionHandler
	order_handler: OrderHandler
	event_handler: EventHandler
	time_generator: TimeGenerator
	# INST-03 (D-06/D-08): the symbol->Instrument read-model, constructed at the
	# Trap-4 wiring point in the runner (_initialise_backtest_session) and set
	# onto the engine there. None until wiring — populated before the run loop.
	universe: Optional[Universe] = None
	# RESULT-01 (D-02/D-14a): the OPTIONAL results sink, forwarded already-built by
	# the FACTORY (build_backtest_system) — this seam NEVER constructs one. Default
	# None keeps the oracle path store-free (D-04). Only the ResultsStore ABC is
	# referenced here (SQL-free); the concrete SqlResultsStore stays out of the
	# import graph so persist=False is SQL-import-inert (GATE-01).
	results_store: Optional[ResultsStore] = None


def compose_engine(
	ctx: "EngineContext", *,
	exchange_config: Optional[Any] = None,
	results_store: Optional["ResultsStore"] = None,
	alert_sink: Optional[Any] = None,
	system_store: Optional[Any] = None,
	error_policy: Optional[Any] = None) -> Engine:
	"""Wire the shared component graph from a SPEC-FREE infra ``ctx`` (D-01/D-04).

	Spec-free seam (D-04, the Phase-06.1 centerpiece): ``compose_engine`` no longer
	takes a ``spec``. The store/feed READ-MODELS ride on ``ctx`` (``ctx.store`` /
	``ctx.feed``, D-01) — the mode factory selects and injects them — so compose
	no longer reads ``data`` / ``start`` / ``end`` / ``timeframe`` (those only ever
	built the store/feed) and no longer constructs a ``CsvPriceStore`` /
	``BacktestBarFeed`` itself. The only two remaining inputs are HOW/WHERE to
	execute + persist, so they become explicit keyword params, NOT a spec read:
	``exchange_config`` (the already-seeded ``ExchangeConfig``, ``None`` for live's
	default) and ``results_store`` (the OPTIONAL sink, ``None`` on the oracle path).
	The WHAT-to-run description (strategies / portfolios / dates / ticker) stays
	FACTORY-LOCAL and never crosses this shared seam — backtest keeps its
	``SystemSpec``, live keeps a tiny venue-spec object.

	The shared event transport is ``ctx.bus`` (the composition root owns the bus),
	and the run-mode infra knobs (``ctx.environment`` / ``ctx.sql_engine``) select
	the handler-OWNED storage backends. The ``order_config`` stays handler-owned
	(``OrderConfig.default()``, D-04 lean).

	Parameters
	----------
	ctx : EngineContext
		The frozen mode-injection bundle: ``bus`` (the shared transport injected into
		every handler + the ``Engine`` holder), ``config`` (carried, unread until P9),
		``environment`` (selects handler-owned storage backends), ``feed`` (the REQUIRED
		per-mode read-model), ``store`` (REAL in backtest / ``None`` in live, D-02),
		``sql_engine`` (``None`` for backtest — keeps the path SQL-import-inert, GATE-01).
	exchange_config : Optional[Any]
		The already-seeded ``ExchangeConfig`` threaded into the ``ExecutionHandler``
		(the complete symbol set folded in by the factory, D-13/Trap 1). ``None`` yields
		the ``ExecutionHandler`` default (live's behavior today — no change).
	results_store : Optional[ResultsStore]
		The OPTIONAL results sink forwarded onto the ``Engine`` holder (RESULT-01/D-04).
		``None`` on the oracle path keeps it store-free AND SQL-import-inert (GATE-01).
	alert_sink : Optional[Any]
		The CRITICAL/halt egress collaborator injected into the ``ErrorHandler`` (D-03/D-04).
		``build_live_system`` passes a ``LogAlertSink``; ``None`` on the backtest path (no
		egress). Typed ``Optional[Any]`` so no ``LogAlertSink`` concrete lands on the
		backtest import graph.
	system_store : Optional[Any]
		The durable KV store for the D-17 ``state.last_error`` persist, injected into the
		``ErrorHandler``. ``build_live_system`` passes a gated ``SystemStore``; ``None`` in
		backtest (no persist). Typed ``Optional[Any]`` — ``storage.system_store`` is in the
		OKX-inertness _FORBIDDEN list, so it is NEVER module-imported here.
	error_policy : Optional[Any]
		The live publish-and-continue ``HandlerErrorPolicy`` (D-06) selected here as the
		dispatcher's failure policy AND handed to the ``ErrorHandler`` as its ``failure_sink``
		(the shared tripwire surface for the off-thread okx FILL_TRANSLATION count). ``None``
		→ a ``FailFastPolicy`` is built instead (byte-exact oracle re-raise) and the
		``ErrorHandler`` gets no tripwire (backtest logs only).
	"""
	# D-01/D-04: store + feed are INJECTED on ctx by the mode factory — compose reads
	# them uniformly (backtest: real CsvPriceStore + BacktestBarFeed; live: store=None
	# + LiveBarFeed). The construction MOVED to the factory so the seam is store/feed-
	# agnostic and never reads a backtest-shaped run description.
	store = ctx.store
	feed = ctx.feed

	# Determinism seam (D-09/D-10): the injected BacktestClock staged on the
	# determinism seam (no domain consumer yet — result determinism comes from
	# passing the bar time explicitly to record_metrics in the runner).
	clock = BacktestClock()

	# ScreenersHandler is a deferred subsystem (ignore_errors override).
	screeners_handler = ScreenersHandler(ctx.bus, feed)  # type: ignore[no-untyped-call]
	portfolio_handler = PortfolioHandler(ctx.bus, environment=ctx.environment, sql_engine=ctx.sql_engine)

	# Execution handler is constructed BEFORE the order handler so the admission
	# gate's commission estimator can adapt the simulated exchange's fee model
	# (D-04). The construction-time ExchangeConfig threads the complete symbol
	# set (D-13). Construction-order only — runtime stays queue-mediated.
	execution_handler = ExecutionHandler(ctx.bus, exchange_config=exchange_config)

	# Commission estimator for the admission cash-reservation gate (D-04/D-15):
	# the typed FeeModelCommissionEstimator adapter holds the exchange ref and
	# reads fee_model at call time (late binding). The golden run pins fees 0,
	# so the reservation equals price x quantity exactly (value-preserving).
	simulated_exchange = execution_handler.exchanges.get('simulated')
	commission_estimator = FeeModelCommissionEstimator(simulated_exchange)

	# Plan 02-03 (D-09/D-14): thread the portfolio's margin settings into the
	# order domain at construction so the admission leverage cap (D-04) and the
	# margin reservation branch (D-08) are gated correctly. Read from the
	# portfolio config's TradingRules (config_data.trading_rules). With the
	# default PortfolioConfig (enable_margin=False / max_leverage=1) the order
	# domain stays on the spot byte-exact arm. The Universe itself is injected
	# later via order_handler.set_universe at the Trap-4 wiring point (the runner
	# builds it after this construction).
	trading_rules = portfolio_handler.config_data.trading_rules

	# Signal-store sink (read-model): the handler now OWNS its signal-store init
	# from (environment, sql_engine) (CTX-02/02-02) — NOT injected here, and NOT
	# re-surfaced on the Engine holder (D-03). The post-run accessors reach the
	# store through the owning handler (engine.strategies_handler.signal_store),
	# matching the store-access convention every other persistence store follows.
	#
	# SHORT-01/D-07: thread the two shorts-enabling flags from trading_rules into
	# the registration gate. Constructed AFTER the trading_rules binding so the
	# flags are available; both default off → SMA_MACD (LONG_ONLY) stays admitted
	# and the oracle stays byte-exact.
	strategies_handler = StrategiesHandler(
		ctx.bus, feed,
		allow_short_selling=trading_rules.allow_short_selling,
		enable_margin=trading_rules.enable_margin,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine)

	# order_config stays handler-owned (D-04 lean, P1 D-03) — never a spec field.
	resolved_order_config = OrderConfig.default()
	# The order handler OWNS its storage init from (environment, sql_engine)
	# (CTX-02/02-02) — NOT injected here; `.storage` is read back below.
	order_handler = OrderHandler(
		ctx.bus, portfolio_handler,
		order_config=resolved_order_config,
		commission_estimator=commission_estimator,
		enable_margin=trading_rules.enable_margin,
		portfolio_max_leverage=trading_rules.max_leverage,
		environment=ctx.environment,
		sql_engine=ctx.sql_engine)

	# Read the handler-owned storage back for wiring (02-03). The SAME
	# order_storage instance is injected into the portfolio handler so the
	# BAR-route liquidation forced-close registers its real Order in the exact
	# mirror the ReconcileManager reads (the set_order_storage write-seam, the
	# analog of set_universe). Oracle-dark: with no breaches the seam is never
	# written, SMA_MACD byte-exact.
	order_storage = order_handler.storage
	portfolio_handler.set_order_storage(order_storage)

	time_generator = TimeGenerator()

	# D-01/D-03/D-04: build the ERROR-route consumer + select the handler-failure
	# policy HERE (the single mode-agnostic site, beside the EventHandler). The live
	# collaborators ride in as ``Optional[Any]`` kwargs (built by build_live_system);
	# backtest passes all three None so the ErrorHandler logs only (no escalate/persist/
	# count) and FailFastPolicy re-raises identically (oracle byte-exact). ``error_policy``
	# doubles as the ErrorHandler's failure_sink (the shared tripwire the off-thread okx
	# FILL_TRANSLATION event counts through, ERR-04) — None in backtest.
	error_handler = ErrorHandler(
		alert_sink=alert_sink,
		system_store=system_store,
		failure_sink=error_policy,
	)
	policy = error_policy if error_policy is not None else FailFastPolicy()

	# The TIME route's BarEvent source is the feed-owned factory (D-20).
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
