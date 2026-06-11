from decimal import Decimal
from queue import Queue
from typing import Any, Callable, List, Dict, Optional

from itrader.core.portfolio_read_model import PortfolioReadModel
from .base import OrderStorage
from .order import Order
from ..core.enums import OrderStatus
from .order_validator import EnhancedOrderValidator
from .order_manager import OrderManager
from ..events_handler.events import SignalEvent, OrderEvent, FillEvent, PortfolioUpdateEvent
from .storage import OrderStorageFactory

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
	- API interface for order operations (create_order, modify_order, cancel_order)
	- OrderEvent generation and queue management
	- Minimal business logic - delegates to OrderManager
	
	**OrderManager handles all business logic:**
	- Signal processing with smart order creation/modification
	- Order lifecycle management
	- Position-aware operations (when portfolio_handler is available)
	- Validation and state management
	"""
	def __init__(self, events_queue: "Queue[Any]", portfolio_handler: PortfolioReadModel,
	             order_storage: Optional[OrderStorage] = None, market_execution: str = "immediate",
	             commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]] = None) -> None:
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		portfolio_handler: `PortfolioReadModel`
			The narrow portfolio read boundary (D-16: the concrete
			PortfolioHandler satisfies this Protocol structurally)
		order_storage: `OrderStorage`, optional
			The order storage for storage operations. If None, uses InMemoryOrderStorage.
		market_execution: str, optional
			Market order execution timing. Options:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Queue market orders for next bar execution (realistic backtesting)
		commission_estimator: Callable[[Decimal, Decimal], Decimal], optional
			(quantity, price) -> estimated commission Decimal, forwarded to
			OrderManager's admission reservation gate (Plan 05-06, D-04).
			None -> zero estimate (golden run pins fees 0).
		"""
		self.events_queue = events_queue
		self.portfolio_handler = portfolio_handler
		self.market_execution = market_execution

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
			commission_estimator=commission_estimator
		)
		self.order_validator = EnhancedOrderValidator(portfolio_handler)
		
		self.logger.info(f'Order Handler initialized with market_execution={market_execution})')

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
					self.events_queue.put(order_event)
					self.logger.debug('OrderEvent sent to execution handler: %s', order_event)

	
	def on_fill(self, fill_event: FillEvent) -> None:
		"""Reconcile the order mirror from an exchange fill event.

		WR-05: reconciliation may cancel bracket children orphaned by a parent
		that reached a terminal state without any fill — the manager returns
		their CANCEL OrderEvents (D-18: the manager never touches the queue)
		and the handler enqueues them for the execution handler.
		"""
		for order_event in self.order_manager.on_fill(fill_event):
			self.events_queue.put(order_event)
			self.logger.debug('Orphaned-child cancel event sent to execution handler: %s', order_event)

	def modify_order(self, order_id: int, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[Any] = None, reason: str = "user modification") -> bool:
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
				self.events_queue.put(order_event)
				self.logger.debug('Order modification event sent to execution handler: %s', order_event)
		
		return result.success
	
	def cancel_order(self, order_id: int, portfolio_id: Optional[Any] = None, reason: str = "user cancellation") -> bool:
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
				self.events_queue.put(order_event)
				self.logger.debug('Order cancellation event sent to execution handler: %s', order_event)
		
		return result.success
	
	def create_order(self, signal_event: SignalEvent) -> bool:
		"""
		Create orders from signal through OrderManager and generate OrderEvents.
		
		This is an API interface method for programmatic order creation
		that delegates to OrderManager and ensures proper OrderEvent generation.

		Parameters
		----------
		signal_event : SignalEvent
			The signal event containing order details

		Returns
		-------
		bool
			True if orders were successfully created, False otherwise
		"""
		# Delegate to OrderManager
		operation_results = self.order_manager.create_orders_from_signal(signal_event)
		
		# Generate OrderEvents for all created orders
		success = False
		for result in operation_results:
			if result.success:
				success = True
			if result.order_events:
				for order_event in result.order_events:
					self.events_queue.put(order_event)
					self.logger.debug('Order creation event sent to execution handler: %s', order_event)
		
		return success
	
	def get_order_by_id(self, order_id: int, portfolio_id: Optional[Any] = None) -> Optional[Order]:
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
	
	def get_orders_by_status(self, status: OrderStatus, portfolio_id: Optional[Any] = None) -> List[Order]:
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
	
	def get_active_orders(self, portfolio_id: Optional[Any] = None) -> List[Order]:
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
	
	def get_order_history(self, order_id: int) -> List[Dict[str, Any]]:
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
	
	def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[Any] = None) -> List[Order]:
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
	
	def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[Any] = None) -> List[Order]:
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
	
	def get_orders_summary(self, portfolio_id: Optional[Any] = None) -> Dict[str, int]:
		"""
		Get a summary of orders by status.

		Parameters
		----------
		portfolio_id : int, optional
			Portfolio ID to filter by

		Returns
		-------
		Dict[str, int]
			Dictionary with status names as keys and counts as values
		"""
		return self.order_manager.get_orders_summary(portfolio_id)
