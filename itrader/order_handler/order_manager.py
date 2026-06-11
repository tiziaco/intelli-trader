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

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, assert_never, cast
from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderCommand, OrderStatus, OrderType, FillStatus, Side, OrderOperationType, OrderTriggerSource
from ..core.exceptions import InsufficientFundsError, SizingPolicyViolation
from ..core.ids import OrderId, PortfolioId, StrategyId
from ..core.money import to_money
from ..core.portfolio_read_model import PortfolioReadModel
from ..core.sizing import PercentFromDecision, PercentFromFill, SLTPPolicy, TradingDirection
from .base import OrderStorage
from ..events_handler.events import OrderEvent, SignalEvent, FillEvent
from .order_validator import EnhancedOrderValidator
from .sizing_resolver import SizingResolver

_ONE = Decimal("1")


@dataclass(frozen=True)
class _PendingBracket:
	"""Context for a PercentFromFill bracket awaiting its parent's fill (D-13).

	RESEARCH Pattern 5 Option B: the manager holds a map keyed by the
	parent order id carrying the policy plus everything needed to build
	the children at fill time — the children do not exist until the
	parent EXECUTES, so a placeholder-priced child can never trigger
	before its parent fills (T-07-14, structurally unreachable).
	"""

	policy: PercentFromFill
	ticker: str
	action: str
	quantity: Decimal
	exchange: str
	strategy_id: StrategyId
	portfolio_id: "PortfolioId | int"


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

		# D-13 PercentFromFill pending brackets (RESEARCH Pattern 5 Option B):
		# parent order id -> the context needed to create the fill-anchored
		# children in on_fill. Entries are discarded when the parent reaches
		# CANCELLED/REJECTED without executing (T-07-15 — no orphans possible:
		# the children were never created).
		self._pending_brackets: Dict[OrderId, _PendingBracket] = {}

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
			reached a terminal state without any fill (WR-05), plus the
			fill-anchored PercentFromFill children created on the parent's
			EXECUTED fill (D-13, Pattern 5 Option B). The manager never
			touches the queue (D-18) — the handler enqueues these.
		"""
		out_events: List[OrderEvent] = []
		order_id = getattr(fill_event, 'order_id', None)
		if order_id is None:
			return out_events
		order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
		if order is None:
			return out_events
		# WR-04: the terminal release MUST run even if the reconciliation body
		# raises — a stuck BUY reservation corrupts buying power for the rest of
		# the run (T-05-17). The release is therefore moved into a `finally`,
		# gated by this flag so the early-return "unknown status" path (which
		# intentionally holds the reservation) does not trigger it. The body is
		# re-raised after logging (backtest fail-fast policy, matching the
		# portfolio side of the same FILL via _on_handler_error) so a corrupted
		# reconciliation aborts the run instead of producing silently-wrong
		# numbers.
		should_release = False
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
				return out_events
			# A terminal status was reached (EXECUTED/CANCELLED/REFUSED): arm the
			# release before any further work so a raise below still releases.
			should_release = True
			# Reached for every terminal-status fill (EXECUTED/CANCELLED/
			# REFUSED), whether or not the mirror transition applied.
			# D-20: no deactivate step — the terminal status set above already
			# removes the order from active queries via the is_active predicate.
			if applied:
				self.order_storage.update_order(order)
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
						out_events.extend(child_result.order_events)
			# D-13 PercentFromFill (RESEARCH Pattern 5 Option B): the parent's
			# EXECUTED fill is the moment its policy-declared children come
			# into existence — created, stored, linked and emitted priced from
			# the ACTUAL fill (IB attached-order semantics). A parent that
			# terminates WITHOUT executing (CANCELLED/REJECTED) discards its
			# pending entry: the children were never created, so no orphan can
			# exist and the WR-05 logic above is untouched (T-07-15).
			if fill_event.status == FillStatus.EXECUTED:
				pending = self._pending_brackets.pop(order_id, None)
				# WR-03 (part 1): only anchor children when the mirror actually
				# applied the fill. If add_fill was rejected (applied=False) the
				# parent never moved, so creating fill-anchored children would
				# link live SL/TP to a parent the engine still considers unfilled.
				if pending is not None and applied:
					out_events.extend(
						self._create_fill_anchored_children(order, pending, fill_event))
			else:
				self._pending_brackets.pop(order_id, None)
		except Exception as e:
			# WR-04: log with a stack trace and RE-RAISE — backtest fail-fast.
			# A reconciliation that cannot complete leaves the mirror and/or
			# reservation in an inconsistent state; continuing would produce
			# silently-wrong numbers. The portfolio side of the same FILL is
			# already fail-fast via _on_handler_error; the order side now
			# matches. The `finally` below still releases a terminal fill's
			# reservation before the exception propagates.
			self.logger.error('Error reconciling fill for order %s: %s',
			                  order_id, e, exc_info=True)
			raise
		finally:
			# WR-04: a terminal fill ALWAYS releases its reservation, even when
			# the reconciliation body raised after the terminal status was set
			# (T-05-17: a stuck reservation corrupts buying power for the whole
			# run). `should_release` is False on the non-terminal early-return
			# path, which intentionally holds the reservation. The release is
			# idempotent — never-reserved orders (SELLs, children) silently
			# no-op. Failures inside the release itself are logged, never masked.
			if should_release and self.portfolio_handler is not None:
				try:
					self.portfolio_handler.release(
						order.portfolio_id, order.id)
				except Exception:
					self.logger.error(
						'Failed to release reservation for order %s during fill reconciliation',
						order.id, exc_info=True)
		return out_events

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""
		Process signal event with entity-based validation (D-13) and
		create-all-then-emit bracket assembly (D-11).

		This method:
		0. Enforces the strategy's DECLARED admission constraints BEFORE
		   sizing — direction (D-08), then max_positions, then allow_increase
		   (D-10). A LONG_ONLY unsized SELL with no open long is an audited
		   REJECTED order (triggered_by=OrderTriggerSource.ADMISSION_DIRECTION), never a
		   short-opening fall-through (DEF-01-C dead structurally); an unsized
		   BUY-while-long with allow_increase=False is audited REJECTED
		   (triggered_by=OrderTriggerSource.ADMISSION_INCREASE); an unsized new-position BUY at
		   the max_positions limit is audited REJECTED
		   (triggered_by=OrderTriggerSource.ADMISSION_MAX_POSITIONS)
		1. Resolves sizing via the SizingResolver dispatching on the
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
			# 0. D-08 direction admission gate — BEFORE sizing. Enforces the
			# strategy's DECLARED TradingDirection: an unsized LONG_ONLY SELL
			# with no open long is an AUDITED rejection (Pitfall 4 — the exact
			# fall-through that opened the 2 blessed golden shorts is gone).
			gate_rejection = self._enforce_direction_admission(signal_event)
			if gate_rejection is not None:
				return [gate_rejection]

			# 0b. D-10 increase gate + max_positions gate (plan 07-08) — the
			# rest of step 0. Gate ordering: direction -> max_positions ->
			# increase; the cases are disjoint by position state (the increase
			# case is an OPEN ticker, the max_positions case is a NEW ticker)
			# so a signal trips at most ONE gate.
			gate_rejection = self._enforce_position_admission(signal_event)
			if gate_rejection is not None:
				return [gate_rejection]

			# 1. Resolve the DECLARED sizing policy BEFORE validation (D-01/D-08/D-09).
			# The strategy emits quantity=None (D-10); the order/risk layer resolves the
			# per-portfolio quantity through the SizingResolver dispatching on
			# signal.sizing_policy (M5-06). Sizing failures are AUDITED (D-06): the
			# entity is stored REJECTED with triggered_by=OrderTriggerSource.SIZING_POLICY inside the
			# resolve step and a failure_result short-circuits here — the DEF-01-B
			# narrow gate holds: the running engine never presents an unsized order
			# to the validator (which now hard-rejects any non-positive quantity).
			resolved = self._resolve_signal_quantity(signal_event)
			if isinstance(resolved, OperationResult):
				return [resolved]

			exchange = self._get_signal_exchange(signal_event)

			# 2. Entity-as-state (D-13): create the primary Order (PENDING) first.
			primary = self._build_primary_order(signal_event, exchange, resolved)
			if isinstance(primary, OperationResult):
				return [primary]

			# 3. Validate the ENTITY, not the signal (D-13). Rejection becomes an
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
						triggered_by=OrderTriggerSource.VALIDATOR,
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(validation_result.errors),
						operation_type=OrderOperationType.SIGNAL_VALIDATION)]

				# Log warnings if any
				if validation_result.has_warnings:
					self.logger.warning('Signal validation warnings: %s',
									   [msg.message for msg in validation_result.warnings])

			# 3b. Admission cash-reservation gate (Plan 05-06, Critical #22 / M4-01).
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
						primary.portfolio_id, primary.id, cost)
					reserved_primary = primary
				except InsufficientFundsError as e:
					# T-05-16: the failure goes through the Phase 4 audited
					# add_state_change path and is persisted — rejected orders
					# never vanish silently. Nothing is emitted (D-02).
					error_msg = f"Cash reservation failed: {e}"
					self.logger.warning('%s for %s %s', error_msg,
									signal_event.ticker, signal_event.action)
					primary.add_state_change(
						OrderStatus.REJECTED,
						str(e),
						triggered_by=OrderTriggerSource.CASH_RESERVATION,
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(e),
						operation_type=OrderOperationType.CASH_RESERVATION)]

			# 4. Create-all-then-emit (D-11): assemble brackets, store, emit.
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
					reserved_primary.portfolio_id,
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
						reserved_primary.portfolio_id,
						reserved_primary.id)
				except Exception:
					self.logger.error('Failed to release orphaned reservation for order %s',
									reserved_primary.id, exc_info=True)
			results.append(OperationResult.failure_result(error_msg,
				error_details=str(e), operation_type=OrderOperationType.SIGNAL_PROCESSING))

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
				operation_type=OrderOperationType.CREATE_ORDERS_FROM_SIGNAL
			)]

	def _get_signal_exchange(self, signal_event: SignalEvent) -> str:
		"""Resolve the exchange the signal's portfolio trades on (Protocol read, D-16)."""
		if self.portfolio_handler:
			# FL-02: events now declare portfolio_id as PortfolioId (#10 carry-forward).
			return self.portfolio_handler.exchange_for(
				signal_event.portfolio_id)
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
			operation_type=OrderOperationType.CREATE_PRIMARY_ORDER
		)

	def _assemble_bracket_and_emit(self, signal_event: SignalEvent, exchange: str,
	                               quantity: Decimal, primary: Order) -> List[OperationResult]:
		"""
		Create-all-then-emit (D-11): build every bracket entity first, link
		parent and children two-directionally, store all, THEN emit
		OrderEvents parent-first (primary, stop-loss, take-profit) — the
		queue arrival sequence is identical to the old emit-per-creation flow.

		D-13 SLTP precedence: explicit stop_loss/take_profit levels are
		PRIMARY — when either is present the declared sltp_policy is ignored
		and this path behaves exactly as before. Only a signal with no
		explicit level consults the policy: PercentFromDecision prices the
		children from the signal's decision price at assembly time;
		PercentFromFill defers them to the parent's fill.

		CARVE-OUT: PercentFromFill children are created at parent fill
		(IB attached-order semantics) — a documented exception to
		create-all-then-emit (Phase 4 D-11). Until the parent EXECUTES the
		children structurally do not exist (no placeholder-trigger hazard,
		T-07-14); on_fill creates, stores, links and emits them priced from
		the actual fill.

		D-07 v1 limitation: bracket children are sized at entry and are NOT
		resized by partial signal exits — a partial exit leaves the resting
		SL/TP quantities at their entry size.

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

			# D-13 SLTP dispatch with explicit precedence: explicit levels
			# WIN whenever either is present (the truthy semantics below,
			# preserved verbatim — even when an sltp_policy is also declared).
			# Only a signal with NO explicit level consults the policy.
			sl_price: Decimal = signal_event.stop_loss
			tp_price: Decimal = signal_event.take_profit
			sltp_policy = signal_event.sltp_policy
			if not (sl_price > 0 or tp_price > 0) and sltp_policy is not None:
				match sltp_policy:
					case PercentFromDecision():
						# Decision-time pricing: levels fixed from the
						# signal's decision price (price ± pct for a BUY,
						# mirrored for SELL) — Decimal arithmetic end-to-end
						# (string-path constants enforced by the policy types).
						sl_price, tp_price = self._bracket_levels(
							sltp_policy, to_money(signal_event.price),
							signal_event.action.value)
					case PercentFromFill():
						# CARVE-OUT to create-all-then-emit (Phase 4 D-11):
						# NO children at assembly — record the pending bracket;
						# on_fill creates them priced from the actual fill
						# (IB attached-order semantics, Pattern 5 Option B).
						self._pending_brackets[primary.id] = _PendingBracket(
							policy=sltp_policy,
							ticker=signal_event.ticker,
							action=signal_event.action.value,
							quantity=quantity,
							exchange=exchange,
							strategy_id=signal_event.strategy_id,
							portfolio_id=signal_event.portfolio_id,
						)
					case _:
						assert_never(sltp_policy)

			if sl_price > 0:
				sl_order = Order.new_stop_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					# Invert on Side (D-05); the entity stores str until M4.
					action='BUY' if signal_event.action is Side.SELL else 'SELL',
					price=sl_price,
					quantity=quantity,
					exchange=exchange,
					strategy_id=signal_event.strategy_id,
					portfolio_id=signal_event.portfolio_id
				)
				sl_order.parent_order_id = primary.id

			if tp_price > 0:
				tp_order = Order.new_limit_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					# Invert on Side (D-05); the entity stores str until M4.
					action='BUY' if signal_event.action is Side.SELL else 'SELL',
					price=tp_price,
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
				operation_type=OrderOperationType.CREATE_PRIMARY_ORDER,
				affected_order_ids=[primary.id]
			))

			if sl_order is not None:
				self.logger.debug(f'Stop-loss order created: {sl_order.ticker} at {sl_order.price}')
				results.append(OperationResult.success_result(
					f"Stop-loss order created: {sl_order.ticker} at {sl_order.price}",
					order_events=[OrderEvent.new_order_event(sl_order)],
					operation_type=OrderOperationType.CREATE_STOP_LOSS,
					affected_order_ids=[sl_order.id]
				))

			if tp_order is not None:
				self.logger.debug(f'Take-profit order created: {tp_order.ticker} at {tp_order.price}')
				results.append(OperationResult.success_result(
					f"Take-profit order created: {tp_order.ticker} at {tp_order.price}",
					order_events=[OrderEvent.new_order_event(tp_order)],
					operation_type=OrderOperationType.CREATE_TAKE_PROFIT,
					affected_order_ids=[tp_order.id]
				))

			success_count = sum(1 for r in results if r.success)
			self.logger.debug(f'Created {success_count}/{len(results)} orders from signal: {signal_event.ticker} {signal_event.action}')

		except Exception as e:
			# WR-03 (part 2): the PercentFromFill pending entry is registered at
			# assembly time (above) BEFORE add_order runs. If storage raises
			# afterwards the primary never reaches the exchange, so no fill will
			# ever consume the pending entry — disarm it here so a stale entry
			# cannot later anchor children to a parent that was never emitted.
			self._pending_brackets.pop(primary.id, None)
			self.logger.error(f'Error creating orders from signal: {e}', exc_info=True)
			results.append(OperationResult.failure_result(
				f"Failed to create orders from signal",
				error_details=str(e),
				operation_type=OrderOperationType.CREATE_ORDERS_FROM_SIGNAL
			))

		return results

	def _bracket_levels(self, policy: SLTPPolicy, anchor: Decimal,
	                    action: str) -> "tuple[Decimal, Decimal]":
		"""
		Compute (stop_loss, take_profit) percent-offset levels from ``anchor``.

		D-13: for a BUY parent the stop sits BELOW the anchor and the target
		ABOVE — sl = anchor * (1 - sl_pct), tp = anchor * (1 + tp_pct);
		mirrored for a SELL parent. The anchor is the decision price for
		PercentFromDecision and the actual fill price for PercentFromFill —
		identical ± pct math, different anchoring moment. Decimal end-to-end
		(the policy types enforce string-path constants, Pitfall 1).
		"""
		if action == Side.SELL.value:
			return anchor * (_ONE + policy.sl_pct), anchor * (_ONE - policy.tp_pct)
		return anchor * (_ONE - policy.sl_pct), anchor * (_ONE + policy.tp_pct)

	def _create_fill_anchored_children(self, parent: Order, pending: _PendingBracket,
	                                   fill_event: FillEvent) -> List[OrderEvent]:
		"""
		Create, store, link and return the PercentFromFill children (D-13).

		RESEARCH Pattern 5 Option B / IB attached-order semantics: invoked
		from on_fill on the parent's EXECUTED fill — the children are priced
		from the parent's ACTUAL fill price (the anchoring a strategy
		structurally cannot express). Linkage mirrors the assembly path
		exactly (parent_order_id on the children, child_order_ids on the
		parent); entities are stored BEFORE the OrderEvents are returned.
		The returned events ride the on_fill return list — the manager never
		touches the queue (D-18); the handler enqueues them.

		D-07 v1 limitation: the children carry the entry-sized quantity
		recorded at assembly — partial signal exits do not resize them.
		"""
		anchor = to_money(fill_event.price)
		sl_price, tp_price = self._bracket_levels(pending.policy, anchor, pending.action)
		# Invert on the parent's action (D-05); the entity stores str until M4.
		child_action = 'BUY' if pending.action == Side.SELL.value else 'SELL'
		sl_order = Order.new_stop_order(
			time=fill_event.time,
			ticker=pending.ticker,
			action=child_action,
			price=sl_price,
			quantity=pending.quantity,
			exchange=pending.exchange,
			strategy_id=pending.strategy_id,
			portfolio_id=pending.portfolio_id
		)
		sl_order.parent_order_id = parent.id
		tp_order = Order.new_limit_order(
			time=fill_event.time,
			ticker=pending.ticker,
			action=child_action,
			price=tp_price,
			quantity=pending.quantity,
			exchange=pending.exchange,
			strategy_id=pending.strategy_id,
			portfolio_id=pending.portfolio_id
		)
		tp_order.parent_order_id = parent.id
		# Two-directional linkage, exactly as the assembly path does it.
		parent.child_order_ids = [sl_order.id, tp_order.id]
		# Store all, THEN emit (the D-11 ordering, preserved within the fill).
		self.order_storage.add_order(sl_order)
		self.order_storage.add_order(tp_order)
		self.order_storage.update_order(parent)
		self.logger.debug('Fill-anchored bracket created for parent %s: SL %s / TP %s',
		                  parent.id, sl_order.price, tp_order.price)
		return [OrderEvent.new_order_event(sl_order), OrderEvent.new_order_event(tp_order)]

	def _enforce_direction_admission(self, signal_event: SignalEvent) -> Optional[OperationResult]:
		"""
		D-08 direction admission gate — step 0 of process_signal, BEFORE sizing.

		Enforces the strategy's DECLARED TradingDirection at admission,
		intercepting exactly the Pitfall-4 fall-through that opened the 2
		blessed golden shorts: an unsized LONG_ONLY SELL with no open long
		(no position, or net_quantity <= 0) previously fell through to entry
		sizing and opened a short. Now it is an AUDITED rejection
		(triggered_by=OrderTriggerSource.ADMISSION_DIRECTION) — DEF-01-C dies structurally.
		SHORT_ONLY + BUY with no open short is rejected symmetrically
		(oracle-dark: the golden strategy is LONG_ONLY).

		Preserved paths the gate never blocks:
		- Explicit-quantity signals (signal.quantity set) skip the gate —
		  the live/manual path is untouched.
		- LONG_SHORT passes: registration (strategies_handler), not
		  admission, polices LONG_SHORT.
		- LONG_ONLY SELL with an open long passes — the exit sizes as before.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when the direction is violated (the audited
			REJECTED entity is already persisted, Pitfall 5 option (a)),
			or None when the signal passes the gate.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			# Explicit caller-supplied quantity: the gate does not apply.
			return None
		if signal_event.direction is TradingDirection.LONG_SHORT:
			return None
		if self.portfolio_handler is None:
			# No position truth to consult — an unsized signal without a
			# read model fails loudly in the sizing step right after.
			return None
		# FL-02: events now declare portfolio_id as PortfolioId (#10 carry-forward).
		portfolio_id = signal_event.portfolio_id
		open_position = self.portfolio_handler.get_position(
			portfolio_id, signal_event.ticker)
		if (signal_event.direction is TradingDirection.LONG_ONLY
				and signal_event.action is Side.SELL
				and (open_position is None or open_position.net_quantity <= 0)):
			return self._reject_unsized_signal(
				signal_event,
				f"direction violation: LONG_ONLY strategy cannot open a short "
				f"(SELL with no open long) for {signal_event.ticker}",
				triggered_by=OrderTriggerSource.ADMISSION_DIRECTION,
				operation_type=OrderOperationType.SIGNAL_ADMISSION,
				error_prefix="Signal rejected at admission",
			)
		if (signal_event.direction is TradingDirection.SHORT_ONLY
				and signal_event.action is Side.BUY
				and (open_position is None or open_position.net_quantity >= 0)):
			return self._reject_unsized_signal(
				signal_event,
				f"direction violation: SHORT_ONLY strategy cannot open a long "
				f"(BUY with no open short) for {signal_event.ticker}",
				triggered_by=OrderTriggerSource.ADMISSION_DIRECTION,
				operation_type=OrderOperationType.SIGNAL_ADMISSION,
				error_prefix="Signal rejected at admission",
			)
		return None

	def _enforce_position_admission(self, signal_event: SignalEvent) -> Optional[OperationResult]:
		"""
		D-10 increase gate + max_positions gate — the rest of process_signal
		step 0 (plan 07-08), running after the direction gate, BEFORE sizing.

		Both gates police unsized BUYs only and dispatch on position state,
		so a signal trips at most ONE gate (no double-gating):

		* OPEN long for the ticker (net_quantity > 0) — the INCREASE case
		  (D-10). ``allow_increase=False`` is an AUDITED rejection
		  (triggered_by=OrderTriggerSource.ADMISSION_INCREASE) — SMA_MACD's declared-but-
		  ignored False, finally honest. ``allow_increase=True`` passes
		  through to entry sizing: the resolver's FractionOfCash arm reads
		  CURRENT available_cash, which IS "fraction of remaining available
		  cash" semantics (the CONTEXT discretion clause — oracle-dark, the
		  golden strategy declares False), and the existing check-and-reserve
		  gate downstream covers the cash check (the literal M5-06 check_cash
		  requirement — no new reservation code; insufficient funds still
		  produces the audited cash_reservation rejection, T-07-21).
		* NO open position for the ticker — the NEW-POSITION case. When the
		  portfolio's open-position count has reached the strategy's declared
		  ``max_positions``, the entry is an AUDITED rejection
		  (triggered_by=OrderTriggerSource.ADMISSION_MAX_POSITIONS). Oracle-dark: the golden
		  run is single-ticker with max_positions=1 and at most one open
		  position, so a new-entry BUY never trips it.
		* OPEN short for the ticker (net_quantity < 0) — a BUY is a cover/
		  exit; neither gate applies (short increases are out of v1 scope
		  with the margin model, D-09).

		Preserved paths the gates never block:
		- First entries (no open position, count under the limit) size
		  EXACTLY as before — byte-exactness of the post-07-07 reference
		  depends on it when N=0.
		- Explicit-quantity signals skip both gates (live/manual path).
		- SELLs pass: exits are sized downstream; direction polices the rest.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when a gate trips (the audited REJECTED entity
			is already persisted, Pitfall 5 option (a)), or None when the
			signal passes.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			# Explicit caller-supplied quantity: the gates do not apply.
			return None
		if signal_event.action is not Side.BUY:
			return None
		if self.portfolio_handler is None:
			# No position truth to consult — an unsized signal without a
			# read model fails loudly in the sizing step right after.
			return None
		# FL-02: events now declare portfolio_id as PortfolioId (#10 carry-forward).
		portfolio_id = signal_event.portfolio_id
		open_position = self.portfolio_handler.get_position(
			portfolio_id, signal_event.ticker)
		if open_position is not None and open_position.net_quantity > 0:
			# INCREASE case (D-10): BUY for an already-open long.
			if not signal_event.allow_increase:
				return self._reject_unsized_signal(
					signal_event,
					f"position increase not allowed by strategy "
					f"(allow_increase=False) for {signal_event.ticker}",
					triggered_by=OrderTriggerSource.ADMISSION_INCREASE,
					operation_type=OrderOperationType.SIGNAL_ADMISSION,
					error_prefix="Signal rejected at admission",
				)
			# allow_increase=True: fall through to entry sizing — the
			# FractionOfCash arm reads CURRENT available_cash (remaining-cash
			# semantics) and the check-and-reserve gate covers the cash check.
			return None
		if open_position is not None and open_position.net_quantity < 0:
			# BUY against an open short is a cover/exit — neither gate applies.
			return None
		# NEW-POSITION case: no open position for the ticker (or a fully
		# closed residual view). Enforce the declared concurrent-position cap.
		# W1-03: cache open_position_count once — it was called twice (the
		# guard comparison + the rejection message) in the same branch.
		open_count = self.portfolio_handler.open_position_count(portfolio_id)
		if open_count >= signal_event.max_positions:
			return self._reject_unsized_signal(
				signal_event,
				f"max positions reached: "
				f"{open_count} open "
				f">= max_positions={signal_event.max_positions}; "
				f"new entry for {signal_event.ticker} not allowed by strategy",
				triggered_by=OrderTriggerSource.ADMISSION_MAX_POSITIONS,
				operation_type=OrderOperationType.SIGNAL_ADMISSION,
				error_prefix="Signal rejected at admission",
			)
		return None

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
		  M1 expression. NOTE: a SELL with no open long can only reach this
		  branch for a LONG_SHORT direction (a sanctioned short entry) — the
		  D-08 admission gate in process_signal rejects the LONG_ONLY case
		  upstream (the 2-shorts Pitfall-4 mechanism, removed at the 07-07
		  owner-approved re-freeze).

		Sizing failures (invalid price, SizingPolicyViolation) are AUDITED
		rejections (D-06): the entity is built unsized, transitioned
		PENDING→REJECTED with triggered_by=OrderTriggerSource.SIZING_POLICY, and stored —
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
				operation_type=OrderOperationType.CREATE_PRIMARY_ORDER
			)
		# FL-02: events now declare portfolio_id as PortfolioId (#10 carry-forward).
		portfolio_id = signal_event.portfolio_id
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
		# Entry (or a LONG_SHORT SELL with no open long — a sanctioned short
		# entry; the D-08 gate rejected the LONG_ONLY case before sizing):
		# dispatch on the DECLARED policy (D-01). The FractionOfCash
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

	def _reject_unsized_signal(self, signal_event: SignalEvent, reason: str, *,
	                           triggered_by: OrderTriggerSource = OrderTriggerSource.SIZING_POLICY,
	                           operation_type: OrderOperationType = OrderOperationType.SIGNAL_SIZING,
	                           error_prefix: str = "Signal sizing failed") -> OperationResult:
		"""
		Audited admission/sizing rejection (D-06/D-08, Pitfall 5 option (a)).

		Build the primary Order entity UNSIZED (quantity 0) via the existing
		factory, transition it PENDING→REJECTED through the audited
		add_state_change path — ``triggered_by`` identifies the gate
		("sizing_policy" for D-06 sizing failures, "admission_direction" for
		the D-08 direction gate) and the reason names the violation — and
		persist it: rejected signals never vanish (the exact shape of the
		validator-rejection template). The entity is REJECTED before
		validation ever runs, so the validator's positive-quantity rule is
		never consulted on it. Timestamps stay event-derived (M2-09 — never
		wall clock: add_state_change defaults to the order's own event time).
		"""
		error_msg = f"{error_prefix}: {reason}"
		self.logger.warning('%s for %s %s', error_msg,
						signal_event.ticker, signal_event.action)
		try:
			exchange = self._get_signal_exchange(signal_event)
			rejected = self._build_primary_order(signal_event, exchange, Decimal("0"))
			if isinstance(rejected, OperationResult):
				return rejected
			rejected.add_state_change(
				OrderStatus.REJECTED,
				reason,
				triggered_by=triggered_by,
			)
			self.order_storage.add_order(rejected)
		except Exception as e:
			# The audit entity could not be built (e.g. an unrepresentable
			# price) — the rejection verdict stands; log the audit gap loudly.
			self.logger.error('Failed to persist audited admission rejection: %s',
							e, exc_info=True)
		return OperationResult.failure_result(error_msg,
			error_details=reason,
			operation_type=operation_type)

	def modify_order(self, order_id: int, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[int] = None, reason: str = "user modification") -> OperationResult:
		"""
		Modify an existing order and generate OrderEvent.
		
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
		OperationResult
			Result of the modification operation
		"""
		try:
			# Get the order
			order = self.order_storage.get_order_by_id(order_id, portfolio_id)
			if not order:
				return OperationResult.failure_result(
					f"Order {order_id} not found for modification",
					operation_type=OrderOperationType.MODIFY_ORDER
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
						operation_type=OrderOperationType.MODIFY_ORDER
					)
			
			# Apply the modification. Order money is Decimal (M2a); normalize the
			# Decimal modify args through the money entry point at this boundary.
			success = order.modify_order(
				to_money(new_price) if new_price is not None else None,
				to_money(new_quantity) if new_quantity is not None else None,
				reason)
			if success:
				# Update in storage
				self.order_storage.update_order(order)

				# WR-03 (part 3): if this parent has an armed PercentFromFill
				# pending bracket and the quantity changed, refresh the pending
				# quantity so fill-anchored children are created at the CURRENT
				# order quantity, not the stale assembly-time value.
				if new_quantity is not None:
					pending = self._pending_brackets.get(order.id)
					if pending is not None:
						self._pending_brackets[order.id] = replace(
							pending, quantity=to_money(new_quantity))

				# Generate OrderEvent
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.MODIFY)

				self.logger.info('Order %s modified successfully: %s', order_id, reason)
				return OperationResult.success_result(
					f"Order {order_id} modified successfully",
					order_events=[order_event],
					operation_type=OrderOperationType.MODIFY_ORDER,
					affected_order_ids=[order_id]
				)
			else:
				return OperationResult.failure_result(
					f"Failed to modify order {order_id}",
					operation_type=OrderOperationType.MODIFY_ORDER
				)
				
		except Exception as e:
			error_msg = f"Error modifying order {order_id}: {e}"
			self.logger.error(error_msg, exc_info=True)
			return OperationResult.failure_result(error_msg, 
				error_details=str(e), operation_type=OrderOperationType.MODIFY_ORDER)
	
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
					operation_type=OrderOperationType.CANCEL_ORDER
				)
			
			# Cancel the order
			success = order.cancel_order(reason)
			if success:
				# Update in storage
				self.order_storage.update_order(order)

				# WR-03 (part 1): a locally-cancelled PercentFromFill parent must
				# disarm its pending entry. Otherwise a late EXECUTED fill for
				# the same order would still anchor and emit SL/TP children
				# against a CANCELLED parent (on_fill keys child creation off the
				# fill, not the parent's live status). The pop is keyed by the
				# parent's id; children/non-PercentFromFill orders no-op.
				self._pending_brackets.pop(order.id, None)

				# WR-04: the local terminal transition owns the release. The
				# exchange only emits FillEvent(CANCELLED) for orders actually
				# resting in its matching engine, so a cancel it never
				# acknowledges would otherwise hold the BUY's reservation
				# forever. The release is idempotent — a later exchange
				# CANCELLED fill re-releasing is a silent no-op.
				if self.portfolio_handler is not None:
					self.portfolio_handler.release(
						order.portfolio_id, order.id)

				# Generate OrderEvent for cancelled order
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.CANCEL)
				
				self.logger.info('Order %s cancelled: %s', order_id, reason)
				return OperationResult.success_result(
					f"Order {order_id} cancelled: {reason}",
					order_events=[order_event],
					operation_type=OrderOperationType.CANCEL_ORDER,
					affected_order_ids=[order_id]
				)
			else:
				return OperationResult.failure_result(
					f"Failed to cancel order {order_id} (status: {order.status.name})",
					operation_type=OrderOperationType.CANCEL_ORDER
				)
				
		except Exception as e:
			error_msg = f"Error cancelling order {order_id}: {e}"
			self.logger.error(error_msg, exc_info=True)
			return OperationResult.failure_result(error_msg,
				error_details=str(e), operation_type=OrderOperationType.CANCEL_ORDER)

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
