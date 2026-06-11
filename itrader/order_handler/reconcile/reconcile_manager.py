"""
Fill-reconciliation collaborator (D-01 5th bucket; D-07/D-08/D-09/D-13, T-05-17,
WR-03/WR-04, RESEARCH Pattern 5) — the FRAGILE, LAST extraction.

`ReconcileManager` owns `on_fill` MOVED VERBATIM (TAB) from `order_manager.py`
(D-13, pure code-motion — byte-exact behavior) as ONE indivisible intact unit
(D-07, criterion 2). The `should_release`/`try`/`finally`/release-in-finally
interplay (T-05-17, WR-03/WR-04) is byte-for-byte unchanged: `should_release`
is armed AFTER the terminal status and BEFORE further work so a later raise still
releases; the non-terminal unknown-status early-return intentionally holds the
reservation; the `finally` runs the idempotent reservation `release`; and the
inner release-failure `except` re-raises ONLY when the body did not already raise
(WR-03 — never mask the original exception). `OrderManager.on_fill` becomes a
1-line delegation, so the public surface and external ctor stay byte-equal.

`on_fill` makes two cross-bucket calls that become cross-collaborator seams after
the move. Per D-08 (no stateful sibling edges) and D-04 (coordinator-owned star)
they are wired with NO sibling-collaborator ref:
- the WR-05 orphaned-child cancel routes through a `cancel_order` **coordinator
  callback** (`self._cancel_order`) that forwards to `OrderManager.cancel_order`
  (the plan-04 lifecycle delegation) — ReconcileManager holds NO lifecycle-manager
  sibling ref, so there is no circular import;
- the fill-anchored PercentFromFill children are created via the injected
  coordinator-owned `BracketManager` (`self.bracket_manager`) — ReconcileManager
  holds no BracketManager *as a sibling edge* beyond that injected object (the
  type is imported only under `TYPE_CHECKING`).

The collaborator receives its dep subset by injection (D-09): `order_storage`,
`logger`, `portfolio_handler` (read-model, for `release`), the coordinator-owned
`BracketBook` (`self._brackets`, the single owner of the pending-bracket map,
D-05), the coordinator-owned `BracketManager` (`self.bracket_manager`), and the
`cancel_order` coordinator callback (`self._cancel_order`). NO queue access
(D-06/D-18) — the manager returns OrderEvents and the handler performs all queue
puts. Money is Decimal end-to-end via `to_money` (NEVER `Decimal(float)`).
"""

from typing import Any, Callable, List, Optional, TYPE_CHECKING

from ..operation_result import OperationResult
from ..base import OrderStorage
from ..brackets import BracketBook
from ...core.enums import FillStatus
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel
from ...events_handler.events import OrderEvent, FillEvent

if TYPE_CHECKING:
	from ..brackets import BracketManager


class ReconcileManager:
	"""
	Fill-reconciliation verb (D-01 5th bucket; D-07/D-08/D-13 — FRAGILE).

	Owns `on_fill` (the public entry point OrderManager delegates into, D-07),
	moved verbatim from OrderManager as one indivisible unit. Holds the injected
	coordinator-owned BracketBook (`self._brackets`, D-05) and BracketManager
	(`self.bracket_manager`); routes the WR-05 orphaned-child cancel through the
	injected `cancel_order` coordinator callback (`self._cancel_order`, D-04 star —
	no lifecycle-manager sibling ref, no circular import). Never touches the events queue
	(D-18) and holds no direct sibling-manager edge (D-08).
	"""

	def __init__(self, order_storage: OrderStorage, logger: Any,
	             portfolio_handler: Optional[PortfolioReadModel],
	             brackets: BracketBook,
	             bracket_manager: "BracketManager",
	             cancel_order: Callable[..., OperationResult]) -> None:
		self.order_storage = order_storage
		self.logger = logger
		self.portfolio_handler = portfolio_handler
		# D-05: the coordinator-owned single bracket-map owner, injected.
		self._brackets = brackets
		# D-04 star: the coordinator-owned BracketManager (for the fill-anchored
		# PercentFromFill children) — injected, not a sibling import.
		self.bracket_manager = bracket_manager
		# D-04 star: the cancel coordinator callback — forwards to
		# OrderManager.cancel_order (the plan-04 lifecycle delegation), so the
		# WR-05 orphaned-child cancel reaches lifecycle WITHOUT a direct
		# lifecycle-manager sibling ref (no circular import).
		self._cancel_order = cancel_order

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
		body_raised = False
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
					# D-12: cancel_order now declares OrderId/PortfolioId; child_id
					# is an OrderId and order.portfolio_id a PortfolioId, so the
					# prior cast(int, ...) bridge (IN-06) is gone.
					child_result = self._cancel_order(
						child_id, order.portfolio_id,
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
				pending = self._brackets.consume(order_id)
				# WR-03 (part 1): only anchor children when the mirror actually
				# applied the fill. If add_fill was rejected (applied=False) the
				# parent never moved, so creating fill-anchored children would
				# link live SL/TP to a parent the engine still considers unfilled.
				if pending is not None and applied:
					out_events.extend(
						self.bracket_manager._create_fill_anchored_children(order, pending, fill_event))
			else:
				self._brackets.consume(order_id)
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
			body_raised = True
			raise
		finally:
			# WR-04: a terminal fill ALWAYS releases its reservation, even when
			# the reconciliation body raised after the terminal status was set
			# (T-05-17: a stuck reservation corrupts buying power for the whole
			# run). `should_release` is False on the non-terminal early-return
			# path, which intentionally holds the reservation. The release is
			# idempotent — never-reserved orders (SELLs, children) silently
			# no-op.
			if should_release and self.portfolio_handler is not None:
				try:
					self.portfolio_handler.release(
						order.portfolio_id, order.id)
				except Exception:
					# WR-03: distinguish "body raised" from "release raised".
					# If the body already raised, that ORIGINAL exception is the
					# one propagating out of the finally — re-raising the release
					# failure here would mask it, so we only log. But if the body
					# succeeded and the release itself fails, a silently-unreleased
					# reservation IS the buying-power-corruption class WR-04
					# defends against, so it must reach the fail-fast seam.
					self.logger.error(
						'Failed to release reservation for order %s during fill reconciliation',
						order.id, exc_info=True)
					if not body_raised:
						raise
		return out_events
