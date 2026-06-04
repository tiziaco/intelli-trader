"""
Order Manager - Enhanced order orchestration engine for OrderHandler.

Centralizes all order operations including:
- Signal processing with smart order creation/modification
- Stop/Limit order trigger evaluation
- Market order execution with configurable timing
- Order lifecycle management (create, modify, cancel)
- State management and OrderEvent generation

Provides the business logic layer between OrderHandler (interface)
and order storage/execution systems.
"""

from typing import List
from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderCommand
from .base import OrderStorage
from ..events_handler.event import OrderEvent, SignalEvent, FillEvent, FillStatus
from .order_validator import EnhancedOrderValidator


class OrderManager:
	"""
	Enhanced order orchestration engine for OrderHandler.
	
	Centralizes all order operations including:
	- Signal processing with smart order creation/modification
	- Stop/Limit order trigger evaluation  
	- Market order execution with configurable timing
	- Order lifecycle management (create, modify, cancel)
	- State management and OrderEvent generation
	
	Provides the business logic layer between OrderHandler (interface)
	and order storage/execution systems.
	"""
	
	def __init__(self, order_storage: OrderStorage, logger, order_handler_ref, 
	             market_execution: str = "immediate", portfolio_handler=None):
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
		portfolio_handler : PortfolioHandler, optional
			Portfolio handler for position-aware operations
		"""
		self.order_storage = order_storage
		self.logger = logger
		self.order_handler = order_handler_ref
		self.market_execution = market_execution
		self.portfolio_handler = portfolio_handler

		# Initialize validator if portfolio_handler is available
		self.order_validator = EnhancedOrderValidator(portfolio_handler) if portfolio_handler else None

	def on_fill(self, fill_event: FillEvent) -> None:
		"""
		Reconcile the order mirror against an exchange fill.

		EXECUTED -> mark the order FILLED; CANCELLED -> mark CANCELLED.
		Then deactivate it from the active book (kept in all_orders for audit).
		"""
		order_id = getattr(fill_event, 'order_id', None)
		if order_id is None:
			return
		order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
		if order is None:
			return
		try:
			if fill_event.status == FillStatus.EXECUTED:
				if not order.add_fill(order.remaining_quantity, fill_event.price,
				                      fill_event.time, "exchange fill"):
					self.logger.warning('add_fill rejected for order %s; mirror left unchanged', order_id)
					return
			elif fill_event.status == FillStatus.CANCELLED:
				order.cancel_order("exchange cancellation")
			elif fill_event.status == FillStatus.REFUSED:
				order.reject_order("exchange rejection")
			else:
				# Truly unknown status: leave the order active and alert.
				self.logger.warning('Unhandled fill status %s for order %s; order left active',
				                    fill_event.status, order_id)
				return
			# Only reached for an applied EXECUTED or CANCELLED reconciliation.
			self.order_storage.update_order(order)
			self.order_storage.deactivate_order(order.id, order.portfolio_id)
		except Exception as e:
			self.logger.error('Error reconciling fill for order %s: %s', order_id, e)

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""
		Process signal event with smart order creation logic.
		
		This method:
		1. Validates the signal
		2. For now, creates new orders (future: smart modify existing orders)
		3. Creates primary order (market/limit/stop) based on signal.order_type
		4. Creates stop-loss and take-profit orders if specified
		5. Handles execution based on market_execution mode
		
		Parameters
		----------
		signal_event : SignalEvent
			The signal event to process
			
		Returns
		-------
		List[OperationResult]
			List of operation results with OrderEvents for execution handler
		"""
		results = []

		try:
			# 0. Resolve fraction-of-cash sizing BEFORE validation (D-08/D-09).
			# The strategy emits quantity=0 (base.py:63); the order/risk layer resolves the
			# per-portfolio quantity here so the in-flight signal carries a real size before
			# the validator and order construction run. Doing this BEFORE validation is the
			# narrow gate for DEF-01-B: the running engine never presents quantity=0 to the
			# validator (so the offline run is admitted), while the validator's own zero-quantity
			# rejection — exercised directly by test_zero_quantity_signal — is left intact.
			sizing_error = self._resolve_signal_quantity(signal_event)
			if sizing_error is not None:
				return [sizing_error]

			# 1. Validate the signal
			if self.order_validator:
				validation_result = self.order_validator.validate_signal_pipeline(signal_event)
				if not validation_result.success:
					error_msg = f"Signal validation failed: {validation_result.summary}"
					self.logger.error('%s - %s', error_msg, 
									[msg.message for msg in validation_result.errors])
					return [OperationResult.failure_result(error_msg, 
						error_details=str(validation_result.errors), 
						operation_type="signal_validation")]
				
				# Log warnings if any
				if validation_result.has_warnings:
					self.logger.warning('Signal validation warnings: %s',
									   [msg.message for msg in validation_result.warnings])
			
			# 2. For now, always create new orders 
			# (Future enhancement: check existing orders and decide modify vs create new)
			create_results = self.create_orders_from_signal(signal_event)
			results.extend(create_results)
			
			self.logger.info('Processed signal for %s %s: %d operations completed', 
							signal_event.ticker, signal_event.action, len(results))
			
		except Exception as e:
			error_msg = f"Error processing signal: {e}"
			self.logger.error(error_msg, exc_info=True)
			results.append(OperationResult.failure_result(error_msg, 
				error_details=str(e), operation_type="signal_processing"))
		
		return results
	
	def create_orders_from_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""
		Create all orders from a signal event.
		
		Creates:
		1. Primary order (market/limit/stop based on signal.order_type)
		2. Stop-loss order (if signal.stop_loss > 0)
		3. Take-profit order (if signal.take_profit > 0)
		
		Parameters
		----------
		signal_event : SignalEvent
			The signal event containing order details
			
		Returns
		-------
		List[OperationResult]
			List of operation results for each order created
		"""
		results = []
		
		try:
			# Get exchange for orders
			portfolio_id = signal_event.portfolio_id
			if self.portfolio_handler:
				exchange = self.portfolio_handler.get_portfolio(portfolio_id).exchange
			else:
				exchange = "default"  # Fallback
			
			# 1. Create primary order based on order_type
			primary_order_result = self._create_primary_order(signal_event, exchange)
			results.append(primary_order_result)
			
			# Primary order id for bracket linkage
			primary_order_ids = primary_order_result.affected_order_ids
			parent_id = primary_order_ids[0] if primary_order_ids else None

			# 2. Create stop-loss order if specified
			if signal_event.stop_loss > 0:
				sl_result = self._create_stop_loss_order(signal_event, exchange, parent_id)
				results.append(sl_result)

			# 3. Create take-profit order if specified
			if signal_event.take_profit > 0:
				tp_result = self._create_take_profit_order(signal_event, exchange, parent_id)
				results.append(tp_result)

			success_count = sum(1 for r in results if r.success)
			self.logger.info(f'Created {success_count}/{len(results)} orders from signal: {signal_event.ticker} {signal_event.action}')
			
		except Exception as e:
			self.logger.error(f'Error creating orders from signal: {e}', exc_info=True)
			results.append(OperationResult.failure_result(
				f"Failed to create orders from signal",
				error_details=str(e),
				operation_type="create_orders_from_signal"
			))
		
		return results
	
	def _resolve_signal_quantity(self, signal_event: SignalEvent):
		"""
		Resolve a strategy sentinel quantity (qty<=0) in the order/risk seam (D-08/D-09).

		The strategy emits quantity=0 (base.py:63); the order/risk layer — NOT the strategy
		or position_sizer (D-09) — resolves the per-portfolio quantity. Two cases, both keyed
		on the long-only reference strategy (SMA_MACD: BUY enters a long, SELL exits it; the
		short block is commented out):

		* EXIT (SELL with an open long position): size the order to the position's net
		  quantity so the exit fully closes the long and a round-trip trade is recorded.
		  Without this the exit SELL would be sized independently and never net the long to
		  zero, so no position would ever close and the trade log would stay empty (M1-07).
		* ENTRY (BUY, or a SELL with no open position): fraction-of-cash sizing,
		  (0.95 * available_cash) / price — 95% buffer so float/rounding cannot overshoot a
		  cash check; fractional BTC.

		The resolved qty is carried on the in-flight signal so every downstream branch picks
		it up: the MARKET path reads signal.quantity internally (order.py:143) and the
		LIMIT/STOP branches pass signal_event.quantity explicitly.

		Idempotent: only resolves when the signal carries no explicit quantity (qty<=0), so a
		caller-supplied quantity is preserved and a second call after resolution is a no-op.

		Returns
		-------
		OperationResult | None
			A failure_result when the price is invalid (cannot size); otherwise None.
		"""
		if not signal_event.quantity or signal_event.quantity <= 0:
			price = signal_event.price
			if not price or price <= 0:
				return OperationResult.failure_result(
					f"Cannot size order: invalid signal price {price!r} for {signal_event.ticker}",
					operation_type="create_primary_order"
				)
			portfolio = self.portfolio_handler.get_portfolio(signal_event.portfolio_id)
			open_position = portfolio.get_open_position(signal_event.ticker)
			if signal_event.action == "SELL" and open_position is not None and open_position.net_quantity > 0:
				# Long-only exit: close the open long by selling its full quantity.
				signal_event.quantity = open_position.net_quantity
			else:
				# Entry (or SELL with no open long): fraction-of-cash sizing.
				signal_event.quantity = (0.95 * portfolio.cash) / price
		return None

	def _create_primary_order(self, signal_event: SignalEvent, exchange: str) -> OperationResult:
		"""
		Create the primary order based on signal.order_type.
		
		Parameters
		----------
		signal_event : SignalEvent
			The signal event
		exchange : str
			Exchange for the order
			
		Returns
		-------
		OperationResult
			Result of primary order creation
		"""
		try:
			# Fraction-of-cash sizing (D-08/D-09): idempotently resolve the per-portfolio
			# quantity in the order/risk seam. Normally already resolved at the top of
			# process_signal (before validation); kept here too so the direct
			# create_orders_from_signal entry point (which bypasses process_signal) is sized.
			sizing_error = self._resolve_signal_quantity(signal_event)
			if sizing_error is not None:
				return sizing_error

			order_type_str = signal_event.order_type.upper()

			if order_type_str == 'MARKET':
				order = Order.new_order(signal_event, exchange)
			elif order_type_str == 'LIMIT':
				order = Order.new_limit_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					action=signal_event.action,
					price=signal_event.price,
					quantity=signal_event.quantity,
					exchange=exchange,
					strategy_id=signal_event.strategy_id,
					portfolio_id=signal_event.portfolio_id
				)
			elif order_type_str == 'STOP':
				order = Order.new_stop_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					action=signal_event.action,
					price=signal_event.price,
					quantity=signal_event.quantity,
					exchange=exchange,
					strategy_id=signal_event.strategy_id,
					portfolio_id=signal_event.portfolio_id
				)
			else:
				return OperationResult.failure_result(
					f"Unsupported order type: {order_type_str}",
					operation_type="create_primary_order"
				)
			
			# Add to storage
			self.order_storage.add_order(order)
			
			# Generate OrderEvent for the primary order
			order_event = OrderEvent.new_order_event(order)
			
			return OperationResult.success_result(
				f"{order_type_str} order created: {order.ticker} {order.action} at {order.price}",
				order_events=[order_event],
				operation_type="create_primary_order",
				affected_order_ids=[order.id]
			)
			
		except Exception as e:
			return OperationResult.failure_result(
				f"Error creating primary order: {e}",
				error_details=str(e),
				operation_type="create_primary_order"
			)
	
	def _create_stop_loss_order(self, signal_event: SignalEvent, exchange: str,
	                            parent_id: int = None) -> OperationResult:
		"""
		Create a stop-loss order from a signal and emit its OrderEvent.

		Parameters
		----------
		signal_event : SignalEvent
			The originating signal (stop price taken from signal.stop_loss).
		exchange : str
			Exchange for the order.
		parent_id : int, optional
			Id of the primary order this stop-loss brackets (OCO linkage).

		Returns
		-------
		OperationResult
			Success result carrying the stop-loss OrderEvent, or a failure result.
		"""
		try:
			sl_order = Order.new_stop_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action='BUY' if signal_event.action == 'SELL' else 'SELL',
				price=signal_event.stop_loss,
				quantity=signal_event.quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
			sl_order.parent_order_id = parent_id
			self.order_storage.add_order(sl_order)
			order_event = OrderEvent.new_order_event(sl_order)
			self.logger.debug(f'Stop-loss order created: {sl_order.ticker} at {sl_order.price}')
			return OperationResult.success_result(
				f"Stop-loss order created: {sl_order.ticker} at {sl_order.price}",
				order_events=[order_event],
				operation_type="create_stop_loss",
				affected_order_ids=[sl_order.id]
			)
		except Exception as e:
			return OperationResult.failure_result(
				f"Error creating stop-loss order: {e}",
				error_details=str(e), operation_type="create_stop_loss")
	
	def _create_take_profit_order(self, signal_event: SignalEvent, exchange: str,
	                              parent_id: int = None) -> OperationResult:
		"""
		Create a take-profit order from a signal and emit its OrderEvent.

		Parameters
		----------
		signal_event : SignalEvent
			The originating signal (limit price taken from signal.take_profit).
		exchange : str
			Exchange for the order.
		parent_id : int, optional
			Id of the primary order this take-profit brackets (OCO linkage).

		Returns
		-------
		OperationResult
			Success result carrying the take-profit OrderEvent, or a failure result.
		"""
		try:
			tp_order = Order.new_limit_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action='BUY' if signal_event.action == 'SELL' else 'SELL',
				price=signal_event.take_profit,
				quantity=signal_event.quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
			tp_order.parent_order_id = parent_id
			self.order_storage.add_order(tp_order)
			order_event = OrderEvent.new_order_event(tp_order)
			self.logger.debug(f'Take-profit order created: {tp_order.ticker} at {tp_order.price}')
			return OperationResult.success_result(
				f"Take-profit order created: {tp_order.ticker} at {tp_order.price}",
				order_events=[order_event],
				operation_type="create_take_profit",
				affected_order_ids=[tp_order.id]
			)
		except Exception as e:
			return OperationResult.failure_result(
				f"Error creating take-profit order: {e}",
				error_details=str(e), operation_type="create_take_profit")
	
	def modify_order(self, order_id: int, new_price: float = None, new_quantity: float = None, 
	                portfolio_id: int = None, reason: str = "user modification") -> OperationResult:
		"""
		Modify an existing order and generate OrderEvent.
		
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
		OperationResult
			Result of the modification operation
		"""
		try:
			# Get the order
			order = self.order_storage.get_order_by_id(order_id, portfolio_id)
			if not order:
				return OperationResult.failure_result(
					f"Order {order_id} not found for modification",
					operation_type="modify_order"
				)
			
			# Validate the modification
			if self.order_validator:
				validation_messages = self.order_validator.validate_order_modification(
					order, new_price=new_price, new_quantity=new_quantity
				)
				
				if not self.order_validator.is_valid(validation_messages):
					error_messages = self.order_validator.get_errors(validation_messages)
					return OperationResult.failure_result(
						"Order modification validation failed",
						error_details=str([msg.message for msg in error_messages]),
						operation_type="modify_order"
					)
			
			# Apply the modification
			success = order.modify_order(new_price, new_quantity, reason)
			if success:
				# Update in storage
				self.order_storage.update_order(order)

				# Generate OrderEvent
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.MODIFY)
				
				self.logger.info('Order %s modified successfully: %s', order_id, reason)
				return OperationResult.success_result(
					f"Order {order_id} modified successfully",
					order_events=[order_event],
					operation_type="modify_order",
					affected_order_ids=[order_id]
				)
			else:
				return OperationResult.failure_result(
					f"Failed to modify order {order_id}",
					operation_type="modify_order"
				)
				
		except Exception as e:
			error_msg = f"Error modifying order {order_id}: {e}"
			self.logger.error(error_msg, exc_info=True)
			return OperationResult.failure_result(error_msg, 
				error_details=str(e), operation_type="modify_order")
	
	def cancel_order(self, order_id: int, portfolio_id: int = None, 
	                reason: str = "user cancellation") -> OperationResult:
		"""
		Cancel an existing order and generate OrderEvent.
		
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
		OperationResult
			Result of the cancellation operation
		"""
		try:
			# Get the order
			order = self.order_storage.get_order_by_id(order_id, portfolio_id)
			if not order:
				return OperationResult.failure_result(
					f"Order {order_id} not found for cancellation",
					operation_type="cancel_order"
				)
			
			# Cancel the order
			success = order.cancel_order(reason)
			if success:
				# Update in storage
				self.order_storage.update_order(order)

				# Generate OrderEvent for cancelled order
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.CANCEL)
				
				self.logger.info('Order %s cancelled: %s', order_id, reason)
				return OperationResult.success_result(
					f"Order {order_id} cancelled: {reason}",
					order_events=[order_event],
					operation_type="cancel_order",
					affected_order_ids=[order_id]
				)
			else:
				return OperationResult.failure_result(
					f"Failed to cancel order {order_id} (status: {order.status.name})",
					operation_type="cancel_order"
				)
				
		except Exception as e:
			error_msg = f"Error cancelling order {order_id}: {e}"
			self.logger.error(error_msg, exc_info=True)
			return OperationResult.failure_result(error_msg, 
				error_details=str(e), operation_type="cancel_order")
