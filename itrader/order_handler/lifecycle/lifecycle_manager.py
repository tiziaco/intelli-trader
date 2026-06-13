"""
Order-lifecycle collaborator (D-01 4th bucket; D-07/D-08/D-09/D-13, T-05-17,
RESEARCH Pattern 5).

`LifecycleManager` owns the modify/cancel verbs MOVED VERBATIM (TAB) from
`order_manager.py` (D-13, pure code-motion — byte-exact behavior): the two public
entry points `modify_order` / `cancel_order` (relocated INTACT, D-07).
`OrderManager.modify_order` / `cancel_order` become 1-line delegations, so the
public surface and external ctor stay byte-equal.

Both verbs behave exactly as before: modify validates the modification through the
injected validator, applies it, persists, and (WR-03 part 3) refreshes the
PercentFromFill pending quantity through the injected BracketBook when the quantity
changes; cancel applies the local terminal transition, disarms the pending bracket
(WR-03 part 1, BracketBook `consume`) and runs the idempotent reservation release
(WR-04, T-05-17 — a stuck BUY reservation corrupts buying power for the whole run).

The collaborator receives its dep subset by injection (D-09): `order_storage`,
`logger`, `order_validator`, `portfolio_handler` (read-model, for `release`), and
the coordinator-owned `BracketBook` (`self._brackets`, the single owner of the
pending-bracket map, D-05). It holds NO sibling reconcile/admission/lifecycle ref
(D-08). NO queue access (D-06/D-18) — the manager returns OperationResults/
OrderEvents and the handler performs all queue puts. Money is Decimal end-to-end
via `to_money` (NEVER `Decimal(float)`).
"""

from decimal import Decimal
from typing import Any, List, Optional

from ..operation_result import OperationResult
from ..base import OrderStorage
from ..order_validator import EnhancedOrderValidator
from ..brackets import BracketBook
from ...core.enums import OrderCommand, OrderOperationType
from ...core.ids import OrderId, PortfolioId
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel
from ...events_handler.events import OrderEvent


class LifecycleManager:
	"""
	Order-lifecycle verbs (D-01 4th bucket; D-07/D-08/D-13).

	Owns `modify_order` / `cancel_order` (the two public entry points
	OrderManager delegates into, D-07), moved verbatim from OrderManager. Holds
	the injected coordinator-owned BracketBook (`self._brackets`, D-05); never
	touches the events queue (D-18) and holds no sibling-collaborator ref (D-08).
	"""

	def __init__(self, order_storage: OrderStorage, logger: Any,
	             order_validator: Optional[EnhancedOrderValidator],
	             portfolio_handler: Optional[PortfolioReadModel],
	             brackets: BracketBook) -> None:
		self.order_storage = order_storage
		self.logger = logger
		self.order_validator = order_validator
		self.portfolio_handler = portfolio_handler
		# D-05: the coordinator-owned single bracket-map owner, injected.
		self._brackets = brackets

	def modify_order(self, order_id: OrderId, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[PortfolioId] = None, reason: str = "user modification") -> OperationResult:
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
					self._brackets.refresh_quantity(order.id, to_money(new_quantity))

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

	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None,
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
				self._brackets.consume(order.id)

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

	def expire_all_resting(self) -> List[OperationResult]:
		"""Sweep every active order to EXPIRED at run end (LIFE-01, D-08/D-10).

		The run-end time-in-force sweep — the peer of ``cancel_order`` (the body
		below mirrors it near-verbatim). Visits active portfolios in
		``active_portfolio_ids()`` order and, within each, orders sorted by
		``order_id`` (UUIDv7 stable sort, D-10 — deterministic). Per order it
		locally transitions PENDING -> EXPIRED, persists, disarms any pending
		bracket (WR-03 symmetry — no-ops at run end), idempotently releases the
		reservation (WR-04), and emits an ``OrderEvent(EXPIRE)`` carried on a
		successful ``OperationResult`` so the exchange clears the resting order
		through the queue (the sweep never touches ``_resting`` directly,
		T-06-05). The manager NEVER touches the queue (D-18): it returns the
		results; the handler enqueues each ``OrderEvent``.

		Returns
		-------
		List[OperationResult]
			One success result per swept order, each carrying exactly one
			OrderEvent with ``command == OrderCommand.EXPIRE``.
		"""
		results: List[OperationResult] = []
		if self.portfolio_handler is None:
			return results
		# WR-02: active_portfolio_ids() is part of the PortfolioReadModel
		# Protocol (D-13/D-16), so the run-end enumeration is type-checked and
		# contract-guaranteed — no concrete-handler coupling via a type: ignore.
		# Returning ids (not live Portfolio objects) keeps the order domain on
		# the narrow read boundary.
		for portfolio_id in self.portfolio_handler.active_portfolio_ids():
			# D-10: UUIDv7 stable sort => deterministic per-portfolio sweep order.
			for order in sorted(
					self.order_storage.get_active_orders(portfolio_id),
					key=lambda o: o.id):
				try:
					# Local terminal transition (peer of cancel_order's
					# order.cancel_order). Skip orders that refuse the transition.
					if not order.expire_order("run end (time-in-force)"):
						continue
					self.order_storage.update_order(order)
					# WR-03 (part 1): disarm any pending PercentFromFill bracket —
					# symmetric with cancel_order; a no-op at run end for ordinary
					# orders.
					self._brackets.consume(order.id)
					# WR-04: the local terminal transition owns the idempotent
					# release (a stuck BUY reservation corrupts buying power).
					if self.portfolio_handler is not None:
						self.portfolio_handler.release(
							order.portfolio_id, order.id)
					# OrderEvent(EXPIRE) — the exchange clears the resting order.
					order_event = OrderEvent.new_order_event(order, command=OrderCommand.EXPIRE)
					results.append(OperationResult.success_result(
						f"Order {order.id} expired at run end",
						order_events=[order_event],
						operation_type=OrderOperationType.EXPIRE_ORDER,
						affected_order_ids=[order.id]))
				except Exception as e:
					# WR-03: fail-fast on the backtest run-end sweep (CLAUDE.md
					# "Backtest error policy is fail-fast"). A mid-sweep failure
					# leaves a half-swept book — some orders EXPIRED with released
					# reservations, others left PENDING with stuck reservations —
					# so we re-raise to abort the run rather than completing it
					# "successfully" with corrupted run-end state. This mirrors the
					# deliberate fail-fast re-raise on the reconcile path
					# (reconcile_manager.py) at the same correctness-critical seam;
					# the dropped-failure_result path that OrderHandler.expire_all_resting
					# never inspected is removed entirely. (The only caller is the
					# backtest run-end bookend, backtest_runner.py.)
					self.logger.error(
						f"Error expiring order {order.id}: {e}", exc_info=True)
					raise
		return results
