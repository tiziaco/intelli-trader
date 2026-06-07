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
from typing import Any, Callable, Dict, List, Optional, cast
from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderCommand, OrderStatus, OrderType, FillStatus, Side
from ..core.exceptions import InsufficientFundsError, SizingPolicyViolation
from ..core.ids import PortfolioId
from ..core.money import to_money
from ..core.portfolio_read_model import PortfolioReadModel
from .base import OrderStorage
from ..events_handler.events import OrderEvent, SignalEvent, FillEvent
from .order_validator import EnhancedOrderValidator
from .sizing_resolver import SizingResolver


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
	
	def __init__(self, order_storage: OrderStorage, logger: Any,
	             market_execution: str = "immediate",
	             portfolio_handler: Optional[PortfolioReadModel] = None,
	             commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]] = None) -> None:
		"""
		Initialize the OrderManager.

		D-18: the manager has EXCLUSIVE ownership of the order storage and no
		back-reference to OrderHandler — layering is one-directional
		(facade -> manager -> storage). The manager never touches the events
		queue: it returns OperationResults carrying OrderEvents and the
		handler performs all queue puts.

		Parameters
		----------
		order_storage : OrderStorage
			Storage interface for order operations (manager-owned, D-18)
		logger : Logger
			Logger instance for order processing events
		market_execution : str
			Market order execution mode:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Execute market orders on next bar (realistic backtesting)
		portfolio_handler : PortfolioReadModel, optional
			Narrow portfolio read boundary for position-aware operations
			(D-16: the concrete handler conforms structurally)
		commission_estimator : Callable[[Decimal, Decimal], Decimal], optional
			Estimates the commission for an order as f(quantity, price) ->
			Decimal, feeding the admission reservation amount (Plan 05-06,
			D-04). INJECTED at wiring time — order_manager never imports
			across the execution boundary (RESEARCH Pattern 1). None means a
			zero estimate, which reproduces the pre-reservation funds-check
			math exactly (mode-agnostic; the golden run pins fees 0).
		"""
		self.order_storage = order_storage
		self.logger = logger
		self.market_execution = market_execution
		self.portfolio_handler = portfolio_handler
		self.commission_estimator = commission_estimator

		# Initialize validator if portfolio_handler is available
		self.order_validator = EnhancedOrderValidator(portfolio_handler) if portfolio_handler else None

		# The ONE sizing resolver (D-01, M5-06): dispatches on the signal's
		# DECLARED SizingPolicy. Same optionality pattern as the read model —
		# constructed only when a read model is present (resolution reads
		# portfolio state exclusively through the Protocol).
		self.sizing_resolver = SizingResolver(portfolio_handler) if portfolio_handler else None

	def _estimate_commission(self, order: Order) -> Decimal:
		"""Estimate the commission for an order's admission reservation (D-04).

		Delegates to the injected estimator (quantity, price) -> Decimal;
		``None`` -> ``Decimal("0")`` so the reservation amount degrades to
		exactly price x quantity — today's funds-check math.
		"""
		if self.commission_estimator is None:
			return Decimal("0")
		return self.commission_estimator(order.quantity, order.price)

	def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]:
		"""
		Reconcile the order mirror against an exchange fill.

		EXECUTED -> mark the order FILLED; CANCELLED -> mark CANCELLED;
		REFUSED -> mark REJECTED. The terminal status change alone moves the
		order out of active queries (D-20: "active" is an entity predicate,
		not a container) — the order stays in storage for the audit trail.

		Returns
		-------
		List[OrderEvent]
			CANCEL OrderEvents for bracket children orphaned by a parent that
			reached a terminal state without any fill (WR-05). The manager
			never touches the queue (D-18) — the handler enqueues these.
		"""
		cancel_events: List[OrderEvent] = []
		order_id = getattr(fill_event, 'order_id', None)
		if order_id is None:
			return cancel_events
		order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
		if order is None:
			return cancel_events
		try:
			applied = True
			if fill_event.status == FillStatus.EXECUTED:
				# D-22: fill_event.price is Decimal — to_money is an identity
				# normalization at this domain entry (kept deliberately: the
				# mirror never trusts an unnormalized money input).
				# Full-quantity contract (D-06, plan 06-04): matching is
				# Decimal-native end-to-end, so the exchange-truth fill
				# quantity passes straight through — the float-roundtrip
				# clamp that defended the old D-22 boundary is gone.
				if not order.add_fill(to_money(fill_event.quantity),
				                      to_money(fill_event.price),
				                      fill_event.time, "exchange fill"):
					# WR-02: do NOT early-return — the portfolio has already
					# settled this fill (FILL dispatches portfolio-first), so
					# the uniform terminal release below must still run or the
					# BUY's reservation is stuck forever (T-05-17). Only the
					# mirror update is skipped.
					self.logger.warning('add_fill rejected for order %s; mirror left unchanged', order_id)
					applied = False
			elif fill_event.status == FillStatus.CANCELLED:
				order.cancel_order("exchange cancellation")
			elif fill_event.status == FillStatus.REFUSED:
				order.reject_order("exchange rejection")
			else:
				# Truly unknown status: leave the order active and alert.
				# (No release either — an unknown status is not a terminal
				# reconciliation, so the reservation is intentionally held.)
				self.logger.warning('Unhandled fill status %s for order %s; order left active',
				                    fill_event.status, order_id)
				return cancel_events
			# Reached for every terminal-status fill (EXECUTED/CANCELLED/
			# REFUSED), whether or not the mirror transition applied.
			# D-20: no deactivate step — the terminal status set above already
			# removes the order from active queries via the is_active predicate.
			if applied:
				self.order_storage.update_order(order)
			# D-01/OQ2 (Plan 05-06): the reserver owns the release — a uniform
			# idempotent release on EVERY terminal reconciliation (FILLED/
			# CANCELLED/REJECTED). Never-reserved orders (SELLs, bracket
			# children) hit the silent no-op. Ordering vs the settlement debit
			# is irrelevant: the 05-05 invariant guard checks balance, never
			# available_balance, so a release-after-debit cannot false-positive
			# (T-05-17: no stuck reservations corrupting buying power).
			if self.portfolio_handler is not None:
				self.portfolio_handler.release(
					cast(PortfolioId, order.portfolio_id), order.id)
			# WR-05: a parent that reaches a terminal state WITHOUT any fill
			# (REFUSED/CANCELLED) leaves its protective SL/TP children resting
			# on the exchange with no position to protect — when price later
			# crosses them they would fill against a flat portfolio. Cancel
			# the children locally and return their CANCEL OrderEvents so the
			# exchange removes the resting orders too.
			if (fill_event.status in (FillStatus.CANCELLED, FillStatus.REFUSED)
					and order.child_order_ids and order.filled_quantity == 0):
				for child_id in order.child_order_ids:
					# 02-05 carry-over: the cancel_order API still declares int
					# ids while runtime ids are UUIDv7 — cast bridges until the
					# id-annotation retype lands (IN-06, deferred).
					child_result = self.cancel_order(
						cast(int, child_id), cast(int, order.portfolio_id),
						reason=f"parent order {order.id} terminal without fill")
					if child_result.success and child_result.order_events:
						cancel_events.extend(child_result.order_events)
		except Exception as e:
			self.logger.error('Error reconciling fill for order %s: %s', order_id, e)
		return cancel_events

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""
		Process signal event with entity-based validation (D-13) and
		create-all-then-emit bracket assembly (D-11).

		This method:
		1. Resolves sizing FIRST via the SizingResolver dispatching on the
		   signal's declared policy (D-01, M5-06); sizing failures store an
		   audited REJECTED entity and short-circuit (D-06 — the DEF-01-B
		   narrow gate preserved: no unsized order ever reaches validation)
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

		# WR-03: track the reserve -> emit window. If the admission reserve
		# succeeded but the primary OrderEvent was never produced (assembly/
		# storage failure, or an exception between reserve and emit), no fill
		# will ever arrive to trigger the terminal release in on_fill — the
		# reservation must be released here or it is orphaned forever.
		reserved_primary: Optional[Order] = None
		primary_emitted = False

		try:
			# 0. Resolve the DECLARED sizing policy BEFORE validation (D-01/D-08/D-09).
			# The strategy emits quantity=None (D-10); the order/risk layer resolves the
			# per-portfolio quantity through the SizingResolver dispatching on
			# signal.sizing_policy (M5-06). Sizing failures are AUDITED (D-06): the
			# entity is stored REJECTED with triggered_by="sizing_policy" inside the
			# resolve step and a failure_result short-circuits here — the DEF-01-B
			# narrow gate holds: the running engine never presents an unsized order
			# to the validator (which now hard-rejects any non-positive quantity).
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

			# 2b. Admission cash-reservation gate (Plan 05-06, Critical #22 / M4-01).
			# D-02: SYNCHRONOUS check-and-reserve — the only pre-trade gate. A
			# queue-mediated reserve was explicitly rejected: it would open a
			# TOCTOU window between the funds check and the order emit (T-05-14).
			# D-03: only the cash-debiting primary (BUY) reserves — SELLs and
			# bracket SL/TP children are exempt (no OCO double-reservation,
			# T-05-15). D-04: reserve = price x quantity + estimated commission;
			# the zero default reproduces the old funds-check math exactly.
			# Decimal-native arithmetic — intermediates are never quantized.
			if self.portfolio_handler is not None and primary.action == Side.BUY.value:
				cost = primary.price * primary.quantity + self._estimate_commission(primary)
				try:
					self.portfolio_handler.reserve(
						cast(PortfolioId, primary.portfolio_id), primary.id, cost)
					reserved_primary = primary
				except InsufficientFundsError as e:
					# T-05-16: the failure goes through the Phase 4 audited
					# add_state_change path and is persisted — rejected orders
					# never vanish silently. Nothing is emitted (D-02).
					error_msg = f"Cash reservation failed: {e}"
					self.logger.error('%s for %s %s', error_msg,
									signal_event.ticker, signal_event.action)
					primary.add_state_change(
						OrderStatus.REJECTED,
						str(e),
						triggered_by="cash_reservation",
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(e),
						operation_type="cash_reservation")]

			# 3. Create-all-then-emit (D-11): assemble brackets, store, emit.
			assembled = self._assemble_bracket_and_emit(signal_event, exchange, resolved, primary)
			primary_emitted = any(
				r.success and primary.id in (r.affected_order_ids or [])
				for r in assembled
			)
			if reserved_primary is not None and not primary_emitted \
					and self.portfolio_handler is not None:
				# WR-03: assembly failed after the admission reserve — no
				# OrderEvent reaches the exchange, so no terminal fill will
				# ever drive the on_fill release. Release here (idempotent).
				self.portfolio_handler.release(
					cast(PortfolioId, reserved_primary.portfolio_id),
					reserved_primary.id)
			results.extend(assembled)

			self.logger.debug('Processed signal for %s %s: %d operations completed',
							signal_event.ticker, signal_event.action, len(results))

		except Exception as e:
			error_msg = f"Error processing signal: {e}"
			self.logger.error(error_msg, exc_info=True)
			if reserved_primary is not None and not primary_emitted \
					and self.portfolio_handler is not None:
				# WR-03: same leak path for an exception raised anywhere
				# between the successful reserve and the primary emit.
				try:
					self.portfolio_handler.release(
						cast(PortfolioId, reserved_primary.portfolio_id),
						reserved_primary.id)
				except Exception:
					self.logger.error('Failed to release orphaned reservation for order %s',
									reserved_primary.id, exc_info=True)
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
		"""Resolve the exchange the signal's portfolio trades on (Protocol read, D-16)."""
		if self.portfolio_handler:
			# 02-05 carry-over: events still declare portfolio_id as int while
			# the runtime value is a native UUID — cast bridges until the
			# event-field retype lands (deferred, not mandated by this plan).
			return self.portfolio_handler.exchange_for(
				cast(PortfolioId, signal_event.portfolio_id))
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
		Resolve the order quantity in the order/risk seam (D-01/D-08/D-09/D-13, M5-06).

		The strategy DECLARES a SizingPolicy on the signal (D-01); the order/risk
		layer — never the strategy — resolves the per-portfolio quantity through
		the ONE SizingResolver. The resolved Decimal is RETURNED and flows native
		onto the Order entity (D-13) — the signal is never mutated. Branch ORDER
		preserves the M1 seam exactly (Pitfall 1 byte-exactness):

		* EXPLICIT: a caller-supplied positive quantity bypasses policy sizing
		  entirely (D-07 — the explicit partial-exit path, preserved verbatim).
		* EXIT (SELL with an open long position): the resolver sizes the exit from
		  the position's net_quantity and the signal's exit_fraction. The golden
		  exit_fraction == Decimal("1") returns net_quantity structurally
		  UNCHANGED (D-07 no-op — no multiplication artifact, identical bytes
		  to the M1 seam) so the exit fully closes the long and a round-trip
		  trade is recorded (M1-07).
		* ENTRY (BUY, or a SELL with no open long): the resolver dispatches on
		  signal.sizing_policy. The FractionOfCash arm reproduces
		  (fraction * available_cash) / to_money(price) operand-for-operand —
		  the golden Decimal("0.95") quantity is repr-identical to the deleted
		  M1 expression. NOTE: a SELL with no open long deliberately falls
		  through to entry sizing and opens a short (the 2-shorts mechanism,
		  Pitfall 4) — plan 07-07's direction guard removes that under owner
		  sign-off; removing it here would be an unsanctioned result change.

		Sizing failures (invalid price, SizingPolicyViolation) are AUDITED
		rejections (D-06): the entity is built unsized, transitioned
		PENDING→REJECTED with triggered_by="sizing_policy", and stored —
		rejected signals never vanish (Pitfall 5, option (a)).

		Returns
		-------
		Decimal | OperationResult
			The resolved quantity, or a failure_result when sizing fails
			(the audited REJECTED entity is already persisted).
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			# Explicit caller-supplied quantity: preserved as-is.
			return to_money(signal_event.quantity)

		price = signal_event.price
		if not price or price <= 0:
			# Invalid-price guard: same verdict as the M1 seam, now routed
			# through the audited D-06 rejection instead of a bare failure.
			return self._reject_unsized_signal(
				signal_event,
				f"Cannot size order: invalid signal price {price!r} for {signal_event.ticker}",
			)
		if self.portfolio_handler is None or self.sizing_resolver is None:
			# The run path always wires a read model before sizing; a missing
			# one previously surfaced as an AttributeError caught upstream —
			# the typed failure result is the same verdict, made explicit.
			return OperationResult.failure_result(
				f"Cannot size order: no portfolio read model available for {signal_event.ticker}",
				operation_type="create_primary_order"
			)
		# 02-05 carry-over: events declare portfolio_id as int; runtime is UUID.
		portfolio_id = cast(PortfolioId, signal_event.portfolio_id)
		open_position = self.portfolio_handler.get_position(
			portfolio_id, signal_event.ticker)
		if signal_event.action is Side.SELL and open_position is not None and open_position.net_quantity > 0:
			# Long-only exit: the resolver sizes the exit from exchange truth
			# (net_quantity is Decimal, M2a entity money; the read crosses the
			# boundary as a frozen PositionView, D-15). The golden
			# exit_fraction == Decimal("1") is the D-07 structural no-op:
			# net_quantity is returned UNCHANGED — the Decimal flows native
			# onto the Order entity, no float roundtrip (D-13), so the exit
			# nets the long to exactly the position quantity.
			return self.sizing_resolver.resolve_exit(
				open_position.net_quantity,
				signal_event.exit_fraction,
				signal_event.sizing_policy.step_size,
			)
		# Entry (or SELL with no open long — the preserved shorts fall-through,
		# Pitfall 4): dispatch on the DECLARED policy (D-01). The FractionOfCash
		# arm computes (fraction * available_cash) / to_money(price) — same
		# operands, same order as the M1 seam; available_cash is the single
		# trading-decision figure (D-14), Decimal on the ledger (M2-02). Full
		# Decimal precision rides through the intermediate (D-01: quantize ONLY
		# via an explicit policy step_size — the golden policy carries None);
		# since D-22 the Decimal rides the OrderEvent untouched and the exchange
		# converts ONCE at its float matching boundary.
		try:
			return self.sizing_resolver.resolve_entry(
				signal_event.sizing_policy,
				portfolio_id,
				price,
				stop=signal_event.stop_loss or None,
			)
		except SizingPolicyViolation as e:
			# D-06 fail-loud: the policy violation becomes an audited
			# REJECTED order naming the policy — never a silent drop.
			return self._reject_unsized_signal(signal_event, str(e))

	def _reject_unsized_signal(self, signal_event: SignalEvent,
	                           reason: str) -> OperationResult:
		"""
		D-06 audited sizing rejection (Pitfall 5, option (a)).

		Build the primary Order entity UNSIZED (quantity 0) via the existing
		factory, transition it PENDING→REJECTED through the audited
		add_state_change path with triggered_by="sizing_policy" and a reason
		naming the policy violation, and persist it — rejected signals never
		vanish (the exact shape of the validator-rejection template). The
		entity is REJECTED before validation ever runs, so the validator's
		positive-quantity rule is never consulted on it. Timestamps stay
		event-derived (M2-09 — never wall clock: add_state_change defaults to
		the order's own event time).
		"""
		error_msg = f"Signal sizing failed: {reason}"
		self.logger.error('%s for %s %s', error_msg,
						signal_event.ticker, signal_event.action)
		try:
			exchange = self._get_signal_exchange(signal_event)
			rejected = self._build_primary_order(signal_event, exchange, Decimal("0"))
			if isinstance(rejected, OperationResult):
				return rejected
			rejected.add_state_change(
				OrderStatus.REJECTED,
				reason,
				triggered_by="sizing_policy",
			)
			self.order_storage.add_order(rejected)
		except Exception as e:
			# The audit entity could not be built (e.g. an unrepresentable
			# price) — the rejection verdict stands; log the audit gap loudly.
			self.logger.error('Failed to persist audited sizing rejection: %s',
							e, exc_info=True)
		return OperationResult.failure_result(error_msg,
			error_details=reason,
			operation_type="signal_sizing")

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

				# WR-04: the local terminal transition owns the release. The
				# exchange only emits FillEvent(CANCELLED) for orders actually
				# resting in its matching engine, so a cancel it never
				# acknowledges would otherwise hold the BUY's reservation
				# forever. The release is idempotent — a later exchange
				# CANCELLED fill re-releasing is a silent no-op.
				if self.portfolio_handler is not None:
					self.portfolio_handler.release(
						cast(PortfolioId, order.portfolio_id), order.id)

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

	# --- Read interface (D-18) -------------------------------------------------
	# The manager owns the storage; OrderHandler read methods delegate here.
	# Pure pass-through layer: same names, same signatures as the facade.

	def get_order_by_id(self, order_id: int, portfolio_id: Optional[Any] = None) -> Optional[Order]:
		"""Get an order by its ID from the manager-owned storage."""
		return self.order_storage.get_order_by_id(order_id, portfolio_id)

	def get_orders_by_status(self, status: OrderStatus, portfolio_id: Optional[Any] = None) -> List[Order]:
		"""Get orders by their status from the manager-owned storage."""
		return self.order_storage.get_orders_by_status(status, portfolio_id)

	def get_active_orders(self, portfolio_id: Optional[Any] = None) -> List[Order]:
		"""Get all active orders (PENDING and PARTIALLY_FILLED)."""
		return self.order_storage.get_active_orders(portfolio_id)

	def get_order_history(self, order_id: int) -> List[Dict[str, Any]]:
		"""Get the state change history for an order."""
		return self.order_storage.get_order_history(order_id)

	def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[Any] = None) -> List[Order]:
		"""Get all orders for a specific ticker."""
		return self.order_storage.get_orders_by_ticker(ticker, portfolio_id)

	def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[Any] = None) -> List[Order]:
		"""Search orders based on criteria."""
		return self.order_storage.search_orders(criteria, portfolio_id)

	def get_orders_summary(self, portfolio_id: Optional[Any] = None) -> Dict[str, int]:
		"""Get a summary of orders by status."""
		return self.order_storage.get_orders_count_by_status(portfolio_id)
