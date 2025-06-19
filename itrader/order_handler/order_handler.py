from queue import Queue
from typing import List, Dict

from ..portfolio_handler.portfolio_handler import PortfolioHandler
from .base import OrderBase, OrderStorage
from .order import Order, OrderStatus
from .order_validator import EnhancedOrderValidator
from .order_manager import OrderManager
from ..events_handler.event import SignalEvent, BarEvent, OrderEvent, PortfolioUpdateEvent
from .storage import OrderStorageFactory

from itrader.logger import get_itrader_logger


class OrderHandler(OrderBase):
	"""
	The OrderHandler class manage the signal event coming from the 
	strategy class.

	It transforms the Signal event in a Suggested order, then send it
	to te Risk Manager (cash check, calculate sl and tp) and finally
	calculate the position size with the Position Sizer

	It is able to manage stop and limit order and it has a pending 
	order queue for active and inactive orders.

	When an order is filled it is sended to the execution handler
	
	Enhanced with comprehensive order lifecycle management, state tracking,
	and validation capabilities.
	"""
	def __init__(self, events_queue: Queue, portfolio_handler: PortfolioHandler, 
	             order_storage: OrderStorage = None, market_execution: str = "immediate"):
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		portfolio_handler: `PortfolioHandler`
			The portfolio handler instance
		order_storage: `OrderStorage`, optional
			The order storage for storage operations. If None, uses InMemoryOrderStorage.
		market_execution: str, optional
			Market order execution timing. Options:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Queue market orders for next bar execution (realistic backtesting)
		"""
		self.events_queue = events_queue
		self.portfolio_handler = portfolio_handler
		self.market_execution = market_execution
		
		# Initialize logger first
		self.logger = get_itrader_logger().bind(component="OrderHandler")
		
		self.order_storage = order_storage or OrderStorageFactory.create_in_memory()
		self.order_manager = OrderManager(self.order_storage, self.logger, self, market_execution)
		self.order_validator = EnhancedOrderValidator(portfolio_handler)
		
		self.logger.info(f'Order Handler initialized with market_execution={market_execution})')

	def process_orders_on_market_data(self, bar_event: BarEvent):
		"""
		Process all order types when new market data arrives.
		
		This is the centralized entry point for all market-driven order processing.
		
		Parameters
		----------
		bar_event : BarEvent
			The bar event containing current market data
		"""
		order_events = self.order_manager.process_orders_on_market_data(bar_event)
		
		# Send all generated order events to the execution handler
		for order_event in order_events:
			self.events_queue.put(order_event)
		
		self.logger.debug(f'Processed market data for {len(order_events)} orders')
	
	def on_signal(self, signal_event: SignalEvent):
		"""
		Simplified signal processing with unified validation pipeline.
		
		NOTE: Signal now comes pre-sized from strategy (when strategy refactoring is complete).
		
		Parameters
		----------
		signal_event : `SignalEvent`
			The signal event generated from the strategy module
		"""
		self.logger.debug('Processing signal %s => %s, %s $ (qty: %s)', 
						signal_event.ticker, signal_event.action, 
						round(signal_event.price, 4), signal_event.quantity)

		# Single unified validation pipeline
		validation_result = self.order_validator.validate_signal_pipeline(signal_event)
		
		if not validation_result.success:
			self.logger.error('Signal validation failed: %s - %s', 
							validation_result.summary,
							[msg.message for msg in validation_result.errors])
			return
		
		# Log warnings if any
		if validation_result.has_warnings:
			self.logger.warning('Signal validation warnings: %s',
							   [msg.message for msg in validation_result.warnings])

		# Signal is valid - create orders
		if signal_event.stop_loss > 0:
			self.add_stop_loss_order(signal_event)
		if signal_event.take_profit > 0:
			self.add_take_profit_order(signal_event)
		
		# Generate market order
		self.new_order(signal_event)
		
		# Handle market order execution based on configured mode
		if self.market_execution == "immediate":
			# Execute market orders immediately
			order_events = self.order_manager.process_market_orders_immediately()
			for order_event in order_events:
				self.events_queue.put(order_event)
		elif self.market_execution == "next_bar":
			# Queue market orders for next bar execution
			self.order_manager.queue_market_orders_for_next_bar()

	
	def add_pending_order(self, order: Order):
		"""
		Add new stop or limit order after the suggested order has been 
		refined by the risk manager.

		Parameters
		----------
		order: `Order object`
			The stop/limit order object for a specific ticker
		"""
		self.order_storage.add_order(order)
	
	def remove_orders(self, ticker, portfolio_id):
		"""
		Remove all the pending orders with the same ticker of the
		order who has been filled

		Parameters
		----------
		ticker: `str`
			The ticker of the order to be removed
		portfolio_id: `str`
			The portfolio ID
		"""
		count = self.order_storage.remove_orders_by_ticker(ticker, portfolio_id)
		if count > 0:
			self.logger.debug('Removed %d pending orders for ticker %s in portfolio %s',
							count, ticker, portfolio_id)

	def remove_order(self, order_id: str, portfolio_id: str = None) -> bool:
		"""
		Remove an order by its ID from pending orders.
		
		Parameters
		----------
		order_id : str
			The ID of the order to remove
		portfolio_id : str, optional
			The portfolio ID for direct access (more efficient)
			
		Returns
		-------
		bool
			True if order was found and removed, False otherwise
		"""
		removed = self.order_storage.remove_order(order_id, portfolio_id)
		if removed:
			self.logger.debug('Order %s removed', order_id)
		else:
			self.logger.warning('Order %s not found for removal', order_id)
		return removed

	
	def modify_order(self, order_id: int, new_price: float = None, new_quantity: float = None, 
	                portfolio_id: int = None, reason: str = "user modification") -> bool:
		"""
		Modify the filling price and/or quantity of an active order.
		Useful for trailing stops and order adjustments.

		Parameters
		----------
		order_id : int
			The ID of the order to modify
		new_price : float, optional
			New price for the order
		new_quantity : float, optional
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
		# Get the order
		order = self.order_storage.get_order_by_id(order_id, portfolio_id)
		if not order:
			self.logger.warning('Order %s not found for modification', order_id)
			return False
		
		# Validate the modification
		validation_messages = self.order_validator.validate_order_modification(
			order, new_price, new_quantity
		)
		
		if not self.order_validator.is_valid(validation_messages):
			error_messages = self.order_validator.get_errors(validation_messages)
			self.logger.error('Order modification validation failed: %s',
							[msg.message for msg in error_messages])
			return False
		
		# Apply the modification
		success = order.modify_order(new_price, new_quantity, reason)
		if success:
			# Update in storage
			self.order_storage.update_order(order)
			self.logger.info('Order %s modified successfully', order_id)
		else:
			self.logger.warning('Failed to modify order %s', order_id)
		
		return success
	
	def cancel_order(self, order_id: int, portfolio_id: int = None, reason: str = "user cancellation") -> bool:
		"""
		Cancel an active order.

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
		# Get the order
		order = self.order_storage.get_order_by_id(order_id, portfolio_id)
		if not order:
			self.logger.warning('Order %s not found for cancellation', order_id)
			return False
		
		# Cancel the order
		success = order.cancel_order(reason)
		if success:
			# Update in storage
			self.order_storage.update_order(order)
			self.logger.info('Order %s cancelled: %s', order_id, reason)
		else:
			self.logger.warning('Failed to cancel order %s (status: %s)', 
							   order_id, order.status.name)
		
		return success
	
	def get_order_by_id(self, order_id: int, portfolio_id: int = None) -> Order:
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
		return self.order_storage.get_order_by_id(order_id, portfolio_id)
	
	def get_orders_by_status(self, status: OrderStatus, portfolio_id: int = None) -> List[Order]:
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
		return self.order_storage.get_orders_by_status(status, portfolio_id)
	
	def get_active_orders(self, portfolio_id: int = None) -> List[Order]:
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
		return self.order_storage.get_active_orders(portfolio_id)
	
	def get_order_history(self, order_id: int) -> List[Dict]:
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
		return self.order_storage.get_order_history(order_id)
	
	def get_orders_by_ticker(self, ticker: str, portfolio_id: int = None) -> List[Order]:
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
		return self.order_storage.get_orders_by_ticker(ticker, portfolio_id)
	
	def search_orders(self, criteria: Dict, portfolio_id: int = None) -> List[Order]:
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
		return self.order_storage.search_orders(criteria, portfolio_id)
	
	def get_orders_summary(self, portfolio_id: int = None) -> Dict[str, int]:
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
		return self.order_storage.get_orders_count_by_status(portfolio_id)
	
		return archived_count

	def add_stop_loss_order(self, signal: SignalEvent):
		"""
		Add a stop order in the pending order queue

		Parameters
		----------
		sized_order: `Order object`
			The sized order generated from the position sizer module
		"""
		portfolio_id = signal.portfolio_id
		exchange = self.portfolio_handler.get_portfolio(portfolio_id).exchange
		sl_order = Order.new_stop_order(
			time = signal.time,
			ticker = signal.ticker,
			action = 'BUY' if signal.action == 'SELL' else 'SELL',
			price = signal.stop_loss,
			quantity = signal.quantity,
			exchange = exchange,
			strategy_id = signal.strategy_id,
			portfolio_id = signal.portfolio_id
			)
		self.add_pending_order(sl_order)
		self.logger.debug('Stop loss order added: %s, %s $', 
					sl_order.ticker, sl_order.price)

	def add_take_profit_order(self, signal: SignalEvent):
		"""
		Add a limit order in the pending order queue

		Parameters
		----------
		sized_order: `Order object`
			The sized order generated from the position sizer module
		"""
		portfolio_id = signal.portfolio_id
		exchange = self.portfolio_handler.get_portfolio(portfolio_id).exchange
		tp_order = Order.new_limit_order(
			time = signal.time,
			ticker = signal.ticker,
			action = 'BUY' if signal.action == 'SELL' else 'SELL',
			price = signal.take_profit,
			quantity = signal.quantity,
			exchange = exchange,
			strategy_id = signal.strategy_id,
			portfolio_id = signal.portfolio_id
			)
		self.add_pending_order(tp_order)
		self.logger.debug('Take profit order added: %s, %s $', 
					tp_order.ticker, tp_order.price)
	
	def new_order(self, signal: SignalEvent):
		portfolio_id = signal.portfolio_id
		exchange = self.portfolio_handler.get_portfolio(portfolio_id).exchange
		new_order = Order.new_order(signal, exchange)
		self.add_pending_order(new_order)

	def send_order_event(self, order: Order):
		"""
		When a stop/limit order is filled or when a market order is set,
		create an order event to be added to the global events que. 
		This event will be then processed by the execution handler.
		"""
		order_event = OrderEvent.new_order_event(order)
		self.events_queue.put(order_event)
		self.logger.debug('Order sent to the execution handler')
