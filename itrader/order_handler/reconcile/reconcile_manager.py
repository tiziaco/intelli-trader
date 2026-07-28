"""
Fill-reconciliation collaborator: `ReconcileManager.on_fill` reconciles the order
mirror against exchange-truth fills.

`on_fill` makes two cross-collaborator calls, both wired with NO sibling ref:
- the orphaned-child cancel routes through a `cancel_order` **coordinator
  callback** (`self._cancel_order`) that forwards to `OrderManager.cancel_order`,
  so ReconcileManager holds no lifecycle-manager ref and there is no circular
  import;
- the fill-anchored PercentFromFill children are created via the injected
  coordinator-owned `BracketManager` (`self.bracket_manager`). The
  `BracketManager` type is imported only under `TYPE_CHECKING`; this keeps the
  annotation NAME off the module's runtime name bindings only — it does NOT avoid
  loading the class, which the runtime `from ..brackets import BracketBook` import
  already pulls in transitively (harmless — no import cycle).

`self._brackets` is the single owner of the pending-bracket map. NO queue access
— the manager returns OrderEvents and the handler performs all queue puts. Money
is Decimal end-to-end via `to_money` (NEVER `Decimal(float)`).
"""

from collections import OrderedDict
from typing import Any, Callable, Iterable, List, Optional, TYPE_CHECKING

from ..operation_result import OperationResult
from ..base import OrderStorage
from ..brackets import BracketBook
from ...core.enums import FillStatus, OrderStatus
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel
from ...events_handler.events import OrderEvent, FillEvent

if TYPE_CHECKING:
	from ..brackets import BracketManager
	from ..order import Order


# In-session applied-trade dedup ring capacity, mirroring the
# `venue_correlation.py::_DEDUP_RING_CAPACITY` precedent — 10 000 >> a realistic
# reconnect / restart re-send burst, and bounded (not an unbounded set) so a long
# live session cannot grow it without limit.
_APPLIED_TRADE_RING_CAPACITY = 10000


class ReconcileManager:
	"""
	Fill-reconciliation verb.

	Owns `on_fill`, the public entry point OrderManager delegates into. Holds the
	injected coordinator-owned BracketBook (`self._brackets`) and BracketManager
	(`self.bracket_manager`); routes the orphaned-child cancel through the injected
	`cancel_order` coordinator callback (`self._cancel_order`) so no
	lifecycle-manager sibling ref — and therefore no circular import — is needed.
	Never touches the events queue.
	"""

	def __init__(self, order_storage: OrderStorage, logger: Any,
	             portfolio_handler: Optional[PortfolioReadModel],
	             brackets: BracketBook,
	             bracket_manager: "BracketManager",
	             cancel_order: Callable[..., OperationResult]) -> None:
		self.order_storage = order_storage
		self.logger = logger
		self.portfolio_handler = portfolio_handler
		self._brackets = brackets
		self.bracket_manager = bracket_manager
		self._cancel_order = cancel_order
		# In-session per-trade applied-set guarding _apply_executed against a
		# re-delivered venue trade. Two live emitters (the OKX trade stream and the
		# restart VenueReconciler) can book the SAME economic venue trade; they share
		# only the venue tradeId (fill_id is a fresh uuid7 per emit), so the key is
		# f"{ticker}:{venue_trade_id}" — ticker-scoped so two symbols sharing a
		# numeric tradeId do not alias onto one another.
		self._applied_capacity = _APPLIED_TRADE_RING_CAPACITY
		self._applied_trade_keys: "OrderedDict[str, None]" = OrderedDict()

	def _record_applied_trade(self, dedup_key: Optional[str]) -> None:
		"""Record a successfully-applied venue-trade key in the bounded FIFO ring.

		Past capacity the oldest key is evicted, so the ring cannot grow unboundedly
		in a long live session.
		"""
		if dedup_key is None:
			return
		if dedup_key in self._applied_trade_keys:
			return
		if self._applied_capacity > 0 and len(self._applied_trade_keys) >= self._applied_capacity:
			self._applied_trade_keys.popitem(last=False)
		self._applied_trade_keys[dedup_key] = None

	def seed_applied_trades(self, keys: Iterable[str]) -> None:
		"""Restart-seed the dedup ring from the durable settled-trade history.

		On a live restart ``_applied_trade_keys`` starts EMPTY, so the in-session
		guard does not cover a venue trade re-delivered AFTER the restart (an OKX
		stream re-send, or the ``VenueReconciler`` adopting a downtime fill). Driven
		FROM ``PortfolioHandler.rehydrate`` — the only place already reading the
		durable ``transactions.venue_trade_id`` history, since ReconcileManager has no
		durable transaction store — with the SAME ``f"{ticker}:{venue_trade_id}"``
		keys the portfolio ledger seeds ``_settled_venue_trade_ids`` from, so the
		order-mirror arm and the portfolio arm survive a restart SYMMETRICALLY.
		LIVE-ONLY: the in-memory backtest backend has no durable transactions and
		never rehydrates, so the sink is never called.
		"""
		for key in keys:
			self._record_applied_trade(key)

	@staticmethod
	def _classify(status: FillStatus) -> "tuple[bool, Optional[OrderStatus]]":
		"""
		Name the exchange-truth fill status -> order-mirror transition mapping
		and its terminal-ness, for READABILITY only.

		A pure naming aid: it does NOT drive the mirror transition (the per-status
		arms call ``order.add_fill``/``cancel_order``/``reject_order`` directly). The
		non-terminal ``(False, None)`` case stays an early-return INSIDE ``on_fill``
		so the reservation is intentionally HELD — pushing that early-return into
		this helper would arm ``should_release``.

		DUAL-EDIT REQUIREMENT: the terminal-status vocabulary is encoded in TWO
		places — this mapping and the per-status ``if``/``elif`` dispatch in
		``on_fill``. Adding a terminal ``FillStatus`` requires editing BOTH; a missed
		dispatch arm is caught loud at runtime by the ``else: raise
		NotImplementedError`` fallthrough there.
		"""
		if status == FillStatus.EXECUTED:
			return True, OrderStatus.FILLED
		if status == FillStatus.CANCELLED:
			return True, OrderStatus.CANCELLED
		if status == FillStatus.REFUSED:
			return True, OrderStatus.REJECTED
		if status == FillStatus.EXPIRED:
			return True, OrderStatus.EXPIRED
		return False, None

	def _apply_executed(self, order: "Order", fill_event: FillEvent,
	                    order_id: Any) -> "tuple[bool, bool]":
		"""
		EXECUTED arm: apply an exchange fill increment to the order mirror.

		Live venues deliver PARTIAL fills; the mirror accumulates each increment
		against cumulative-filled and terminalizes to FILLED only when the fill
		covers the entire remaining quantity (the full-quantity ``add_fill``
		contract). A shortfall stays OPEN at PARTIALLY_FILLED — the order keeps
		working, its reservation is HELD, and no engine-imposed timeout ages it
		out (aging is a strategy concern, not an engine one).

		Returns ``(applied, terminalized)``:
		- ``applied``      — ``True`` when the mirror moved. On a rejected mirror
		                     update the caller must NOT early-return: the portfolio
		                     already settled this fill (FILL dispatches
		                     portfolio-first), so a terminal fill's uniform release
		                     must still run or the BUY's reservation is stuck
		                     forever.
		- ``terminalized`` — ``True`` only when THIS fill completed the order
		                     (-> FILLED). ``False`` when the order stayed open
		                     (a partial) so the caller HOLDS the reservation
		                     and SKIPS the terminal-only bracket post-processing.
		"""
		# In-session dedup: a re-delivered venue trade (same venue_trade_id, fresh
		# fill_id) must be a no-op so the mirror never double-books. A None
		# venue_trade_id (backtest / simulated fill) skips the guard entirely.
		venue_trade_id = getattr(fill_event, "venue_trade_id", None)
		dedup_key = (f"{fill_event.ticker}:{venue_trade_id}"
		             if venue_trade_id is not None else None)
		if dedup_key is not None and dedup_key in self._applied_trade_keys:
			# Re-delivered venue trade: no accumulation, no release, no bracket
			# post-processing — the reservation stays HELD.
			self.logger.warning(
				'Dedup: venue trade %s for order %s already applied; increment ignored',
				dedup_key, order_id)
			return False, False
		# fill_event.price/quantity are already Decimal — to_money is an identity
		# normalization at this domain entry (the mirror never trusts an
		# unnormalized money input).
		increment = to_money(fill_event.quantity)
		fill_price = to_money(fill_event.price)
		# COMMON PATH, tried FIRST: a fill covering the ENTIRE remaining quantity
		# completes the order via the full-quantity add_fill contract -> FILLED.
		# Attempting add_fill before inspecting order state keeps any mirror whose
		# add_fill simply succeeds untouched — the state inspection below runs ONLY
		# when add_fill rejects.
		if order.add_fill(increment, fill_price, fill_event.time, "exchange fill"):
			self._record_applied_trade(dedup_key)
			return True, True
		# add_fill REJECTED the increment. Distinguish three outcomes:
		if not order.is_active:
			# An EXECUTED fill for an ALREADY-TERMINAL mirror (e.g. locally
			# CANCELLED before the exchange ack) can never move the order — but the
			# portfolio already settled the fill (FILL dispatches portfolio-first),
			# so this is still a TERMINAL reconciliation whose uniform release MUST
			# run or the reservation is stuck forever: rejected mirror, but
			# terminalized -> release.
			self.logger.warning(
				'add_fill rejected for order %s (mirror already terminal); left unchanged', order_id)
			return False, True
		# The order is ACTIVE, so add_fill rejected at its full-quantity guard
		# WITHOUT mutating filled_quantity — the remaining quantity is accurate.
		remaining = order.remaining_quantity
		if 0 < increment < remaining:
			# Partial fill: a strict shortfall against the remaining leaves the order
			# OPEN at PARTIALLY_FILLED — accumulate the increment, HOLD the
			# reservation, impose NO timeout. add_fill did not mutate, so this does
			# not double-count.
			#
			# Validate the transition BEFORE mutating filled_quantity: compute the
			# prospective total WITHOUT assigning it yet, so a rejected transition
			# leaves the mirror literally unchanged (the "mirror left unchanged"
			# contract logged below).
			new_filled = to_money(order.filled_quantity + increment)
			additional_data = {
				"fill_quantity": increment,
				"fill_price": fill_price,
				"fill_time": fill_event.time.isoformat() if fill_event.time is not None else None,
				"total_filled": new_filled,
			}
			# allow_same_status so a SECOND partial (PARTIALLY_FILLED ->
			# PARTIALLY_FILLED) records without tripping the transition validator;
			# a first partial (PENDING -> PARTIALLY_FILLED) is a normal transition.
			if not order.add_state_change(
					OrderStatus.PARTIALLY_FILLED, "exchange partial fill",
					additional_data=additional_data, time=fill_event.time,
					allow_same_status=True):
				self.logger.warning(
					'Partial-fill transition rejected for order %s; mirror left unchanged', order_id)
				return False, False
			order.filled_quantity = new_filled
			self._record_applied_trade(dedup_key)
			return True, False
		# Over-fill (increment > remaining) or non-positive increment on an ACTIVE
		# order: reject-and-log — never crash, and never terminalize on a bad fill.
		# The mirror is left unchanged and the reservation HELD.
		self.logger.warning(
			'Rejected fill for order %s: increment %s not in (0, remaining %s]; mirror left unchanged',
			order_id, increment, remaining)
		return False, False

	@staticmethod
	def _apply_cancelled(order: "Order") -> None:
		order.cancel_order("exchange cancellation")

	@staticmethod
	def _apply_refused(order: "Order") -> None:
		order.reject_order("exchange rejection")

	@staticmethod
	def _apply_expired(order: "Order") -> None:
		"""EXPIRED arm: mark the order EXPIRED (exchange expiration).

		LANDMINE: NO custom already-EXPIRED guard. When the run-end sweep already
		transitioned the mirror locally to EXPIRED, ``expire_order`` here is a
		silent no-op — ``add_state_change`` returns False on the invalid
		EXPIRED->EXPIRED transition (``core/enums/order.py::VALID_ORDER_TRANSITIONS``
		maps EXPIRED to an empty list), so idempotency is FREE without a guard. The
		terminal release still runs in the ``finally``; the second release is
		idempotent (pops nothing)."""
		order.expire_order("exchange expiration")

	def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]:
		"""
		Reconcile the order mirror against an exchange fill.

		EXECUTED -> mark the order FILLED; CANCELLED -> mark CANCELLED;
		REFUSED -> mark REJECTED. The terminal status change alone moves the
		order out of active queries ("active" is an entity predicate, not a
		container) — the order stays in storage for the audit trail.

		The ``try``/``finally`` skeleton below is load-bearing: a sequential
		``apply(); release()`` state machine is the REJECTED alternative, because it
		reintroduces the skip-release-on-raise bug.

		Returns
		-------
		List[OrderEvent]
			CANCEL OrderEvents for bracket children orphaned by a parent that
			reached a terminal state without any fill, CANCEL OrderEvents for
			bracket children orphaned when an EXECUTED fill FLATTENED their
			portfolio+ticker position, plus the fill-anchored PercentFromFill
			children created on the parent's EXECUTED fill. The manager never
			touches the queue — the handler enqueues these.
		"""
		out_events: List[OrderEvent] = []
		order_id = getattr(fill_event, 'order_id', None)
		if order_id is None:
			return out_events
		order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
		if order is None:
			return out_events
		# The terminal release MUST run even if the reconciliation body raises — a
		# stuck BUY reservation corrupts buying power for the rest of the run — so it
		# lives in a `finally`, gated by this flag so the early-return "unknown
		# status" path (which intentionally holds the reservation) does not trigger
		# it. The body is re-raised after logging (backtest fail-fast, matching the
		# portfolio side of the same FILL under FailFastPolicy) so a corrupted
		# reconciliation aborts the run instead of producing silently-wrong numbers.
		should_release = False
		body_raised = False
		try:
			applied = True
			# CANCELLED/REFUSED/EXPIRED terminalize unconditionally; an EXECUTED fill
			# overrides this below — a PARTIAL leaves the order OPEN
			# (PARTIALLY_FILLED), so it is NOT terminal and the reservation is HELD.
			# ``terminalized``, not the fill-status classification, drives
			# ``should_release`` and the terminal-only bracket work.
			terminalized = True
			terminal, _transition = self._classify(fill_event.status)
			if not terminal:
				# Unknown / non-terminal status: leave the order active and alert.
				# This early-return stays HERE rather than inside ``_classify`` so
				# ``should_release`` is never armed — an unknown status is not a
				# terminal reconciliation, so the reservation is intentionally held.
				self.logger.warning('Unhandled fill status %s for order %s; order left active',
				                    fill_event.status, order_id)
				return out_events
			if fill_event.status == FillStatus.EXECUTED:
				applied, terminalized = self._apply_executed(order, fill_event, order_id)
			elif fill_event.status == FillStatus.CANCELLED:
				self._apply_cancelled(order)
			elif fill_event.status == FillStatus.REFUSED:
				self._apply_refused(order)
			elif fill_event.status == FillStatus.EXPIRED:
				self._apply_expired(order)
			else:
				# _classify marked this status terminal but no arm dispatches it (a
				# future FillStatus added to _classify without a matching arm here).
				# Fail loud BEFORE should_release is armed so the reservation stays
				# held — never silently mis-reconcile as REFUSED.
				raise NotImplementedError(
					f'terminal fill status {fill_event.status!r} has no reconcile arm')
			# Arm the release only when THIS fill terminalized the order, but arm it
			# BEFORE the update/bracket work below so a raise there still releases a
			# TERMINAL fill's reservation.
			should_release = terminalized
			# Persist whenever the mirror moved — for a terminal fill and for an
			# accumulating partial alike; the store's cumulative-filled is the restart
			# cross-check. No deactivate step: a terminal status already removes the
			# order from active queries via is_active.
			if applied:
				self.order_storage.update_order(order)
			# A parent that reaches a terminal state WITHOUT any fill
			# (REFUSED/CANCELLED) leaves its protective SL/TP children resting on the
			# exchange with no position to protect — when price later crosses them
			# they would fill against a flat portfolio. Cancel the children locally
			# and return their CANCEL OrderEvents so the exchange removes the resting
			# orders too.
			if (fill_event.status in (FillStatus.CANCELLED, FillStatus.REFUSED)
					and order.child_order_ids and order.filled_quantity == 0):
				for child_id in order.child_order_ids:
					child_result = self._cancel_order(
						child_id, order.portfolio_id,
						reason=f"parent order {order.id} terminal without fill")
					if child_result.success and child_result.order_events:
						out_events.extend(child_result.order_events)
			# PercentFromFill: the parent's EXECUTED fill is the moment its
			# policy-declared children come into existence — created, stored, linked
			# and emitted priced from the ACTUAL fill (IB attached-order semantics).
			# A parent that terminates WITHOUT executing (CANCELLED/REJECTED) discards
			# its pending entry: the children were never created, so no orphan can
			# exist and the cancel-children branch above is untouched.
			if fill_event.status == FillStatus.EXECUTED and terminalized:
				# Only a TERMINAL (fully-filled) EXECUTED fill consumes the pending
				# bracket, mints the fill-anchored children and runs the flatten
				# sweep. A PARTIAL leaves the parent working, so the bracket stays
				# PENDING for the completing fill — no premature child creation, no
				# bracket discard.
				pending = self._brackets.consume(order_id)
				# Only anchor children when the mirror actually applied the fill: if
				# add_fill was rejected (applied=False) the parent never moved, so
				# creating fill-anchored children would link live SL/TP to a parent
				# the engine still considers unfilled.
				if pending is not None and applied:
					out_events.extend(
						self.bracket_manager._create_fill_anchored_children(order, pending, fill_event))
				# When an EXECUTED fill FLATTENS the (portfolio, ticker) position,
				# cancel that portfolio+ticker's resting bracket children. Without
				# this, a discretionary market SELL flattens a bracketed long but the
				# matching engine's OCO only cancels a bracket's OWN sibling, so the
				# orphaned SL/TP survive and fire later as a SELL fill against a flat
				# portfolio, bypassing admission and silently over-selling. DISTINCT
				# from the cancel-children branch above (a PARENT that terminated
				# WITHOUT any fill); here a SEPARATE order's EXECUTED fill closed the
				# position. Stays in the ORDER domain: reads the portfolio ONLY
				# through the injected read-model and cancels ONLY through the
				# injected coordinator callback — no cross-domain reach.
				if self.portfolio_handler is not None:
					view = self.portfolio_handler.get_position(
						fill_event.portfolio_id, fill_event.ticker)
					if view is None:  # the fill closed the position — now FLAT
						for active in self.order_storage.get_active_orders(fill_event.portfolio_id):
							if (active.ticker == fill_event.ticker
									and active.parent_order_id is not None
									and active.id != order.id):
								child_result = self._cancel_order(
									active.id, fill_event.portfolio_id,
									reason=f"position {fill_event.ticker} flattened by fill {order.id}")
								if child_result.success and child_result.order_events:
									out_events.extend(child_result.order_events)
			elif fill_event.status != FillStatus.EXECUTED:
				# A terminal NON-executing outcome (CANCELLED/REFUSED/EXPIRED)
				# discards the pending bracket — its children were never created.
				# A PARTIAL EXECUTED fill (EXECUTED but not terminalized) falls
				# through NEITHER branch, so the bracket stays PENDING for the
				# completing fill and is never prematurely discarded.
				self._brackets.consume(order_id)
		except Exception as e:
			# Log with a stack trace and RE-RAISE — backtest fail-fast. A
			# reconciliation that cannot complete leaves the mirror and/or
			# reservation inconsistent; continuing would produce silently-wrong
			# numbers. The portfolio side of the same FILL is fail-fast under
			# FailFastPolicy, so the order side matches. The `finally` below still
			# releases a terminal fill's reservation before the exception
			# propagates.
			self.logger.error('Error reconciling fill for order %s: %s',
			                  order_id, e, exc_info=True)
			body_raised = True
			raise
		finally:
			self._release_reservation(order, should_release, body_raised)
		return out_events

	def _release_reservation(self, order: "Order", should_release: bool, body_raised: bool) -> None:
		"""Idempotent terminal-release of the order's cash reservation."""
		# A terminal fill ALWAYS releases its reservation, even when the
		# reconciliation body raised after the terminal status was set — a stuck
		# reservation corrupts buying power for the whole run. `should_release` is
		# False on the non-terminal early-return path, which intentionally holds
		# the reservation. The release is idempotent — never-reserved orders
		# (SELLs, children) silently no-op.
		if should_release and self.portfolio_handler is not None:
			try:
				self.portfolio_handler.release(
					order.portfolio_id, order.id)
			except Exception:
				# Distinguish "body raised" from "release raised". If the body
				# already raised, that ORIGINAL exception is the one propagating out
				# of the finally — re-raising the release failure here would mask it,
				# so only log. But if the body succeeded and the release itself
				# fails, a silently-unreleased reservation is exactly the
				# buying-power corruption this guard exists for, so it must reach the
				# fail-fast seam.
				self.logger.error(
					'Failed to release reservation for order %s during fill reconciliation',
					order.id, exc_info=True)
				if not body_raised:
					raise
