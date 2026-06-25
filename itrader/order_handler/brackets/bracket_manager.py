"""
Bracket assembly collaborator (D-04/D-08/D-13, T-07-15, RESEARCH Pattern 5).

`BracketManager` owns the create-all-then-emit bracket assembly
(`_assemble_bracket_and_emit`) and the fill-anchored PercentFromFill child
creation (`_create_fill_anchored_children`), both MOVED VERBATIM (TAB) from
`order_manager.py` (D-13, pure code-motion — byte-exact behavior).

D-04 SLTP precedence is preserved exactly: explicit stop_loss/take_profit levels
WIN; only a level-less signal consults the declared sltp_policy. PercentFromFill
is the CARVE-OUT to create-all-then-emit (D-11) — its children are armed on the
BracketBook at assembly and created from the ACTUAL fill in
`_create_fill_anchored_children` (IB attached-order semantics, Pattern 5 Option B;
T-07-15 — no orphan possible, the children never exist until the parent EXECUTES).

The collaborator receives its dep subset by injection (D-09): `order_storage`,
`logger`, and the coordinator-owned `BracketBook` (the single owner of the
pending-bracket map, D-05). The stateless `_bracket_levels` ± pct helper is
imported from `.levels` (D-08) so neither admission nor reconcile needs a
brackets-collaborator ref. NO queue access (D-06/D-18) — the manager returns
OperationResults/OrderEvents and the handler performs all queue puts.
Money is Decimal end-to-end via `to_money` (NEVER `Decimal(float)`).
"""

from decimal import Decimal
from typing import Any, List, Optional, assert_never

from ..order import Order
from ..operation_result import OperationResult
from ...core.enums import OrderOperationType, Side
from ...core.exceptions import SizingPolicyViolation
from ...core.money import to_money
from ...core.sizing import PercentFromDecision, PercentFromFill
from ...events_handler.events import OrderEvent, SignalEvent, FillEvent
from .bracket_book import BracketBook, _PendingBracket
from .levels import _bracket_levels


class BracketManager:
	"""
	Bracket assembly + SLTP child creation (D-04/D-08/D-13).

	Owns the create-all-then-emit bracket assembly and the fill-anchored
	PercentFromFill child creation moved verbatim from OrderManager. Holds the
	injected coordinator-owned BracketBook (D-05) as `self._brackets`; never
	touches the events queue (D-18).
	"""

	def __init__(self, order_storage: Any, logger: Any, brackets: BracketBook) -> None:
		self.order_storage = order_storage
		self.logger = logger
		# D-05: the coordinator-owned single bracket-map owner, injected.
		self._brackets = brackets

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
						sl_price, tp_price = _bracket_levels(
							sltp_policy, to_money(signal_event.price),
							signal_event.action)
					case PercentFromFill():
						# CARVE-OUT to create-all-then-emit (Phase 4 D-11):
						# NO children at assembly — record the pending bracket;
						# on_fill creates them priced from the actual fill
						# (IB attached-order semantics, Pattern 5 Option B).
						# TRAIL-01/TRAIL-02 (D-TRAIL-3/D-TRAIL-5): a trailing
						# PercentFromFill carries trail_type/trail_value, which
						# survive the arm->fill round-trip so the SL child can be
						# declared as a TRAILING_STOP seeded from the entry fill
						# (a trailing SL has no static price at declaration, so it
						# rides the fill-anchored carve-out naturally).
						self._brackets.arm(primary.id, _PendingBracket(
							policy=sltp_policy,
							ticker=signal_event.ticker,
							action=signal_event.action,
							quantity=quantity,
							exchange=exchange,
							strategy_id=signal_event.strategy_id,
							portfolio_id=signal_event.portfolio_id,
							trail_type=sltp_policy.trail_type,
							trail_value=sltp_policy.trail_value,
						))
					case _:
						assert_never(sltp_policy)

			if sl_price > 0:
				sl_order = Order.new_stop_order(
					time=signal_event.time,
					ticker=signal_event.ticker,
					# Invert on Side (D-05); the entity stores a Side (SIG-03/D-03).
					action=Side.BUY if signal_event.action is Side.SELL else Side.SELL,
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
					# Invert on Side (D-05); the entity stores a Side (SIG-03/D-03).
					action=Side.BUY if signal_event.action is Side.SELL else Side.SELL,
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
				results.append(OperationResult.success_result(
					f"Stop-loss order created: {sl_order.ticker} at {sl_order.price}",
					order_events=[OrderEvent.new_order_event(sl_order)],
					operation_type=OrderOperationType.CREATE_STOP_LOSS,
					affected_order_ids=[sl_order.id]
				))

			if tp_order is not None:
				results.append(OperationResult.success_result(
					f"Take-profit order created: {tp_order.ticker} at {tp_order.price}",
					order_events=[OrderEvent.new_order_event(tp_order)],
					operation_type=OrderOperationType.CREATE_TAKE_PROFIT,
					affected_order_ids=[tp_order.id]
				))

		except Exception as e:
			# WR-03 (part 2): the PercentFromFill pending entry is registered at
			# assembly time (above) BEFORE add_order runs. If storage raises
			# afterwards the primary never reaches the exchange, so no fill will
			# ever consume the pending entry — disarm it here so a stale entry
			# cannot later anchor children to a parent that was never emitted.
			self._brackets.consume(primary.id)
			self.logger.error(f'Error creating orders from signal: {e}', exc_info=True)
			results.append(OperationResult.failure_result(
				f"Failed to create orders from signal",
				error_details=str(e),
				operation_type=OrderOperationType.CREATE_ORDERS_FROM_SIGNAL
			))

		return results

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
		sl_price, tp_price = _bracket_levels(pending.policy, anchor, pending.action)
		# Invert on the parent's action (D-05); the entity stores a Side (SIG-03/D-03).
		child_action = Side.BUY if pending.action is Side.SELL else Side.SELL
		if pending.trail_type is not None and pending.trail_value is not None:
			# CR-01 / D-TRAIL-7 (PRICE case): the absolute trail viability gate is
			# only knowable HERE, at the fill, against the resolved anchor — it is
			# bypassed by the validator (which never runs on this fill-anchored
			# child). A PRICE trail >= anchor would seed a NON-POSITIVE stop
			# (anchor - trail <= 0 for a long; mirrored for a short) that can never
			# trigger, silently resting an unprotected position. Reject fail-loud
			# (backtest fail-fast: the reconcile caller logs + re-raises) instead of
			# resting a dead stop. The PERCENT case is bounded earlier at policy
			# construction (WR-02); only PRICE needs the fill-time anchor check.
			# TrailType is imported lazily (config-enum exception — keep the
			# order/core -> config dependency direction off the module load path).
			from ...config import TrailType
			if pending.trail_type == TrailType.PRICE and pending.trail_value >= anchor:
				raise SizingPolicyViolation(
					f"PercentFromFill PRICE trail_value {pending.trail_value} must be "
					f"< the entry-fill anchor {anchor}: a non-viable absolute trail "
					f"would seed a non-positive stop that can never trigger "
					f"(parent {parent.id})"
				)
			# TRAIL-01/TRAIL-02 (D-TRAIL-3/D-TRAIL-5): the SL leg is a
			# TRAILING_STOP, not a fixed STOP. Its `price` is the ENTRY FILL
			# anchor (the SAME value MatchingEngine._seed_trail reads as the
			# HWM/LWM seed — 05-02 confirmed order.price is the reference/anchor,
			# NOT the initial stop). The engine computes the initial stop from
			# the anchor and trail_value on submit (Pitfall 6: the anchor is a
			# positive price, so BOTH dual-layer validators' positive-price gate
			# passes; D-TRAIL-7 gates trail_value < anchor for the PRICE type).
			# D-TRAIL-5 EITHER/OR: the trailing SL REPLACES the fixed STOP leg;
			# the TP-limit leg below is unchanged.
			sl_order = Order.new_trailing_stop_order(
				time=fill_event.time,
				ticker=pending.ticker,
				action=child_action,
				price=anchor,
				quantity=pending.quantity,
				exchange=pending.exchange,
				strategy_id=pending.strategy_id,
				portfolio_id=pending.portfolio_id,
				trail_type=pending.trail_type,
				trail_value=pending.trail_value,
			)
		else:
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
