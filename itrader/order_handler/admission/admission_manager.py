"""
Signal→order admission collaborator (D-07/D-08/D-09/D-13, WR-03/WR-04, T-05-17,
RESEARCH Pattern 5).

`AdmissionManager` owns the full signal→order pipeline MOVED VERBATIM (TAB) from
`order_manager.py` (D-13, pure code-motion — byte-exact behavior): the two public
entry points `process_signal` / `create_orders_from_signal` (relocated INTACT,
D-07) plus the admission gates, sizing resolution, primary-order construction,
commission estimation and the audited-rejection helper.

The two entry points behave exactly as before: the strategy's DECLARED admission
constraints are enforced BEFORE sizing (direction → max_positions → increase, D-08/
D-10), sizing resolves through the ONE SizingResolver (D-01/M5-06), the ENTITY is
validated (not the signal, D-13), a synchronous cash-reservation gate runs (WR-03),
and the bracket is assembled create-all-then-emit. Sizing/admission failures are
AUDITED REJECTED entities (D-06, Pitfall 5 option (a)) — rejected signals never
vanish.

The collaborator receives its dep subset by injection (D-09): `order_storage`,
`logger`, `order_validator`, `sizing_resolver`, `portfolio_handler` (read-model),
`commission_estimator`, the coordinator-owned `BracketBook` (`self._brackets`, the
single owner of the pending-bracket map, D-05), and the coordinator-owned
`BracketManager` (the bracket-assembly seam — admission reaches assembly through it,
holding NO reconcile/lifecycle ref, D-08). NO queue access (D-06/D-18) — the
manager returns OperationResults/OrderEvents and the handler performs all queue
puts. Money is Decimal end-to-end via `to_money` (NEVER `Decimal(float)`).
"""

from decimal import Decimal
from typing import Any, Callable, List, Optional

from ..order import Order
from ..operation_result import OperationResult
from ..base import OrderStorage
from ..order_validator import EnhancedOrderValidator
from ..sizing_resolver import SizingResolver
from ..brackets import BracketBook, BracketManager
from ...core.enums import OrderStatus, OrderType, Side, OrderOperationType, OrderTriggerSource
from ...core.exceptions import InsufficientFundsError, SizingPolicyViolation
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel
from ...core.sizing import TradingDirection
from ...events_handler.events import SignalEvent


class AdmissionManager:
	"""
	Signal→order admission pipeline (D-07/D-08/D-13).

	Owns `process_signal` / `create_orders_from_signal` (the two public entry
	points OrderManager delegates into, D-07) plus the admission gates, sizing
	resolution, primary-order construction and audited-rejection helper, all
	moved verbatim from OrderManager. Holds the injected coordinator-owned
	BracketBook (`self._brackets`, D-05) and BracketManager (`self.bracket_manager`,
	the bracket-assembly seam, D-08); never touches the events queue (D-18).
	"""

	def __init__(self, order_storage: OrderStorage, logger: Any,
	             order_validator: Optional[EnhancedOrderValidator],
	             sizing_resolver: Optional[SizingResolver],
	             portfolio_handler: Optional[PortfolioReadModel],
	             commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]],
	             brackets: BracketBook, bracket_manager: BracketManager) -> None:
		self.order_storage = order_storage
		self.logger = logger
		self.order_validator = order_validator
		self.sizing_resolver = sizing_resolver
		self.portfolio_handler = portfolio_handler
		self.commission_estimator = commission_estimator
		# D-05: the coordinator-owned single bracket-map owner, injected.
		self._brackets = brackets
		# D-08: the coordinator-owned bracket-assembly seam, injected — admission
		# reaches assembly through it WITHOUT holding a reconcile/lifecycle ref.
		self.bracket_manager = bracket_manager

	def _estimate_commission(self, order: Order) -> Decimal:
		"""Estimate the commission for an order's admission reservation (D-04).

		Delegates to the injected estimator (quantity, price) -> Decimal;
		``None`` -> ``Decimal("0")`` so the reservation amount degrades to
		exactly price x quantity — today's funds-check math.
		"""
		if self.commission_estimator is None:
			return Decimal("0")
		return self.commission_estimator(order.quantity, order.price)

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
			assembled = self.bracket_manager._assemble_bracket_and_emit(signal_event, exchange, resolved, primary)
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

			return self.bracket_manager._assemble_bracket_and_emit(signal_event, exchange, resolved, primary)

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
