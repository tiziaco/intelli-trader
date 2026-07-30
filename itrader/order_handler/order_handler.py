from decimal import Decimal
from typing import Any, List, Dict, Optional

from itrader.core.commission_estimator import FeeModelProvider
from itrader.core.portfolio_read_model import PortfolioReadModel
from itrader.config import OrderConfig
from .base import OrderStorage
from .order import Order
from ..core.enums import OrderStatus, MarketExecution
from ..core.ids import OrderId, PortfolioId
from .order_validator import EnhancedOrderValidator
from .order_manager import OrderManager
from ..events_handler.bus import EventBus
from ..events_handler.events import SignalEvent, OrderEvent, OrderAckEvent, FillEvent
from .storage import build_order_storage
from ..universe import Universe

from itrader.logger import get_itrader_logger


class OrderHandler:
	"""
	Interface layer between the event system and OrderManager.

	Receives events (SignalEvent, FillEvent, OrderAckEvent), delegates every
	business decision to OrderManager, and is the ONLY side of the pair that
	touches the queue — the manager returns OperationResults carrying
	OrderEvents and this handler performs all puts.
	"""
	def __init__(self, global_queue: "EventBus", portfolio_handler: PortfolioReadModel,
	             order_storage: Optional[OrderStorage] = None,
	             market_execution: "str | MarketExecution | None" = None,
	             fee_model_provider: Optional[FeeModelProvider] = None,
	             order_config: Optional[OrderConfig] = None,
	             enable_margin: bool = False,
	             portfolio_max_leverage: Decimal = Decimal("1"),
	             *,
	             environment: str = "backtest",
	             sql_engine: "Optional[Any]" = None) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		portfolio_handler: `PortfolioReadModel`
			The narrow portfolio read boundary; PortfolioHandler satisfies
			this Protocol structurally.
		order_storage: `OrderStorage`, optional
			The order storage for storage operations. If None, uses InMemoryOrderStorage.
		order_config: `OrderConfig`, optional
			Order-domain config carrying ``market_execution``, forwarded to
			OrderManager. None -> ``OrderConfig.default()`` ("immediate").
		market_execution: str | MarketExecution, optional
			DEPRECATED backward-compat override, forwarded to OrderManager,
			which folds it into an ``OrderConfig``. Options:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Queue market orders for next bar execution (realistic backtesting)
		fee_model_provider: FeeModelProvider, optional
			``(venue, account_id) -> FeeModel | None`` — the CURRENT fee model of
			the exchange serving an order's pair, forwarded to OrderManager's
			admission reservation gate. The admission convention for reading it
			(which side/order type the estimate is taken at) and the resolution
			of the pair itself both live in ``AdmissionManager``, not here and
			not in the provider. None (or a provider returning None) -> zero
			estimate.
		"""
		self.global_queue = global_queue
		self.portfolio_handler = portfolio_handler

		self.logger = get_itrader_logger().bind(component="OrderHandler")

		# `.storage` exists as the wiring seam `build_handler_graph` reads back for
		# `portfolio_handler.set_order_storage(...)`, NOT as a read path: the same
		# instance goes to OrderManager, which owns every storage read
		# (facade -> manager -> storage).
		self.storage = order_storage or build_order_storage(environment, sql_engine=sql_engine)

		self.order_manager = OrderManager(
			self.storage,
			self.logger,
			market_execution,
			portfolio_handler,
			fee_model_provider=fee_model_provider,
			order_config=order_config,
			enable_margin=enable_margin,
			portfolio_max_leverage=portfolio_max_leverage,
		)
		self.market_execution = self.order_manager.market_execution

		self.order_validator = EnhancedOrderValidator(portfolio_handler)

		self.logger.info('Order Handler initialized', market_execution=self.market_execution)

	def set_universe(self, universe: Universe) -> None:
		"""Inject the symbol→Instrument read-model into the order domain.

		Forwards to ``OrderManager.set_universe`` → ``AdmissionManager``, where the
		order/risk leverage cap reads ``Instrument.max_leverage``. Set late — the
		runner builds the ``Universe`` after the order handler is constructed — so
		wiring must call this alongside ``SimulatedExchange.set_universe``.
		"""
		self.order_manager.set_universe(universe)

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update order-domain configuration at runtime.

		Delegates to ``OrderManager.update_config``.

		Raises
		------
		ConfigurationError
			If the merged config fails validation; the cached
			``market_execution`` mirror is then left untouched.
		"""
		self.order_manager.update_config(updates)
		self.market_execution = self.order_manager.market_execution

	def on_signal(self, signal_event: SignalEvent) -> None:
		"""
		Process signal event through OrderManager and generate OrderEvents.

		Parameters
		----------
		signal_event : `SignalEvent`
			The signal event generated from the strategy module
		"""
		self.logger.debug('Processing signal %s => %s, %s $ (qty: %s)', 
						signal_event.ticker, signal_event.action, 
						round(signal_event.price, 4), signal_event.quantity)

		operation_results = self.order_manager.process_signal(signal_event)
		
		for result in operation_results:
			if result.order_events:
				for order_event in result.order_events:
					self.global_queue.put(order_event)
					self.logger.debug('OrderEvent sent to execution handler: %s', order_event)

	
	def on_fill(self, fill_event: FillEvent) -> None:
		"""Reconcile the order mirror from an exchange fill event.

		Reconciliation may cancel bracket children orphaned by a terminal parent;
		the manager returns their CANCEL OrderEvents rather than enqueueing them
		itself, and the handler puts them on the queue.
		"""
		for order_event in self.order_manager.on_fill(fill_event):
			self.global_queue.put(order_event)
			self.logger.debug('Orphaned-child cancel event sent to execution handler: %s', order_event)

	def on_order_ack(self, ack_event: OrderAckEvent) -> None:
		"""Persist the venue ack onto the stored order mirror.

		The live exchange emits an ORDER-ACK once the venue returns its order id.
		Delegates to OrderManager to stamp + persist ``venue_order_id``; the
		handler performs no storage write of its own.
		"""
		self.order_manager.stamp_venue_order_id(
			ack_event.order_id, ack_event.venue_order_id, ack_event.portfolio_id)

	def modify_order(self, order_id: OrderId, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[PortfolioId] = None, reason: str = "user modification") -> bool:
		"""
		Modify an active order through OrderManager and generate OrderEvent.

		Parameters
		----------
		order_id : OrderId
			The ID of the order to modify
		new_price : Decimal, optional
			New price for the order
		new_quantity : Decimal, optional
			New quantity for the order
		portfolio_id : PortfolioId, optional
			Portfolio ID for faster lookup
		reason : str, optional
			Reason for the modification

		Returns
		-------
		bool
			True if order was successfully modified, False otherwise
		"""
		result = self.order_manager.modify_order(order_id, new_price, new_quantity, portfolio_id, reason)
		
		if result.success and result.order_events:
			for order_event in result.order_events:
				self.global_queue.put(order_event)
				self.logger.debug('Order modification event sent to execution handler: %s', order_event)
		
		return result.success
	
	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None, reason: str = "user cancellation") -> bool:
		"""
		Cancel an active order through OrderManager and generate OrderEvent.

		Parameters
		----------
		order_id : OrderId
			The ID of the order to cancel
		portfolio_id : PortfolioId, optional
			Portfolio ID for faster lookup
		reason : str, optional
			Reason for cancellation

		Returns
		-------
		bool
			True if order was successfully cancelled, False otherwise
		"""
		result = self.order_manager.cancel_order(order_id, portfolio_id, reason)
		
		if result.success and result.order_events:
			for order_event in result.order_events:
				self.global_queue.put(order_event)
				self.logger.debug('Order cancellation event sent to execution handler: %s', order_event)

		return result.success

	def expire_all_resting(self) -> None:
		"""Sweep every active order to EXPIRED at run end.

		Delegates the time-in-force sweep to OrderManager and enqueues each
		returned OrderEvent(EXPIRE); the exchange clears the matching resting
		order through ``on_order``'s EXPIRE arm.
		"""
		for result in self.order_manager.expire_all_resting():
			if result.success and result.order_events:
				for order_event in result.order_events:
					self.global_queue.put(order_event)
					self.logger.debug('Order expiry event sent to execution handler: %s', order_event)

	def get_order_by_id(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None) -> Optional[Order]:
		"""
		Get an order by its ID.

		Parameters
		----------
		order_id : OrderId
			The order ID
		portfolio_id : PortfolioId, optional
			Portfolio ID for faster lookup

		Returns
		-------
		Order
			The order object if found, None otherwise
		"""
		return self.order_manager.get_order_by_id(order_id, portfolio_id)
	
	def get_orders_by_status(self, status: OrderStatus, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Get orders by their status.

		Parameters
		----------
		status : OrderStatus
			The status to filter by
		portfolio_id : PortfolioId, optional
			Portfolio ID to filter by
		"""
		return self.order_manager.get_orders_by_status(status, portfolio_id)
	
	def get_active_orders(self, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Get all active orders (PENDING and PARTIALLY_FILLED).

		Parameters
		----------
		portfolio_id : PortfolioId, optional
			Portfolio ID to filter by
		"""
		return self.order_manager.get_active_orders(portfolio_id)
	
	def get_order_history(self, order_id: OrderId) -> List[Dict[str, Any]]:
		"""
		Get the state change history for an order.

		Parameters
		----------
		order_id : OrderId
			The order ID
		"""
		return self.order_manager.get_order_history(order_id)
	
	def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Get all orders for a specific ticker.

		Parameters
		----------
		ticker : str
			The ticker symbol
		portfolio_id : PortfolioId, optional
			Portfolio ID to filter by
		"""
		return self.order_manager.get_orders_by_ticker(ticker, portfolio_id)
	
	def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Search orders based on criteria.

		Parameters
		----------
		criteria : Dict
			Search criteria (e.g., {'ticker': 'AAPL', 'action': 'BUY'})
		portfolio_id : PortfolioId, optional
			Portfolio ID to filter by
		"""
		return self.order_manager.search_orders(criteria, portfolio_id)
	
	def count_orders_by_status(self, portfolio_id: Optional[PortfolioId] = None) -> Dict[str, int]:
		"""
		Count orders by status (status name -> count).

		Parameters
		----------
		portfolio_id : PortfolioId, optional
			Portfolio ID to filter by
		"""
		return self.order_manager.count_orders_by_status(portfolio_id)
