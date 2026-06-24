import queue
from collections.abc import Callable
from typing import TYPE_CHECKING, Any


from itrader.strategy_handler.strategies_handler import StrategiesHandler
from itrader.screeners_handler.screeners_handler import ScreenersHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.core.enums import ErrorSeverity, EventType

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
	# Type-only import: the events package pulls pandas at runtime, which
	# must not be imported as a side effect of loading the dispatcher
	# (keeps the module import light and stub-friendly in tests).
	from itrader.events_handler.events import ErrorEvent, Event


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
		global_queue: "queue.Queue[Any]",
	) -> None:
		self.strategies_handler = strategies_handler
		self.screeners_handler = screeners_handler
		self.portfolio_handler = portfolio_handler
		self.order_handler = order_handler
		self.execution_handler = execution_handler
		self.bar_event_source = bar_event_source
		self.global_queue = global_queue

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
				self.strategies_handler.calculate_signals,              # 3) new signals
			],
			EventType.SIGNAL: [self.order_handler.on_signal],
			EventType.ORDER: [self.execution_handler.on_order],
			EventType.FILL: [
				self.portfolio_handler.on_fill,   # 1) positions/cash
				self.order_handler.on_fill,       # 2) order-mirror reconciliation
			],
			EventType.SCREENER: [],   # explicit empty — consuming screeners is D-screener
			EventType.UPDATE: [],     # explicit empty — live API path consumes these (D-live)
			EventType.ERROR: [self._log_error_event],   # D-16: real log consumer
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
		exceptions route through the ``_on_handler_error`` policy seam.
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
				self._on_handler_error(event, handler)   # D-16 seam

	def _on_handler_error(self, event: "Event", handler: Callable[[Any], Any]) -> None:
		"""
		Handler-failure policy seam (D-16).

		Backtest policy is FAIL-FAST: re-raise the active exception
		unchanged — a handler failure must abort the run rather than
		silently corrupt state (T-04-15). The bare ``raise`` re-raises
		the exception active in the calling ``except`` block (the
		exception context propagates into calls made from except blocks).

		D-live override seam: the live system replaces this policy with
		publish-and-continue (emit an ErrorEvent onto the queue and keep
		draining) by overriding THIS method — ``_dispatch`` stays
		untouched.
		"""
		raise

	def _log_error_event(self, event: "ErrorEvent") -> None:
		"""
		The ERROR route's real consumer (D-17): structured log sink.

		Binds the ErrorEvent fields explicitly at a severity mapped from
		``event.severity`` (WARNING/CRITICAL/anything else -> ERROR).
		Never logs secrets — only the declared ErrorEvent fields.
		"""
		log_method = {
			ErrorSeverity.WARNING: self.logger.warning,
			ErrorSeverity.CRITICAL: self.logger.critical,
		}.get(event.severity, self.logger.error)
		context: dict[str, Any] = {
			"source": event.source,
			"error_type": event.error_type,
			"error_message": event.error_message,
			"operation": event.operation,
			"correlation_id": event.correlation_id,
		}
		portfolio_id = getattr(event, "portfolio_id", None)
		if portfolio_id is not None:
			context["portfolio_id"] = portfolio_id
		if event.details is not None:
			context["details"] = event.details
		log_method("Error event consumed", **context)
