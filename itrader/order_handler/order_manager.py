"""
Order Manager - Internal order orchestration engine for OrderHandler.

Centralizes all market-driven order processing including:
- Stop/Limit order trigger evaluation
- Market order execution with configurable timing
- Order fill processing
- State management and event generation

This eliminates scattered order processing logic and provides
a single, coordinated pipeline for all order operations.
"""

from typing import List, Dict, Optional
from .order import Order, OrderType, OrderStatus
from .base import OrderStorage
from ..events_handler.event import BarEvent, OrderEvent


class OrderManager:
	"""
	Internal order orchestration engine for OrderHandler.
	
	Centralizes all market-driven order processing including:
	- Stop/Limit order trigger evaluation
	- Market order execution with configurable timing
	- Order fill processing
	- State management and event generation
	
	This eliminates scattered order processing logic and provides
	a single, coordinated pipeline for all order operations.
	"""
	
	def __init__(self, order_storage: OrderStorage, logger, order_handler_ref, market_execution: str = "immediate"):
		"""
		Initialize the OrderManager.
		
		Parameters
		----------
		order_storage : OrderStorage
			Storage interface for order operations
		logger : Logger
			Logger instance for order processing events
		order_handler_ref : OrderHandler
			Reference to parent OrderHandler for callbacks
		market_execution : str
			Market order execution mode:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Execute market orders on next bar (realistic backtesting)
		"""
		self.order_storage = order_storage
		self.logger = logger
		self.order_handler = order_handler_ref
		self.market_execution = market_execution
		self.processed_fills = []
		self.pending_events = []
		self.queued_market_orders = []  # For next_bar execution
	
	def process_orders_on_market_data(self, bar_event: BarEvent) -> List[OrderEvent]:
		"""
		Single orchestrated pipeline for all market-driven order processing.
		
		Processes all order types that depend on market data:
		- STOP orders (stop-loss/stop-buy)
		- LIMIT orders (take-profit/limit-buy)
		- Queued MARKET orders (if market_execution="next_bar")
		
		Parameters
		----------
		bar_event : BarEvent
			The market data event containing current prices
			
		Returns
		-------
		List[OrderEvent]
			List of order events to be sent to execution handler
		"""
		try:
			self.processed_fills = []
			self.pending_events = []
			
			# 1. Process any queued market orders (for next_bar execution mode)
			queued_market_orders = self._process_queued_market_orders(bar_event)
			
			# 2. Check and trigger pending stop/limit orders
			triggered_orders = self._check_and_trigger_conditional_orders(bar_event)
			
			# 3. Process all fills and update storage
			all_filled_orders = queued_market_orders + triggered_orders
			self._process_order_fills(all_filled_orders)
			
			# 4. Generate order events for execution
			events = self._generate_order_events(all_filled_orders)
			
			# 5. Clean up filled orders from active storage
			self._cleanup_filled_orders(all_filled_orders)
			
			self.logger.debug(f'Processed {len(all_filled_orders)} orders, generated {len(events)} events')
			return events
			
		except Exception as e:
			self.logger.error(f'Error in order processing pipeline: {e}', exc_info=True)
			return []
	
	def process_market_orders_immediately(self) -> List[OrderEvent]:
		"""
		Process market orders immediately (for market_execution="immediate").
		
		This is called right after market orders are created from signals.
		Only processes MARKET orders - STOP/LIMIT orders still wait for triggers.
		
		Returns
		-------
		List[OrderEvent]
			List of order events to be sent to execution handler
		"""
		if self.market_execution != "immediate":
			return []
		
		try:
			# Process market orders immediately
			market_orders = self._process_market_orders()
			
			# Process fills and generate events
			self._process_order_fills(market_orders)
			events = self._generate_order_events(market_orders)
			self._cleanup_filled_orders(market_orders)
			
			self.logger.debug(f'Processed {len(market_orders)} immediate market orders')
			return events
			
		except Exception as e:
			self.logger.error(f'Error processing immediate market orders: {e}', exc_info=True)
			return []
	
	def queue_market_orders_for_next_bar(self):
		"""
		Queue market orders for execution on next bar (for market_execution="next_bar").
		
		This is called after market orders are created from signals.
		The orders will be executed when the next bar arrives.
		"""
		if self.market_execution != "next_bar":
			return
		
		# Find all pending market orders and queue them
		active_orders = self.order_storage.get_active_orders_dict()
		
		for portfolio_id, portfolio_orders in active_orders.items():
			for order_id, order in portfolio_orders.items():
				if order.type == OrderType.MARKET and order not in self.queued_market_orders:
					self.queued_market_orders.append(order)
					self.logger.debug(f'Queued market order for next bar: {order.ticker} {order.action}')
	
	def _process_queued_market_orders(self, bar_event: BarEvent) -> List[Order]:
		"""
		Process market orders that were queued for next bar execution.
		
		Parameters
		----------
		bar_event : BarEvent
			The current bar event with prices for execution
			
		Returns
		-------
		List[Order]
			List of market orders that were executed
		"""
		if not self.queued_market_orders:
			return []
		
		executed_orders = []
		
		for order in self.queued_market_orders[:]:  # Copy list to avoid modification during iteration
			try:
				# Get the opening price for next-bar execution
				open_price = bar_event.get_last_open(order.ticker)
				if open_price is None:
					self.logger.warning(f'No open price available for {order.ticker}, using order price')
					open_price = order.price
				
				# Execute at opening price
				order.add_fill(
					order.remaining_quantity,
					open_price,
					bar_event.time,
					"market order next bar execution"
				)
				
				executed_orders.append(order)
				self.logger.info(f'Market order executed at next bar open: {order.ticker} {order.action} at {open_price}')
				
			except Exception as e:
				self.logger.error(f'Error executing queued market order {order.id}: {e}')
		
		# Clear the queue
		self.queued_market_orders.clear()
		return executed_orders
	
	def _check_and_trigger_conditional_orders(self, bar_event: BarEvent) -> List[Order]:
		"""
		Check stop and limit orders for trigger conditions.
		
		Returns list of orders that should be filled.
		"""
		triggered_orders = []
		active_orders = self.order_storage.get_active_orders_dict()
		
		if not active_orders:
			return triggered_orders
		
		for portfolio_id, portfolio_orders in list(active_orders.items()):
			for order_id, order in list(portfolio_orders.items()):
				# Skip market orders - they're handled separately
				if order.type == OrderType.MARKET:
					continue
				
				last_close = bar_event.get_last_close(order.ticker)
				if last_close is None:
					continue
				
				# Check trigger conditions
				if self._should_trigger_order(order, last_close):
					# Update order timing
					order.time = bar_event.time
					
					# Add fill with current market price
					fill_reason = self._get_fill_reason(order)
					order.add_fill(
						order.remaining_quantity, 
						last_close, 
						bar_event.time, 
						fill_reason
					)
					
					triggered_orders.append(order)
					self.logger.info(f'{order.type.name} order filled: {order.ticker} {order.action} at {last_close}')
		
		return triggered_orders
	
	def _process_market_orders(self) -> List[Order]:
		"""
		Process all pending market orders for immediate execution.
		
		Returns list of market orders that were filled.
		"""
		market_orders = []
		active_orders = self.order_storage.get_active_orders_dict()
		
		if not active_orders:
			return market_orders
		
		for portfolio_id, portfolio_orders in list(active_orders.items()):
			for order_id, order in list(portfolio_orders.items()):
				if order.type == OrderType.MARKET:
					# Market orders are filled immediately at their specified price
					order.add_fill(
						order.remaining_quantity, 
						order.price, 
						order.time, 
						"market order execution"
					)
					market_orders.append(order)
					self.logger.info(f'Market order executed: {order.ticker} {order.action} at {order.price}')
		
		return market_orders
	
	def _should_trigger_order(self, order: Order, current_price: float) -> bool:
		"""
		Determine if an order should be triggered based on current market price.
		
		Parameters
		----------
		order : Order
			The order to evaluate
		current_price : float
			Current market price
			
		Returns
		-------
		bool
			True if order should be triggered
		"""
		if order.type == OrderType.STOP:
			if order.action == 'SELL':
				# Stop-loss for long position: trigger when price falls below stop
				return current_price < order.price
			elif order.action == 'BUY':
				# Stop-loss for short position: trigger when price rises above stop
				return current_price > order.price
				
		elif order.type == OrderType.LIMIT:
			if order.action == 'SELL':
				# Take-profit for long position: trigger when price rises above limit
				return current_price > order.price
			elif order.action == 'BUY':
				# Take-profit for short position: trigger when price falls below limit
				return current_price < order.price
		
		return False
	
	def _get_fill_reason(self, order: Order) -> str:
		"""Get appropriate fill reason based on order type."""
		if order.type == OrderType.STOP:
			return "stop loss triggered"
		elif order.type == OrderType.LIMIT:
			return "limit order triggered"
		else:
			return "order triggered"
	
	def _process_order_fills(self, filled_orders: List[Order]) -> None:
		"""
		Process fills for all orders and update storage.
		
		Parameters
		----------
		filled_orders : List[Order]
			Orders that have been filled
		"""
		for order in filled_orders:
			# Update order in storage
			self.order_storage.update_order(order)
			self.processed_fills.append(order)
	
	def _generate_order_events(self, filled_orders: List[Order]) -> List[OrderEvent]:
		"""
		Generate OrderEvents for all filled orders.
		
		Parameters
		----------
		filled_orders : List[Order]
			Orders that have been filled
			
		Returns
		-------
		List[OrderEvent]
			Order events ready for execution handler
		"""
		events = []
		for order in filled_orders:
			try:
				order_event = OrderEvent.new_order_event(order)
				events.append(order_event)
				self.pending_events.append(order_event)
			except Exception as e:
				self.logger.error(f'Failed to create order event for order {order.id}: {e}')
		
		return events
	
	def _cleanup_filled_orders(self, filled_orders: List[Order]) -> None:
		"""
		Process filled orders with proper professional trading lifecycle management.
		
		Professional behavior:
		- Market orders: Move from active to filled state, maintain in all_orders for audit trail
		- Stop/Limit orders: Implement OCO (One-Cancels-Other) behavior - when one triggers,
		  cancel all other SL/TP orders for the same position
		
		Parameters
		----------
		filled_orders : List[Order]
			Orders that have been completely filled
		"""
		for order in filled_orders:
			try:
				if order.type == OrderType.MARKET:
					# Market orders: Remove from active orders but keep in all_orders for audit trail
					self._deactivate_filled_order(order)
				
				elif order.type in [OrderType.STOP, OrderType.LIMIT]:
					# Stop/Limit orders: Implement full OCO behavior
					# When SL or TP triggers, cancel all other SL/TP orders for the same position
					self._handle_oco_order_fill(order)
				
			except Exception as e:
				self.logger.error(f'Failed to cleanup order {order.id}: {e}')
	
	def _deactivate_filled_order(self, order: Order) -> None:
		"""
		Deactivate a filled order using professional trading practices.
		
		This removes the order from active_orders but keeps it in all_orders
		for audit trail and historical tracking, mimicking SQL database behavior.
		
		Parameters
		----------
		order : Order
			The order that has been filled and should be deactivated
		"""
		try:
			# Remove from active orders only (SQL-like: WHERE status = 'ACTIVE')
			success = self.order_storage.deactivate_order(order.id, order.portfolio_id)
			if success:
				self.logger.debug(f'Deactivated filled {order.type.name} order {order.id} - kept in historical records')
			else:
				# Don't log warning for normal case where order might not be in active state
				self.logger.debug(f'{order.type.name} order {order.id} not in active state (normal for immediate execution)')
		except Exception as e:
			self.logger.error(f'Error deactivating order {order.id}: {e}')

	def _handle_oco_order_fill(self, filled_order: Order) -> None:
		"""
		Handle One-Cancels-Other behavior with professional trading practices.
		
		When a stop-loss or take-profit order is triggered:
		1. Deactivate the filled order (keep in all_orders for audit trail)
		2. Cancel and deactivate all other SL/TP orders for the same ticker/portfolio
		
		This simulates closing the position and properly managing remaining orders
		while maintaining complete audit trail.
		
		Parameters
		----------
		filled_order : Order
			The stop or limit order that was just filled
		"""
		try:
			# Get all active orders for this portfolio and ticker
			active_orders = self.order_storage.get_active_orders_dict()
			portfolio_orders = active_orders.get(str(filled_order.portfolio_id), {})
			
			orders_to_process = []
			
			# Find all stop/limit orders for the same ticker in the same portfolio
			for order_id, order in portfolio_orders.items():
				if (order.ticker == filled_order.ticker and 
				    order.type in [OrderType.STOP, OrderType.LIMIT]):
					orders_to_process.append(order)
			
			# Process all related orders (including the filled one)
			processed_count = 0
			for order in orders_to_process:
				if order.id == filled_order.id:
					# This is the filled order - deactivate it (keep in history)
					success = self.order_storage.deactivate_order(order.id, order.portfolio_id)
					if success:
						processed_count += 1
						self.logger.info(f'Deactivated filled {order.type.name} order: {order.ticker} at ${order.price}')
				else:
					# This is a related order - cancel it (OCO behavior) and deactivate
					success = order.cancel_order("OCO - related order filled")
					if success:
						self.order_storage.update_order(order)  # Update the cancelled state
						success = self.order_storage.deactivate_order(order.id, order.portfolio_id)
						if success:
							processed_count += 1
							self.logger.info(f'Cancelled & deactivated {order.type.name} order (OCO): {order.ticker} at ${order.price}')
			
			self.logger.info(f'OCO order fill: Processed {processed_count} orders for {filled_order.ticker} (maintained audit trail)')
			
		except Exception as e:
			self.logger.error(f'Error handling OCO order fill for order {filled_order.id}: {e}')
			# Fallback to simple deactivation
			self.order_storage.deactivate_order(filled_order.id, filled_order.portfolio_id)
