"""Signal→order admission — the single validated signal→order path.

The strategy's DECLARED admission constraints are enforced BEFORE sizing (leaving →
readiness → direction → max_positions → increase → leverage), sizing resolves through the
ONE SizingResolver, the ENTITY is validated (not the signal), a synchronous
cash-reservation gate runs, and the bracket is assembled create-all-then-emit.
Sizing/admission failures become AUDITED REJECTED entities — rejected signals never vanish.

NO queue access: the manager returns OperationResults/OrderEvents and the handler
performs every queue put. Money is Decimal end-to-end via `to_money` (NEVER
`Decimal(float)`).
"""

import logging
from decimal import Decimal
from typing import Any, List, Optional

from ..order import Order
from ..operation_result import OperationResult
from ..base import OrderStorage
from ..order_validator import EnhancedOrderValidator
from ..sizing_resolver import SizingResolver
from ..brackets import BracketBook, BracketManager
from ...core.commission_estimator import FeeModelProvider
from ...core.enums import OrderStatus, OrderType, Side, OrderOperationType, OrderTriggerSource, PositionSide
from ...core.exceptions import InsufficientFundsError, SizingPolicyViolation
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel, PositionView
from ...core.sizing import TradingDirection, LeveredFraction
from ...events_handler.events import SignalEvent
from ...universe import Universe
# Read from the same declaration site ``PortfolioHandler`` and ``ExecutionHandler``
# read: a second ``'default'`` literal here is how the arms end up keying on
# different strings.
from ...execution_handler.execution_handler import DEFAULT_ACCOUNT_ID


class AdmissionManager:
	"""Signal→order admission pipeline.

	Owns `process_signal` — the single validated entry point OrderManager delegates
	into. Never touches the events queue.
	"""

	def __init__(self, order_storage: OrderStorage, logger: Any,
	             order_validator: Optional[EnhancedOrderValidator],
	             sizing_resolver: Optional[SizingResolver],
	             portfolio_handler: Optional[PortfolioReadModel],
	             fee_model_provider: Optional[FeeModelProvider],
	             brackets: BracketBook, bracket_manager: BracketManager,
	             universe: Optional[Universe] = None,
	             enable_margin: bool = False,
	             portfolio_max_leverage: Decimal = Decimal("1")) -> None:
		self.order_storage = order_storage
		self.logger = logger
		self.order_validator = order_validator
		self.sizing_resolver = sizing_resolver
		self.portfolio_handler = portfolio_handler
		# The WIRING seam only — a `(venue, account_id) -> FeeModel | None` provider.
		# NEVER dereference it at construction: the pair is not known until an order exists.
		self.fee_model_provider = fee_model_provider
		self._brackets = brackets
		# The bracket-assembly seam — admission reaches assembly WITHOUT holding a
		# reconcile/lifecycle ref.
		self.bracket_manager = bracket_manager
		# The order-domain instrument seam, set late via ``set_universe``. None degrades
		# the leverage cap to Decimal("1") with NO instrument read.
		self._universe = universe
		# enable_margin=False forces the spot arm everywhere (no division, no
		# instrument read).
		self._enable_margin = enable_margin
		self._portfolio_max_leverage = portfolio_max_leverage

	def set_universe(self, universe: Universe) -> None:
		"""Inject the symbol→Instrument read-model.

		The runner builds the ``Universe`` AFTER the order domain is constructed, so the
		seam is set late — mirroring ``SimulatedExchange.set_universe``.
		"""
		self._universe = universe

	def _resolve_account_id(self, order: Order) -> str:
		"""Resolve the ACCOUNT half of the fee-model lookup key.

		An order's economic target is the PAIR ``(venue, account_id)`` — the same key
		``ExecutionHandler.exchanges`` is keyed on; ``order.exchange`` carries the venue
		half. ``account_for`` stays ``Optional[str]`` because ``Portfolio.account_id`` is
		optional on the type; in practice every portfolio built through ``AccountFactory``
		carries a real id, so the coercion below is defence-in-depth rather than the
		single-account path it once was.

		⚠ ``account_for(...) or DEFAULT_ACCOUNT_ID`` is EXPRESSLY FORBIDDEN in
		``ExecutionHandler._resolve_account_id`` and is correct HERE — do not "unify" the
		two. There the pair selects an AUTHENTICATED SESSION, so coercing an unnamed
		account submits real orders through another account's credentials. Here it selects
		a FEE MODEL for a PRE-TRADE estimate: nothing is submitted, and dropping the
		coercion would price every such order against NO fee model — a reservation with
		zero fee headroom, which the golden run (``ZeroFeeModel``) cannot distinguish from
		the correct answer. What must never be silent is the OUTCOME — a pair resolving no
		fee model is logged in ``_estimate_commission`` before the estimate degrades.
		"""
		if self.portfolio_handler is None:
			return DEFAULT_ACCOUNT_ID
		return self.portfolio_handler.account_for(order.portfolio_id) or DEFAULT_ACCOUNT_ID

	def _estimate_commission(self, order: Order) -> Decimal:
		"""Estimate the commission for an order's admission reservation.

		The CURRENT fee model of the exchange serving the order's ``(venue, account_id)``
		pair comes from the injected ``FeeModelProvider``. The ADMISSION CONVENTION — the
		estimate is taken at ``side='buy', order_type='market'`` — is admission policy, so
		it lives HERE and nowhere else.

		Two DISTINCT zero paths, deliberately not conflated: no provider wired ->
		``Decimal("0")``, SILENT (a construction-time absence); the provider returns
		``None`` -> ``Decimal("0")`` but LOUD, because the reservation then books NO fee
		headroom on a venue that may charge real fees. ``Decimal("0")`` is BOTH the correct
		golden value and what a dead seam returns, so the log is the only signal
		discriminating the two — silence here is how a venue-blind provider survives review.
		KNOWN, DELIBERATELY DEFERRED: ``OkxExchange`` carries no ``fee_model`` attribute,
		so a live OKX order takes the second path today.
		"""
		if self.fee_model_provider is None:
			return Decimal("0")
		# CALL-TIME dereference, bound to a LOCAL and never cached on self:
		# ``update_config`` REPLACES the exchange's fee model, so a memoized model would
		# silently quote a retired rate forever.
		venue = order.exchange
		account_id = self._resolve_account_id(order)
		fee_model = self.fee_model_provider(venue, account_id)
		if fee_model is None:
			self.logger.warning(
				'No fee model for venue/account (%s, %s) — order %s %s reserves '
				'NO commission headroom (estimate degraded to 0)',
				venue, account_id, order.ticker, order.action)
			return Decimal("0")
		# Money boundary: a fee model returning a float would import binary-float-repr
		# error into the reservation, or raise Decimal+float TypeError in reserve.
		return to_money(fee_model.calculate_fee(
			order.quantity, order.price, side="buy", order_type="market"))

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""Process a signal with entity-based validation and create-all-then-emit assembly.

		Every admission gate runs BEFORE sizing and each violation becomes an audited
		REJECTED order carrying the gate as ``triggered_by`` — never a silent
		fall-through. Sizing then resolves (failures short-circuit, so no unsized order
		reaches validation), the primary Order entity is created PENDING — the entity IS
		the pipeline state, the signal is never mutated — the ENTITY is validated, cash is
		reserved, and the full bracket is built, linked two-directionally, stored and
		emitted parent-first.

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

		# Track the reserve -> emit window: if the reserve succeeded but the primary
		# OrderEvent was never produced, no fill will ever arrive to trigger the terminal
		# release in on_fill and the reservation leaks forever.
		reserved_primary: Optional[Order] = None
		primary_emitted = False

		try:
			# Snapshot the position ONCE and thread it through the gates. Value-identical
			# to per-site re-fetches under the single-writer contract — nothing mutates the
			# position within one process_signal (the reserve touches cash only). ``None``
			# when there is no read model.
			snap: PositionView | None = (
				self.portfolio_handler.get_position(
					signal_event.portfolio_id, signal_event.ticker)
				if self.portfolio_handler is not None else None)

			# 0-pre. Leaving-symbol gate — FIRST, before direction. A NEW entry for a
			# removed-but-still-held symbol is an AUDITED rejection; an exit passes.
			gate_rejection = self._enforce_leaving_symbol_admission(signal_event, snap)
			if gate_rejection is not None:
				return [gate_rejection]

			# 0a. Readiness gate — SECOND, after leaving and BEFORE direction. Stops an
			# externally-injected signal (which bypasses the strategy loop's secondary
			# check) from sizing a live order for a still-PENDING/FAILED symbol.
			gate_rejection = self._enforce_readiness_admission(signal_event, snap)
			if gate_rejection is not None:
				return [gate_rejection]

			# 0. Direction gate — BEFORE sizing. An unsized LONG_ONLY SELL with no open
			# long is an AUDITED rejection, not a short-opening fall-through.
			gate_rejection = self._enforce_direction_admission(signal_event, snap)
			if gate_rejection is not None:
				return [gate_rejection]

			# 0b. Increase gate + max_positions gate. The cases are disjoint by position
			# state (increase = an OPEN ticker, max_positions = a NEW ticker), so a signal
			# trips at most ONE gate.
			gate_rejection = self._enforce_position_admission(signal_event, snap)
			if gate_rejection is not None:
				return [gate_rejection]

			# 0c. Leverage-sizing gate — the last admission gate, BEFORE sizing. The f>1
			# guard lives HERE, not in the config-free resolver: the policy and the
			# resolver never know enable_margin.
			gate_rejection = self._enforce_leverage_admission(signal_event)
			if gate_rejection is not None:
				return [gate_rejection]

			# 1. Resolve the DECLARED sizing policy BEFORE validation. Sizing failures are
			# AUDITED inside the resolve step and short-circuit here, so the engine never
			# presents an unsized order to the validator.
			resolved = self._resolve_signal_quantity(signal_event, snap)
			if isinstance(resolved, OperationResult):
				return [resolved]

			exchange = self._get_signal_exchange(signal_event)

			# 2. Entity-as-state: create the primary Order (PENDING) first.
			primary = self._build_primary_order(signal_event, exchange, resolved)
			if isinstance(primary, OperationResult):
				return [primary]

			# 3. Validate the ENTITY, not the signal. Rejection becomes an auditable
			# state change persisted to storage — rejected signals never vanish.
			if self.order_validator:
				validation_result = self.order_validator.validate_order_pipeline(primary)
				if not validation_result.success:
					error_msg = f"Signal validation failed: {validation_result.summary}"
					# WARNING, not ERROR: an out-of-cash / dust-quantity rejection is not a
					# system error. Behind isEnabledFor because the eager f-string + list-comp make
					# this the one hot callsite the central wrapper gate cannot skip (Python
					# evaluates the args before the call).
					if self.logger._stdlib.isEnabledFor(logging.WARNING):
						self.logger.warning('%s - %s', error_msg,
										[msg.message for msg in validation_result.errors])
					# Audited PENDING→REJECTED; the timestamp is event-derived, never wall clock.
					primary.add_state_change(
						OrderStatus.REJECTED,
						validation_result.summary,
						triggered_by=OrderTriggerSource.VALIDATOR,
					)
					self.order_storage.add_order(primary)
					return [OperationResult.failure_result(error_msg,
						error_details=str(validation_result.errors),
						operation_type=OrderOperationType.SIGNAL_VALIDATION)]

				if validation_result.has_warnings:
					self.logger.warning('Signal validation warnings: %s',
									   [msg.message for msg in validation_result.warnings])

			# 3b. Admission cash-reservation gate: a SYNCHRONOUS check-and-reserve. A
			# queue-mediated reserve was explicitly rejected — it opens a TOCTOU window
			# between the funds check and the order emit. Only the cash-debiting primary
			# (BUY) reserves; SELLs and bracket SL/TP children are exempt, so there is no
			# OCO double-reservation. Intermediates are never quantized.
			if self.portfolio_handler is not None and primary.action is Side.BUY:
				# CRITICAL: the spot arm must NOT route through notional / 1 — Decimal
				# division is context-sensitive and a /1 can shift the exponent, drifting
				# the byte-exact oracle. Use a real if-branch, never a forced-to-1 division.
				notional = primary.price * primary.quantity
				commission = self._estimate_commission(primary)
				if self._enable_margin:
					effective_leverage = self._effective_leverage(signal_event)
					cost = notional / effective_leverage + commission
				else:
					cost = notional + commission
				try:
					self.portfolio_handler.reserve(
						primary.portfolio_id, primary.id, cost)
					reserved_primary = primary
				except InsufficientFundsError as e:
					# Audited and persisted — rejected orders never vanish. Nothing is emitted.
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

			# 3c. Short-increase margin SOLVENCY gate — the admission-side mirror of the
			# long arm. The reserve gate above is BUY-only (a SELL credits cash), so an
			# admitted SELL-add against an OPEN SHORT books no reservation and its margin
			# lock would ride settlement alone; an UNFUNDED short add then slips past
			# admission and either settles silently or fail-fast aborts in
			# SimulatedMarginAccount.assert_lock_fits_buying_power. This only CHECKS — it
			# emits an audited CASH_RESERVATION rejection but NEVER books a reservation.
			# Guarded to the short ADD (open SHORT + SELL primary) and run AFTER sizing so
			# add_notional is known; it covers explicit-quantity short adds too (the
			# position admission gate is skipped for explicit quantity).
			if (self.portfolio_handler is not None
					and primary.action is Side.SELL):
				open_short = self.portfolio_handler.get_position(
					primary.portfolio_id, primary.ticker)
				if (open_short is not None
						and open_short.side is PositionSide.SHORT):
					# Prospective post-add aggregate lock = (existing + add notional) /
					# effective_leverage. As in the BUY gate the spot arm stays division-free.
					existing_notional = open_short.net_quantity * open_short.avg_price
					add_notional = primary.price * primary.quantity
					aggregate_notional = existing_notional + add_notional
					if self._enable_margin:
						effective_leverage = self._effective_leverage(signal_event)
						prospective_lock = aggregate_notional / effective_leverage
						# Settlement RELEASES this position's OWN prior lock then re-locks the
						# new aggregate, so the admission headroom must credit that prior lock
						# back to available_cash — otherwise the gate double-counts it and
						# over-rejects a fundable add.
						own_prior_lock = existing_notional / effective_leverage
					else:
						prospective_lock = aggregate_notional
						own_prior_lock = existing_notional
					buying_power = (
						self.portfolio_handler.available_cash(primary.portfolio_id)
						+ own_prior_lock)
					if prospective_lock > buying_power:
						# _reject_unsized_signal builds its OWN UNSIZED audit entity and
						# persists it — exactly ONE audited REJECTED order, queue untouched,
						# available_cash unchanged. Do NOT also store `primary`.
						return [self._reject_unsized_signal(
							signal_event,
							f"insufficient margin for short increase: required "
							f"{prospective_lock} > buying power {buying_power} "
							f"for {primary.ticker}",
							triggered_by=OrderTriggerSource.CASH_RESERVATION,
							operation_type=OrderOperationType.CASH_RESERVATION,
							error_prefix="Signal rejected at admission",
						)]

			# 4. Create-all-then-emit: assemble brackets, store, emit.
			assembled = self.bracket_manager._assemble_bracket_and_emit(signal_event, exchange, resolved, primary)
			primary_emitted = any(
				r.success and primary.id in (r.affected_order_ids or [])
				for r in assembled
			)
			if reserved_primary is not None and not primary_emitted \
					and self.portfolio_handler is not None:
				# Assembly failed after the reserve — no OrderEvent reaches the exchange,
				# so no terminal fill will ever drive the on_fill release (idempotent).
				self.portfolio_handler.release(
					reserved_primary.portfolio_id,
					reserved_primary.id)
			results.extend(assembled)

		except Exception as e:
			error_msg = f"Error processing signal: {e}"
			self.logger.error(error_msg, exc_info=True)
			if reserved_primary is not None and not primary_emitted \
					and self.portfolio_handler is not None:
				# Same leak path for an exception between the reserve and the primary emit.
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

	def _get_signal_exchange(self, signal_event: SignalEvent) -> str:
		"""Resolve the exchange the signal's portfolio trades on (Protocol read)."""
		if self.portfolio_handler:
			return self.portfolio_handler.exchange_for(
				signal_event.portfolio_id)
		return "default"  # Fallback

	def _build_primary_order(self, signal_event: SignalEvent, exchange: str,
	                         quantity: Decimal) -> "Order | OperationResult":
		"""Build (but do not store/emit) the primary Order entity for a signal.

		The entity is created PENDING immediately after sizing resolves; the resolved
		quantity lives Decimal-native on the entity — the signal is never mutated.

		Returns
		-------
		Order | OperationResult
			The PENDING primary order, or a failure result for an
			unsupported order type (short-circuits before entity creation).
		"""
		# The admission-clamped EFFECTIVE leverage, computed once and threaded onto the
		# Order so it flows OrderEvent -> FillEvent -> Transaction -> Position.
		effective_leverage = self._effective_leverage(signal_event)
		if signal_event.order_type is OrderType.MARKET:
			return Order.new_order(signal_event, exchange, quantity=quantity,
			                       leverage=effective_leverage)
		elif signal_event.order_type is OrderType.LIMIT:
			return Order.new_limit_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action=signal_event.action,
				price=signal_event.price,
				quantity=quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id,
				# The CLAMPED leverage rides every order type, so position-life locked
				# margin equals the admission reservation.
				leverage=effective_leverage,
			)
		elif signal_event.order_type is OrderType.STOP:
			return Order.new_stop_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action=signal_event.action,
				price=signal_event.price,
				quantity=quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id,
				leverage=effective_leverage,
			)
		return OperationResult.failure_result(
			f"Unsupported order type: {signal_event.order_type}",
			operation_type=OrderOperationType.CREATE_PRIMARY_ORDER
		)

	def _enforce_leaving_symbol_admission(self, signal_event: SignalEvent,
	                                      snap: "PositionView | None") -> Optional[OperationResult]:
		"""Leaving-symbol admission gate — the FIRST gate in process_signal.

		When a symbol is REMOVED from the universe while it still holds an open position
		(orphan-and-track), the remove-policy consumer marks it ``leaving``. This gate
		BLOCKS a NEW entry for such a symbol — it must never open fresh exposure while
		winding down — while ALLOWING a sanctioned EXIT so the orphaned position can go
		flat. Runs BEFORE the direction gate so a signal that would also trip direction is
		still reported as ADMISSION_LEAVING.

		No-op (early-return None) for explicit-quantity signals, when no universe is
		injected, and for a ticker outside the leaving set. A sanctioned exit is
		dispatched on ``side`` (the read model carries an UNSIGNED magnitude): a SELL
		against an open LONG, or a BUY against an open SHORT. Everything else for a
		leaving ticker is an AUDITED rejection.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when a new entry is blocked (the audited REJECTED
			entity is already persisted), or None when the signal passes.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			return None
		if self._universe is None:
			return None
		if signal_event.ticker not in self._universe.leaving_symbols():
			return None
		is_sanctioned_exit = snap is not None and (
			(signal_event.action is Side.SELL and snap.side is PositionSide.LONG)
			or (signal_event.action is Side.BUY and snap.side is PositionSide.SHORT)
		)
		if is_sanctioned_exit:
			return None
		return self._reject_unsized_signal(
			signal_event,
			f"universe removal: new entries blocked for leaving symbol "
			f"{signal_event.ticker}",
			triggered_by=OrderTriggerSource.ADMISSION_LEAVING,
			operation_type=OrderOperationType.SIGNAL_ADMISSION,
			error_prefix="Signal rejected at admission",
		)

	def _enforce_readiness_admission(self, signal_event: SignalEvent,
	                                 snap: "PositionView | None") -> Optional[OperationResult]:
		"""Readiness admission gate — the PRIMARY consumer of per-symbol readiness.

		The strategy loop carries a cheap SECONDARY defensive check; THIS gate is the one
		that stops a signal BYPASSING the strategy loop entirely (an externally-injected
		SignalEvent admitted by the ingress allowlist). A still-``PENDING`` (or ``FAILED``)
		symbol has not finished its warmup backfill, so sizing it into a live order would
		trade on an unwarmed symbol. A sanctioned EXIT is still ALLOWED, so a winding-down
		orphan whose readiness may be stale (force-close tears the stream down at removal)
		can go flat.

		Runs SECOND: leaving-first so a leaving symbol's stale readiness never mis-triggers
		ADMISSION_READINESS on an exit the leaving gate already allowed;
		readiness-before-direction so a PENDING symbol is intercepted with the correct
		reason before direction sizing is consulted.

		No-op (early-return None) for explicit-quantity signals, when no universe is
		injected, and for a READY ticker — the common path, since construction members are
		always READY.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when a non-READY new entry is blocked (the audited
			REJECTED entity is already persisted), or None when the signal passes.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			return None
		if self._universe is None:
			return None
		if self._universe.is_ready(signal_event.ticker):
			return None
		is_sanctioned_exit = snap is not None and (
			(signal_event.action is Side.SELL and snap.side is PositionSide.LONG)
			or (signal_event.action is Side.BUY and snap.side is PositionSide.SHORT)
		)
		if is_sanctioned_exit:
			return None
		return self._reject_unsized_signal(
			signal_event,
			f"symbol not ready: {signal_event.ticker} is warming up (readiness gate)",
			triggered_by=OrderTriggerSource.ADMISSION_READINESS,
			operation_type=OrderOperationType.SIGNAL_ADMISSION,
			error_prefix="Signal rejected at admission",
		)

	def _enforce_direction_admission(self, signal_event: SignalEvent,
	                                 snap: "PositionView | None") -> Optional[OperationResult]:
		"""Direction admission gate — step 0 of process_signal, BEFORE sizing.

		Enforces the strategy's DECLARED TradingDirection at admission. An unsized
		LONG_ONLY SELL with no open long is an AUDITED rejection
		(triggered_by=ADMISSION_DIRECTION), not a fall-through into entry sizing that
		would open a short; SHORT_ONLY + BUY with no open short is rejected symmetrically.

		Never blocks: explicit-quantity signals (the live/manual path); LONG_SHORT, which
		``StrategiesHandler.add_strategy`` polices at registration, not admission; and a
		LONG_ONLY SELL with an open long, which sizes as an exit.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when the direction is violated (the audited
			REJECTED entity is already persisted), or None when the signal passes.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			return None
		if signal_event.direction is TradingDirection.LONG_SHORT:
			return None
		if self.portfolio_handler is None:
			# No position truth to consult — an unsized signal without a read model
			# fails loudly in the sizing step right after, as does "snap is None".
			return None
		open_position = snap
		# Dispatch on ``side``, NOT the sign of ``net_quantity`` (an UNSIGNED magnitude —
		# see ``_resolve_signal_quantity``): a SELL is a sanctioned exit ONLY when an open
		# LONG exists, a BUY a sanctioned cover ONLY when an open SHORT exists.
		if (signal_event.direction is TradingDirection.LONG_ONLY
				and signal_event.action is Side.SELL
				and (open_position is None
				     or open_position.side is not PositionSide.LONG)):
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
				and (open_position is None
				     or open_position.side is not PositionSide.SHORT)):
			return self._reject_unsized_signal(
				signal_event,
				f"direction violation: SHORT_ONLY strategy cannot open a long "
				f"(BUY with no open short) for {signal_event.ticker}",
				triggered_by=OrderTriggerSource.ADMISSION_DIRECTION,
				operation_type=OrderOperationType.SIGNAL_ADMISSION,
				error_prefix="Signal rejected at admission",
			)
		return None

	def _enforce_position_admission(self, signal_event: SignalEvent,
	                                snap: "PositionView | None") -> Optional[OperationResult]:
		"""Increase gate + max_positions gate — the rest of step 0, BEFORE sizing.

		Both gates dispatch on position state, so a signal trips at most ONE:

		* OPEN long — the INCREASE case. ``allow_increase=False`` is an AUDITED rejection
		  (ADMISSION_INCREASE); ``allow_increase=True`` passes through to entry sizing,
		  where the resolver's FractionOfCash arm reads CURRENT available_cash
		  ("fraction of remaining cash" semantics) and the downstream check-and-reserve
		  gate covers the cash check.
		* NO open position — the NEW-POSITION case. Once the portfolio's open-position
		  count reaches the strategy's declared ``max_positions``, the entry is an AUDITED
		  rejection (ADMISSION_MAX_POSITIONS).
		* OPEN short — a BUY is a cover/exit and passes, sized downstream. An unsized SELL
		  is a same-side ADD, gated behind ``allow_increase`` symmetrically with the long
		  INCREASE gate.

		Never blocks: first entries under the limit, explicit-quantity signals, and SELLs
		unless they add to an open short with allow_increase=False.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when a gate trips (the audited REJECTED entity
			is already persisted), or None when the signal passes.
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			return None
		if signal_event.action is not Side.BUY:
			# An unsized SELL that ADDS to an open short is gated behind the SAME
			# `allow_increase` flag as the long INCREASE gate. Without it the SELL passes
			# the direction gate (SHORT_ONLY+SELL is not policed), is not a reduction in
			# _resolve_signal_quantity, and falls into FIRST-ENTRY `resolve_entry` sizing.
			if (snap is not None and snap.side is PositionSide.SHORT):
				if not signal_event.allow_increase:
					return self._reject_unsized_signal(
						signal_event,
						f"position increase not allowed by strategy "
						f"(allow_increase=False) for {signal_event.ticker}",
						triggered_by=OrderTriggerSource.ADMISSION_INCREASE,
						operation_type=OrderOperationType.SIGNAL_ADMISSION,
						error_prefix="Signal rejected at admission",
					)
				# allow_increase=True falls through to entry sizing. The SELL-add books NO
				# admission-side reservation (the reserve gate is BUY-only; a SELL credits
				# cash), so the symmetric margin SOLVENCY check (step 3c in process_signal)
				# is what stops an UNFUNDED add — a CHECK, not a reservation.
				return None
			return None
		if self.portfolio_handler is None:
			# No position truth to consult — an unsized signal without a read model
			# fails loudly in the sizing step right after, as does "snap is None".
			return None
		portfolio_id = signal_event.portfolio_id
		open_position = snap
		# Dispatch on `side`, NOT the sign of net_quantity (an UNSIGNED magnitude — see
		# `_resolve_signal_quantity`): a `net_quantity > 0` predicate matches EVERY open
		# position and misclassifies an open SHORT as a long, rejecting a legitimate
		# BUY-to-cover as a disallowed increase.
		if open_position is not None and open_position.side is PositionSide.LONG:
			# INCREASE case: BUY for an already-open long.
			if not signal_event.allow_increase:
				return self._reject_unsized_signal(
					signal_event,
					f"position increase not allowed by strategy "
					f"(allow_increase=False) for {signal_event.ticker}",
					triggered_by=OrderTriggerSource.ADMISSION_INCREASE,
					operation_type=OrderOperationType.SIGNAL_ADMISSION,
					error_prefix="Signal rejected at admission",
				)
			return None
		if open_position is not None and open_position.side is PositionSide.SHORT:
			# BUY against an open short is a cover/exit — neither gate applies.
			return None
		# NEW-POSITION case (no open position, or a fully closed residual view):
		# enforce the declared concurrent-position cap.
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

	def _effective_leverage(self, signal_event: SignalEvent) -> Decimal:
		"""Resolve the effective leverage for an order.

		With ``enable_margin`` off the leverage is FORCED to ``Decimal("1")`` with NO
		instrument read — the helper never touches the Universe on the spot path. With it
		on, the effective leverage is the venue-realistic cap ``min(signal.leverage,
		Instrument.max_leverage, portfolio.max_leverage)``; the instrument cap degrades to
		``Decimal("1")`` when no Universe is wired. A requested leverage ABOVE the cap is
		CLAMPED and a warning logged — NOT rejected, NOT silent.
		"""
		if not self._enable_margin:
			return Decimal("1")
		instr_cap = (
			self._universe.instrument(signal_event.ticker).max_leverage
			if self._universe is not None else Decimal("1"))
		pf_cap = self._portfolio_max_leverage
		requested = signal_event.leverage
		capped = min(requested, instr_cap, pf_cap)
		if requested > capped:
			self.logger.warning(
				"leverage clamped to cap",
				requested=str(requested), capped=str(capped),
				ticker=signal_event.ticker)
		# Floor at 1: a misconfigured sub-1 cap would otherwise give a sub-1 effective
		# leverage and an inflated / divide-by-zero margin downstream (locked_margin =
		# notional / L leaks buying power as L → 0).
		if capped < Decimal("1"):
			self.logger.warning(
				"effective leverage floored to 1 (sub-1 cap)",
				capped=str(capped), ticker=signal_event.ticker)
			return Decimal("1")
		return capped

	def _enforce_leverage_admission(self, signal_event: SignalEvent) -> Optional[OperationResult]:
		"""Gate: a LeveredFraction(f>1) needs enable_margin.

		A ``LeveredFraction`` sizes notional as ``f x total_equity``, so ``f > 1`` opens
		more notional than equity and is fundable only with margin; with
		``enable_margin=False`` such a policy is REJECTED via the audited path. The gate is
		f>1-ONLY — ``f <= 1`` and any non-LeveredFraction policy pass untouched.

		Returns
		-------
		Optional[OperationResult]
			A failure_result when an f>1 LeveredFraction reaches admission with
			margin off (the audited REJECTED entity is already persisted), or
			None when the signal passes the gate.
		"""
		policy = signal_event.sizing_policy
		if (isinstance(policy, LeveredFraction)
				and policy.fraction > Decimal("1")
				and not self._enable_margin):
			return self._reject_unsized_signal(
				signal_event,
				f"leverage violation: LeveredFraction(fraction={policy.fraction}) "
				f"requires enable_margin (f > 1 opens notional above equity) "
				f"for {signal_event.ticker}",
				triggered_by=OrderTriggerSource.ADMISSION_LEVERAGE,
				operation_type=OrderOperationType.SIGNAL_ADMISSION,
				error_prefix="Signal rejected at admission",
			)
		return None

	def _resolve_signal_quantity(self, signal_event: SignalEvent,
	                             snap: "PositionView | None") -> "Decimal | OperationResult":
		"""Resolve the order quantity in the order/risk seam.

		The strategy DECLARES a SizingPolicy on the signal; the order/risk layer — never
		the strategy — resolves the per-portfolio quantity through the ONE SizingResolver.
		The resolved Decimal is RETURNED and flows native onto the Order entity; the signal
		is never mutated. Branch order is load-bearing for byte-exactness:

		* EXPLICIT: a caller-supplied positive quantity bypasses policy sizing entirely
		  (the explicit partial-exit path).
		* EXIT (an order opposing an open position): the resolver sizes the exit from the
		  position's net_quantity and the signal's exit_fraction. An exit_fraction of
		  ``Decimal("1")`` returns net_quantity structurally UNCHANGED — no multiplication
		  artifact — so the exit fully closes the position.
		* ENTRY (everything else): the resolver dispatches on signal.sizing_policy; the
		  FractionOfCash arm computes (fraction * available_cash) / to_money(price). A SELL
		  with no open long reaches this branch only for a LONG_SHORT direction (a
		  sanctioned short entry) — the direction gate rejects the LONG_ONLY case upstream.

		Sizing failures (invalid price, SizingPolicyViolation) are AUDITED rejections: the
		entity is built unsized, transitioned PENDING→REJECTED with
		triggered_by=SIZING_POLICY, and stored — rejected signals never vanish.

		Returns
		-------
		Decimal | OperationResult
			The resolved quantity, or a failure_result when sizing fails
			(the audited REJECTED entity is already persisted).
		"""
		if signal_event.quantity and signal_event.quantity > 0:
			return to_money(signal_event.quantity)

		price = signal_event.price
		if not price or price <= 0:
			return self._reject_unsized_signal(
				signal_event,
				f"Cannot size order: invalid signal price {price!r} for {signal_event.ticker}",
			)
		if self.portfolio_handler is None or self.sizing_resolver is None:
			# The run path always wires a read model before sizing; the typed failure
			# result makes a missing one explicit rather than sizing off nothing.
			return OperationResult.failure_result(
				f"Cannot size order: no portfolio read model available for {signal_event.ticker}",
				operation_type=OrderOperationType.CREATE_PRIMARY_ORDER
			)
		portfolio_id = signal_event.portfolio_id
		open_position = snap
		# Side-agnostic exit: a reduction is "the order action OPPOSES the open
		# position's side" — a SELL against an open LONG or a BUY-to-cover against an
		# open SHORT — and both route through the SAME resolve_exit. The predicate
		# dispatches on `side`, NOT the sign of net_quantity: ``PositionView`` carries
		# an UNSIGNED magnitude, so a short never presents net_quantity < 0 here and a
		# `SELL and net > 0` predicate would send a BUY-cover-on-short into entry
		# sizing, flipping the short book LONG. Clamp-to-flat is implicit: resolve_exit
		# returns AT MOST the full magnitude, so the excess can never auto-open a long
		# (Portfolio's over-close guard stays as defense-in-depth).
		is_reduction = open_position is not None and (
			(signal_event.action is Side.SELL and open_position.side is PositionSide.LONG)
			or (signal_event.action is Side.BUY and open_position.side is PositionSide.SHORT)
		)
		if is_reduction:
			assert open_position is not None  # narrowed by is_reduction
			return self.sizing_resolver.resolve_exit(
				abs(open_position.net_quantity),
				signal_event.exit_fraction,
				signal_event.sizing_policy.step_size,
			)
		# Entry (or a LONG_SHORT SELL with no open long — a sanctioned short entry).
		# Full Decimal precision rides through the intermediate — quantize ONLY via an
		# explicit policy step_size — and the Decimal rides the OrderEvent untouched,
		# with the exchange converting ONCE at its float matching boundary.
		try:
			return self.sizing_resolver.resolve_entry(
				signal_event.sizing_policy,
				portfolio_id,
				price,
				stop=signal_event.stop_loss or None,
			)
		except SizingPolicyViolation as e:
			# Fail loud: the violation becomes an audited REJECTED order, never a drop.
			return self._reject_unsized_signal(signal_event, str(e))

	def _reject_unsized_signal(self, signal_event: SignalEvent, reason: str, *,
	                           triggered_by: OrderTriggerSource = OrderTriggerSource.SIZING_POLICY,
	                           operation_type: OrderOperationType = OrderOperationType.SIGNAL_SIZING,
	                           error_prefix: str = "Signal sizing failed") -> OperationResult:
		"""Audited admission/sizing rejection.

		Build the primary Order entity UNSIZED (quantity 0), transition it
		PENDING→REJECTED through the audited add_state_change path — ``triggered_by``
		identifies the gate and the reason names the violation — and persist it, so
		rejected signals never vanish. The entity is REJECTED before validation ever runs,
		so the validator's positive-quantity rule is never consulted on it. Timestamps stay
		event-derived, never wall clock.
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
