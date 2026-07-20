import queue
from collections.abc import Callable
from typing import TYPE_CHECKING, Any


from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.bus import EventBus
from itrader.core.enums import EventType

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# Type-only imports: the events package pulls pandas at runtime, which
	# must not be imported as a side effect of loading the dispatcher
	# (keeps the module import light and stub-friendly in tests). The
	# injected policy + consumer are also type-only here — the concretes are
	# built in ``compose_engine`` and passed in (D-01/D-04/D-06).
	from itrader.events_handler.events import Event
	from itrader.events_handler.error_policy import HandlerErrorPolicy
	from itrader.events_handler.error_handler import ErrorHandler


class EventHandler(object):
	"""
	Encapsulates all components associated with the engine of the
	trading system. This includes the order handler (with its risk manager
	and position sizer), the portfolio handler and the execution handler
	(with its transaction cost model).

	Routing is data: ``self.routes`` maps each ``EventType`` to the list
	of handler callables that consume it — LIST ORDER IS EXECUTION ORDER
	(D-14). Handlers stay passive: there is no registration API; the
	registry is one reviewable literal owned by this class.

	Parameters
	----------
	bar_event_source : `Callable`
		The feed-backed BarEvent factory the TIME route invokes
		(``BacktestBarFeed.generate_bar_event`` — Plan 07-02, D-20: the
		data engine owns BarEvent production).
	global_queue : `Queue`
		The global events queue of the trading system.
	"""

	def __init__(
		self,
		strategies_handler: StrategiesHandler,
		screeners_handler: ScreenersHandler,
		portfolio_handler: PortfolioHandler,
		order_handler: OrderHandler,
		execution_handler: ExecutionHandler,
		bar_event_source: Callable[[Any], Any],
		global_queue: "EventBus",
		error_policy: "HandlerErrorPolicy",
		error_handler: "ErrorHandler",
	) -> None:
		self.strategies_handler = strategies_handler
		self.screeners_handler = screeners_handler
		self.portfolio_handler = portfolio_handler
		self.order_handler = order_handler
		self.execution_handler = execution_handler
		self.bar_event_source = bar_event_source
		self.global_queue = global_queue

		# D-06: the injected handler-failure policy. ``_dispatch``'s except-block
		# routes a raising handler through it — ``FailFastPolicy`` (bare re-raise,
		# byte-exact oracle) on the backtest/replay path, the live
		# publish-and-continue ``ErrorPolicy`` on the daemon path. Selected + built
		# in ``compose_engine`` (the single mode-agnostic site), never here.
		self._error_policy = error_policy
		# D-01: the ERROR-route consumer. Owns severity-mapped logging + CRITICAL
		# alert-sink escalation + ``last_error`` persistence + the FILL_TRANSLATION
		# counting seam. Built in ``compose_engine`` with its injected collaborators
		# (``None`` on the backtest path — logs only, no egress/persist/count).
		self.error_handler = error_handler

		self.logger = get_itrader_logger().bind(component="FullEventHandler")

		# THE dispatch order. List order IS execution order (D-14/D-17).
		# One reviewable literal — change routing here and nowhere else.
		# Return type is Any: the dispatcher ignores handler return values
		# (some collaborators return status values for their own callers).
		self.routes: dict[EventType, list[Callable[[Any], Any]]] = {
			EventType.TIME: [
				self.screeners_handler.screen_markets,
				self.bar_event_source,
			],
			EventType.BAR: [
				self.portfolio_handler.update_portfolios_market_value,  # 1) mark-to-market
				self.execution_handler.on_market_data,                  # 2) resting-order matching
				self.strategies_handler.on_bar,                         # 3) new signals
			],
			EventType.SIGNAL: [self.order_handler.on_signal],
			EventType.ORDER: [self.execution_handler.on_order],
			EventType.ORDER_ACK: [self.order_handler.on_order_ack],  # D-06: persist venue ack
			EventType.FILL: [
				self.portfolio_handler.on_fill,   # 1) positions/cash
				self.order_handler.on_fill,       # 2) order-mirror reconciliation
			],
			EventType.SCREENER: [],   # explicit empty — consuming screeners is D-screener
			EventType.UPDATE: [],     # explicit empty — live API path consumes these (D-live)
			EventType.UNIVERSE_UPDATE: [],  # explicit empty — live consumers wired live-only in plan 05 (backtest stays inert)
			EventType.UNIVERSE_POLL: [],       # NEW — live-only consumers wired live-only in plan 07 (backtest stays inert)
			EventType.STRATEGY_COMMAND: [],    # NEW — live-only consumers wired live-only in plan 07 (backtest stays inert)
			EventType.BARS_LOADED: [],         # NEW — live-only consumers wired live-only in plan 07 (backtest stays inert)
			EventType.BARS_LOAD_FAILED: [],    # NEW — live-only consumers wired live-only in plan 07 (backtest stays inert)
			EventType.STREAM_STATE: [],        # NEW (BUS-03) — CONTROL-plane connector stream up/down; live-only consumers wired in later phases (backtest stays inert)
			EventType.CONNECTOR_FATAL: [],     # NEW (BUS-03) — CONTROL-plane connector fatal -> halt; live-only consumers wired in later phases (backtest stays inert)
			EventType.CONFIG_UPDATE: [],       # NEW (BUS-03) — CONTROL-plane scoped runtime config change; live-only consumers wired in later phases (backtest stays inert)
			EventType.ERROR: [self.error_handler.on_error],   # D-01: formalized ERROR-route consumer
		}

		self.logger.info('Event Handler initialized')

	def process_events(self) -> None:
		"""
		Drain the global queue and dispatch every event through the
		routing registry.

		Race-free drain (D-15): ``get_nowait()`` + ``queue.Empty`` ->
		``break`` — no ``empty()`` precheck, no TOCTOU window.
		"""
		while True:
			try:
				event = self.global_queue.get_nowait()
			except queue.Empty:
				break
			self._dispatch(event)

	def _dispatch(self, event: "Event") -> None:
		"""
		Route a single event to its registered handlers, in list order.

		Unknown event types raise ``NotImplementedError`` (KB1 — silent
		drops are a tampering risk, T-04-18). Unexpected handler
		exceptions route through the injected ``_error_policy`` seam
		(D-06: FailFastPolicy re-raises on backtest/replay, ErrorPolicy
		publishes-and-continues on the live path).
		"""
		try:
			handlers = self.routes[event.type]
		except KeyError:
			raise NotImplementedError(
				f"EventHandler: unsupported event type {event.type!r}"
			)
		for handler in handlers:
			try:
				handler(event)
			except Exception:
				# D-06: the injected policy owns the except-block decision. A bare
				# ``raise`` from inside FailFastPolicy.on_handler_error re-raises the
				# active exception identically (oracle byte-exact); ErrorPolicy emits
				# an ErrorEvent and returns so the live loop keeps draining.
				self._error_policy.on_handler_error(event, handler)
