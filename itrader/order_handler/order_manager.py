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

from decimal import Decimal
from typing import Any, List, Optional
from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderCommand, OrderStatus, OrderType, FillStatus, Side
from ..core.money import to_money
from .base import OrderStorage
from ..events_handler.events import OrderEvent, SignalEvent, FillEvent
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
	
	def __init__(self, order_storage: OrderStorage, logger: Any, order_handler_ref: Any,
	             market_execution: str = "immediate", portfolio_handler: Any = None) -> None:
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
				if not order.add_fill(order.remaining_quantity, to_money(fill_event.price),
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
		Process signal event with entity-based validation (D-13) and
		create-all-then-emit bracket assembly (D-11).

		This method:
		1. Resolves sizing BEFORE any entity creation (sizing failures
		   short-circuit, DEF-01-B narrow gate preserved)
		2. Creates the primary Order entity (PENDING) immediately —
		   the entity IS the pipeline state, the signal is never mutated
		3. Validates the ENTITY; rejection transitions it PENDING→REJECTED
		   through the audited add_state_change path and persists it
		4. On acceptance, builds the full bracket (SL/TP), links it
		   two-directionally, stores all and emits OrderEvents parent-first

		Parameters
		----------
		signal_event : SignalEvent
			The signal event to process

		Returns
		-------
		List[OperationResult]
			List of operation results with OrderEvents for execution handler
		"""
		results: List[OperationResult] = []

		try:
			# 0. Resolve fraction-of-cash sizing BEFORE validation (D-08/D-09).
			# The strategy emits quantity=None (D-10); the order/risk layer resolves the
			# per-portfolio quantity here. Sizing failures (invalid price) short-circuit
			# BEFORE any entity is created — the narrow DEF-01-B gate: the running engine
			# never presents an unsized order to the validator, while the validator's own
			# zero-quantity rejection (test_zero_quantity_signal) is left intact.
			resolved = self._resolve_signal_quantity(signal_event)
			if isinstance(resolved, OperationResult):
				return [resolved]

			exchange = self._get_signal_exchange(signal_event)

			# 1. Entity-as-state (D-13): create the primary Order (PENDING) first.
			primary = self._build_primary_order(signal_event, exchange, resolved)
			if isinstance(primary, OperationResult):
				return [primary]

			# 2. Validate the ENTITY, not the signal (D-13). Rejection becomes an
			# auditable FIX/Nautilus-style state change persisted to storage —
			# rejected signals no longer vanish.
			if self.order_validator:
				validation_result = self.order_validator.validate_order_pipeline(primary)
				if not validation_result.success:
					error_msg = f"Signal validation failed: {validation_result.summary}"
					self.logger.error('%s - %s', error_msg,
									[msg.message for msg in validation_result.errors])
					# Audited PENDING→REJECTED transition; the timestamp defaults to
					# the order's own event-derived time (M2-09 — never wall clock).
					primary.add_state_change(
						OrderStatus.REJECTED,
						validation_result.summary,
						triggered_by="validator",
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(validation_result.errors),
						operation_type="signal_validation")]

				# Log warnings if any
				if validation_result.has_warnings:
					self.logger.warning('Signal validation warnings: %s',
									   [msg.message for msg in validation_result.warnings])

			# 3. Create-all-then-emit (D-11): assemble brackets, store, emit.
			results.extend(self._assemble_bracket_and_emit(signal_event, exchange, resolved, primary))

			self.logger.debug('Processed signal for %s %s: %d operations completed',
							signal_event.ticker, signal_event.action, len(results))

		except Exception as e:
			error_msg = f"Error processing signal: {e}"
			self.logger.error(error_msg, exc_info=True)
			results.append(OperationResult.failure_result(error_msg,
				error_details=str(e), operation_type="signal_processing"))

		return results

	def create_orders_from_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""
		Create all orders from a signal event (direct, unvalidated entry point).

		Creates:
		1. Primary order (market/limit/stop based on signal.order_type)
		2. Stop-loss order (if signal.stop_loss > 0)
		3. Take-profit order (if signal.take_profit > 0)

		All entities are built FIRST with two-directional bracket linkage,
		then stored, then emitted parent-first (D-11). This entry point —
		used by OrderHandler.create_order — performs no validation, exactly
		like the pre-D-13 flow (validation lives in process_signal).

		Parameters
		----------
		signal_event : SignalEvent
			The signal event containing order details

		Returns
		-------
		List[OperationResult]
			List of operation results for each order created
		"""
		try:
			resolved = self._resolve_signal_quantity(signal_event)
			if isinstance(resolved, OperationResult):
				return [resolved]

			exchange = self._get_signal_exchange(signal_event)

			primary = self._build_primary_order(signal_event, exchange, resolved)
			if isinstance(primary, OperationResult):
				return [primary]

			return self._assemble_bracket_and_emit(signal_event, exchange, resolved, primary)

		except Exception as e:
			self.logger.error(f'Error creating orders from signal: {e}', exc_info=True)
			return [OperationResult.failure_result(
				f"Failed to create orders from signal",
				error_details=str(e),
				operation_type="create_orders_from_signal"
			)]

	def _get_signal_exchange(self, signal_event: SignalEvent) -> str:
		"""Resolve the exchange the signal's portfolio trades on."""
		if self.portfolio_handler:
			exchange: str = self.portfolio_handler.get_portfolio(signal_event.portfolio_id).exchange
			return exchange
		return "default"  # Fallback

	def _build_primary_order(self, signal_event: SignalEvent, exchange: str,
	                         quantity: Decimal) -> "Order | OperationResult":
		"""
		Build (but do not store/emit) the primary Order entity for a signal.

		D-13: the entity is created PENDING immediately after sizing resolves;
		the resolved quantity lives Decimal-native on the entity — the signal
		is never mutated.

		Returns
		-------
		Order | OperationResult
			The PENDING primary order, or a failure result for an
			unsupported order type (short-circuits before entity creation).
		"""
		# D-05: the signal carries an enum-typed OrderType; dispatch on the
		# member. The Order ENTITY keeps its str action until M4 — convert at
		# this boundary via .value.
		if signal_event.order_type is OrderType.MARKET:
			return Order.new_order(signal_event, exchange, quantity=quantity)
		elif signal_event.order_type is OrderType.LIMIT:
			return Order.new_limit_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action=signal_event.action.value,
				price=signal_event.price,
				quantity=quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
		elif signal_event.order_type is OrderType.STOP:
			return Order.new_stop_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action=signal_event.action.value,
				price=signal_event.price,
				quantity=quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
		return OperationResult.failure_result(
			f"Unsupported order type: {signal_event.order_type}",
			operation_type="create_primary_order"
		)

	def _assemble_bracket_and_emit(self, signal_event: SignalEvent, exchange: str,
	                               quantity: Decimal, primary: Order) -> List[OperationResult]:
		"""
		Create-all-then-emit (D-11): build every bracket entity first, link
		parent and children two-directionally, store all, THEN emit
		OrderEvents parent-first (primary, stop-loss, take-profit) — the
		queue arrival sequence is identical to the old emit-per-creation flow.

		Parameters
		----------
		signal_event : SignalEvent
			The originating signal (SL/TP prices read from it).
		exchange : str
			Exchange for the orders.
		quantity : Decimal
			The resolved order quantity (shared by all bracket legs).
		primary : Order
			The already-built (and validated) primary order entity.

		Returns
		-------
		List[OperationResult]
			One success result per created order, parent-first.
		"""
		results: List[OperationResult] = []

		try:
			# Build ALL bracket entities first — every UUIDv7 id exists
			# before anything is stored or emitted (D-11).
			sl_order: Optional[Order] = None
			tp_order: Optional[Order] = None

			if signal_event.stop_loss > 0:
				sl_order = Order.new_stop_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					# Invert on Side (D-05); the entity stores str until M4.
					action='BUY' if signal_event.action is Side.SELL else 'SELL',
					price=signal_event.stop_loss,
					quantity=quantity,
					exchange=exchange,
					strategy_id=signal_event.strategy_id,
					portfolio_id=signal_event.portfolio_id
				)
				sl_order.parent_order_id = primary.id

			if signal_event.take_profit > 0:
				tp_order = Order.new_limit_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					# Invert on Side (D-05); the entity stores str until M4.
					action='BUY' if signal_event.action is Side.SELL else 'SELL',
					price=signal_event.take_profit,
					quantity=quantity,
					exchange=exchange,
					strategy_id=signal_event.strategy_id,
					portfolio_id=signal_event.portfolio_id
				)
				tp_order.parent_order_id = primary.id

			# Two-directional linkage: the parent carries its children's ids
			# (order.py child_order_ids — declared since M2, populated here).
			primary.child_order_ids = [
				child.id for child in (sl_order, tp_order) if child is not None
			]

			# Store all, THEN emit — the primary OrderEvent below already
			# carries the complete child linkage.
			self.order_storage.add_order(primary)
			if sl_order is not None:
				self.order_storage.add_order(sl_order)
			if tp_order is not None:
				self.order_storage.add_order(tp_order)

			# Emit parent-first: primary, stop-loss, take-profit.
			results.append(OperationResult.success_result(
				f"{primary.type.name} order created: {primary.ticker} {primary.action} at {primary.price}",
				order_events=[OrderEvent.new_order_event(primary)],
				operation_type="create_primary_order",
				affected_order_ids=[primary.id]
			))

			if sl_order is not None:
				self.logger.debug(f'Stop-loss order created: {sl_order.ticker} at {sl_order.price}')
				results.append(OperationResult.success_result(
					f"Stop-loss order created: {sl_order.ticker} at {sl_order.price}",
					order_events=[OrderEvent.new_order_event(sl_order)],
					operation_type="create_stop_loss",
					affected_order_ids=[sl_order.id]
				))

			if tp_order is not None:
				self.logger.debug(f'Take-profit order created: {tp_order.ticker} at {tp_order.price}')
				results.append(OperationResult.success_result(
					f"Take-profit order created: {tp_order.ticker} at {tp_order.price}",
					order_events=[OrderEvent.new_order_event(tp_order)],
					operation_type="create_take_profit",
					affected_order_ids=[tp_order.id]
				))

			success_count = sum(1 for r in results if r.success)
			self.logger.debug(f'Created {success_count}/{len(results)} orders from signal: {signal_event.ticker} {signal_event.action}')

		except Exception as e:
			self.logger.error(f'Error creating orders from signal: {e}', exc_info=True)
			results.append(OperationResult.failure_result(
				f"Failed to create orders from signal",
				error_details=str(e),
				operation_type="create_orders_from_signal"
			))

		return results
	
	def _resolve_signal_quantity(self, signal_event: SignalEvent) -> "Decimal | OperationResult":
		"""
		Resolve the order quantity in the order/risk seam (D-08/D-09/D-13).

		The strategy emits quantity=None (D-10); the order/risk layer — NOT the
		strategy or position_sizer (D-09) — resolves the per-portfolio quantity.
		The resolved Decimal is RETURNED and flows native onto the Order entity
		(D-13) — the signal is never mutated (the WR-05 float coercion died with
		the signal mutation). Two sizing cases, both keyed on the long-only
		reference strategy (SMA_MACD: BUY enters a long, SELL exits it; the
		short block is commented out):

		* EXIT (SELL with an open long position): size the order to the position's net
		  quantity so the exit fully closes the long and a round-trip trade is recorded.
		  Without this the exit SELL would be sized independently and never net the long to
		  zero, so no position would ever close and the trade log would stay empty (M1-07).
		* ENTRY (BUY, or a SELL with no open position): fraction-of-cash sizing,
		  (0.95 * available_cash) / price — 95% buffer so float/rounding cannot overshoot a
		  cash check; fractional BTC.

		An explicit caller-supplied positive quantity is entered into the money
		domain unchanged (the same to_money entry the Order factories applied
		to the float signal field before D-13).

		Returns
		-------
		Decimal | OperationResult
			The resolved quantity, or a failure_result when the price is
			invalid (cannot size) — BEFORE any entity creation.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			# Explicit caller-supplied quantity: preserved as-is.
			return to_money(signal_event.quantity)

		price = signal_event.price
		if not price or price <= 0:
			return OperationResult.failure_result(
				f"Cannot size order: invalid signal price {price!r} for {signal_event.ticker}",
				operation_type="create_primary_order"
			)
		portfolio = self.portfolio_handler.get_portfolio(signal_event.portfolio_id)
		open_position = portfolio.get_open_position(signal_event.ticker)
		if signal_event.action is Side.SELL and open_position is not None and open_position.net_quantity > 0:
			# Long-only exit: close the open long by selling its full quantity.
			# net_quantity is Decimal (M2a entity money) — size in Decimal so the
			# exit nets the long to exactly the position quantity (D-13: the
			# Decimal flows native onto the Order entity, no float roundtrip).
			sized_qty: Decimal = open_position.net_quantity
			return sized_qty
		# Entry (or SELL with no open long): fraction-of-cash sizing.
		# portfolio.cash is Decimal on the ledger (M2-02); compute sizing in
		# Decimal — (0.95 * cash) / price — keeping full Decimal precision
		# through the intermediate (D-01: quantize ONLY at money boundaries,
		# never on an intermediate). The sized quantity is NOT a money-ledger
		# boundary — it is an in-flight intermediate the exchange consumes — so
		# it is carried at full precision; the float execution layer still sees
		# the identical float at the OrderEvent boundary coercion (D-04).
		# (Quantizing here to 8dp would both violate D-01 and shift the frozen
		# numeric oracle past the D-15 tolerance — DEF-02-04-A: no re-baseline.)
		raw_qty: Decimal = (Decimal("0.95") * portfolio.cash) / to_money(price)
		return raw_qty

	def modify_order(self, order_id: int, new_price: Optional[float] = None, new_quantity: Optional[float] = None,
	                portfolio_id: Optional[int] = None, reason: str = "user modification") -> OperationResult:
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
			
			# Apply the modification. Order money is Decimal (M2a); coerce the
			# float modify args at this boundary.
			success = order.modify_order(
				to_money(new_price) if new_price is not None else None,
				to_money(new_quantity) if new_quantity is not None else None,
				reason)
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
	
	def cancel_order(self, order_id: int, portfolio_id: Optional[int] = None, 
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
