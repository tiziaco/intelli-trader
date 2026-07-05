from decimal import Decimal
from queue import Queue
from typing import Any, Callable, List, Dict, Optional

from itrader.core.commission_estimator import CommissionEstimator
from itrader.core.portfolio_read_model import PortfolioReadModel
from itrader.config import OrderConfig
from .base import OrderStorage
from .order import Order
from ..core.enums import OrderStatus, MarketExecution
from ..core.ids import OrderId, PortfolioId
from .order_validator import EnhancedOrderValidator
from .order_manager import OrderManager
from ..events_handler.events import SignalEvent, OrderEvent, OrderAckEvent, FillEvent, PortfolioUpdateEvent
from .storage import OrderStorageFactory
from ..universe import Universe

from itrader.logger import get_itrader_logger


class OrderHandler:
	"""
	The OrderHandler serves as the interface layer for order management operations.
	
	**NEW ARCHITECTURE (Post-Refactor):**
	- Acts as the interface between the event system and OrderManager
	- Receives events (SignalEvent, FillEvent) and delegates business logic to OrderManager
	- Ensures all order operations generate proper OrderEvents for the execution handler
	- Provides API endpoints for external order management operations
	
	**Key Responsibilities:**
	- Event processing interface (on_signal, on_fill)
	- API interface for order operations (modify_order, cancel_order)
	- OrderEvent generation and queue management
	- Minimal business logic - delegates to OrderManager
	
	**OrderManager handles all business logic:**
	- Signal processing with smart order creation/modification
	- Order lifecycle management
	- Position-aware operations (when portfolio_handler is available)
	- Validation and state management
	"""
	def __init__(self, global_queue: "Queue[Any]", portfolio_handler: PortfolioReadModel,
	             order_storage: Optional[OrderStorage] = None,
	             market_execution: "str | MarketExecution | None" = None,
	             commission_estimator: Optional[CommissionEstimator] = None,
	             order_config: Optional[OrderConfig] = None,
	             enable_margin: bool = False,
	             portfolio_max_leverage: Decimal = Decimal("1")) -> None:
		"""
		Parameters
		----------
		global_queue: `Queue object`
			The events queue of the trading system
		portfolio_handler: `PortfolioReadModel`
			The narrow portfolio read boundary (D-16: the concrete
			PortfolioHandler satisfies this Protocol structurally)
		order_storage: `OrderStorage`, optional
			The order storage for storage operations. If None, uses InMemoryOrderStorage.
		order_config: `OrderConfig`, optional
			Order-domain config (D-05) carrying ``market_execution``, forwarded
			to OrderManager. None -> ``OrderConfig.default()`` ("immediate").
		market_execution: str | MarketExecution, optional
			DEPRECATED backward-compat override (D-05): forwarded to OrderManager,
			which folds it into an ``OrderConfig`` (str->enum coercion lives in
			OrderConfig validation now). Options:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Queue market orders for next bar execution (realistic backtesting)
		commission_estimator: CommissionEstimator, optional
			(quantity, price) -> estimated commission Decimal, forwarded to
			OrderManager's admission reservation gate (Plan 05-06, D-04/D-15).
			None -> zero estimate (golden run pins fees 0).
		"""
		self.global_queue = global_queue
		self.portfolio_handler = portfolio_handler

		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="OrderHandler")

		# D-18: manager owns storage — the handler forwards the injected storage
		# to OrderManager and retains NO reference to it. Every read path
		# delegates through the manager (facade -> manager -> storage).
		self.order_manager = OrderManager(
			order_storage or OrderStorageFactory.create_in_memory(),
			self.logger,
			market_execution,
			portfolio_handler,  # Pass portfolio_handler for position-aware logic
			commission_estimator=commission_estimator,
			order_config=order_config,
			enable_margin=enable_margin,
			portfolio_max_leverage=portfolio_max_leverage,
		)
		# Mirror the resolved execution mode the manager settled on (D-05).
		self.market_execution = self.order_manager.market_execution

		self.order_validator = EnhancedOrderValidator(portfolio_handler)

		self.logger.info('Order Handler initialized', market_execution=self.market_execution)

	def set_universe(self, universe: Universe) -> None:
		"""Inject the symbol→Instrument read-model into the order domain (Plan 02-03).

		Thin facade: forwards to ``OrderManager.set_universe`` → ``AdmissionManager``
		(the order/risk leverage cap reads ``Instrument.max_leverage`` through it,
		D-04). Called at the Trap-4 wiring point in both runners immediately after
		``simulated_exchange.set_universe(universe)`` — the runner builds the
		``Universe`` AFTER the order handler is constructed (Pitfall 1).
		"""
		self.order_manager.set_universe(universe)

	def update_config(self, updates: Dict[str, Any]) -> None:
		"""Update order-domain configuration at runtime (D-05/D-07/D-09).

		Thin facade: delegates to ``OrderManager.update_config`` (the business
		logic owner) per the CLAUDE.md handler/manager split — no business logic
		in the handler. Returns ``None``; raises ``ConfigurationError`` on
		failure. The handler's cached ``market_execution`` mirror is re-synced
		from the manager after the swap.
		"""
		self.order_manager.update_config(updates)
		self.market_execution = self.order_manager.market_execution

	def on_signal(self, signal_event: SignalEvent) -> None:
		"""
		Process signal event through OrderManager and generate OrderEvents.
		
		This is the interface method that delegates all business logic to OrderManager
		and ensures proper OrderEvent generation for the execution handler.
		
		Parameters
		----------
		signal_event : `SignalEvent`
			The signal event generated from the strategy module
		"""
		self.logger.debug('Processing signal %s => %s, %s $ (qty: %s)', 
						signal_event.ticker, signal_event.action, 
						round(signal_event.price, 4), signal_event.quantity)

		# Delegate signal processing to OrderManager
		operation_results = self.order_manager.process_signal(signal_event)
		
		# Generate OrderEvents for ALL operations (create, modify, cancel)
		for result in operation_results:
			if result.order_events:
				for order_event in result.order_events:
					self.global_queue.put(order_event)
					self.logger.debug('OrderEvent sent to execution handler: %s', order_event)

	
	def on_fill(self, fill_event: FillEvent) -> None:
		"""Reconcile the order mirror from an exchange fill event.

		WR-05: reconciliation may cancel bracket children orphaned by a parent
		that reached a terminal state without any fill — the manager returns
		their CANCEL OrderEvents (D-18: the manager never touches the queue)
		and the handler enqueues them for the execution handler.
		"""
		for order_event in self.order_manager.on_fill(fill_event):
			self.global_queue.put(order_event)
			self.logger.debug('Orphaned-child cancel event sent to execution handler: %s', order_event)

	def on_order_ack(self, ack_event: OrderAckEvent) -> None:
		"""Persist the venue ack (D-06 / V17-02) onto the stored order mirror.

		The live exchange emits an ORDER-ACK once the venue returns its order id
		(queue-only cross-domain write, D-19). Delegate to OrderManager to stamp +
		persist ``venue_order_id`` — the handler holds NO store ref (D-18).
		"""
		self.order_manager.stamp_venue_order_id(
			ack_event.order_id, ack_event.venue_order_id, ack_event.portfolio_id)

	def modify_order(self, order_id: OrderId, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[PortfolioId] = None, reason: str = "user modification") -> bool:
		"""
		Modify an active order through OrderManager and generate OrderEvent.
		
		This is an API interface method that delegates to OrderManager
		and ensures proper OrderEvent generation.

		Parameters
		----------
		order_id : int
			The ID of the order to modify
		new_price : Decimal, optional
			New price for the order
		new_quantity : Decimal, optional
			New quantity for the order
		portfolio_id : int, optional
			Portfolio ID for faster lookup
		reason : str, optional
			Reason for the modification

		Returns
		-------
		bool
			True if order was successfully modified, False otherwise
		"""
		# Delegate to OrderManager
		result = self.order_manager.modify_order(order_id, new_price, new_quantity, portfolio_id, reason)
		
		# Generate OrderEvent if modification was successful
		if result.success and result.order_events:
			for order_event in result.order_events:
				self.global_queue.put(order_event)
				self.logger.debug('Order modification event sent to execution handler: %s', order_event)
		
		return result.success
	
	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None, reason: str = "user cancellation") -> bool:
		"""
		Cancel an active order through OrderManager and generate OrderEvent.
		
		This is an API interface method that delegates to OrderManager
		and ensures proper OrderEvent generation.

		Parameters
		----------
		order_id : int
			The ID of the order to cancel
		portfolio_id : int, optional
			Portfolio ID for faster lookup
		reason : str, optional
			Reason for cancellation

		Returns
		-------
		bool
			True if order was successfully cancelled, False otherwise
		"""
		# Delegate to OrderManager
		result = self.order_manager.cancel_order(order_id, portfolio_id, reason)
		
		# Generate OrderEvent if cancellation was successful
		if result.success and result.order_events:
			for order_event in result.order_events:
				self.global_queue.put(order_event)
				self.logger.debug('Order cancellation event sent to execution handler: %s', order_event)

		return result.success

	def expire_all_resting(self) -> None:
		"""Sweep every active order to EXPIRED at run end (LIFE-01, D-08).

		Thin facade: delegates the time-in-force sweep to OrderManager (the
		business logic owner) and enqueues each returned OrderEvent(EXPIRE) for
		the execution handler — mirrors the cancel_order enqueue idiom (D-18: the
		manager never touches the queue). The exchange clears each resting order
		through ``on_order``'s EXPIRE arm.
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
		order_id : int
			The order ID
		portfolio_id : int, optional
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
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		List[Order]
			List of orders with the specified status
		"""
		return self.order_manager.get_orders_by_status(status, portfolio_id)
	
	def get_active_orders(self, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Get all active orders (PENDING and PARTIALLY_FILLED).

		Parameters
		----------
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		List[Order]
			List of active orders
		"""
		return self.order_manager.get_active_orders(portfolio_id)
	
	def get_order_history(self, order_id: OrderId) -> List[Dict[str, Any]]:
		"""
		Get the state change history for an order.

		Parameters
		----------
		order_id : int
			The order ID

		Returns
		-------
		List[Dict]
			List of state changes for the order
		"""
		return self.order_manager.get_order_history(order_id)
	
	def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Get all orders for a specific ticker.

		Parameters
		----------
		ticker : str
			The ticker symbol
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		List[Order]
			List of orders for the ticker
		"""
		return self.order_manager.get_orders_by_ticker(ticker, portfolio_id)
	
	def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""
		Search orders based on criteria.

		Parameters
		----------
		criteria : Dict
			Search criteria (e.g., {'ticker': 'AAPL', 'action': 'BUY'})
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		List[Order]
			List of orders matching the criteria
		"""
		return self.order_manager.search_orders(criteria, portfolio_id)
	
	def count_orders_by_status(self, portfolio_id: Optional[PortfolioId] = None) -> Dict[str, int]:
		"""
		Count orders by status (status name -> count).

		Parameters
		----------
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		Dict[str, int]
			Dictionary with status names as keys and counts as values
		"""
		return self.order_manager.count_orders_by_status(portfolio_id)
