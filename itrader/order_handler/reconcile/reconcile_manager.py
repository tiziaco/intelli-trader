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
  holds no BracketManager *as a sibling edge* beyond that injected object. The
  `BracketManager` type is imported only under `TYPE_CHECKING`; this keeps the
  annotation NAME off the module's runtime name bindings only — it does NOT avoid
  loading the class, which the runtime `from ..brackets import BracketBook` import
  (line 41) already pulls in transitively (harmless — no import cycle).

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
from ...core.enums import FillStatus, OrderStatus
from ...core.money import to_money
from ...core.portfolio_read_model import PortfolioReadModel
from ...events_handler.events import OrderEvent, FillEvent

if TYPE_CHECKING:
	from ..brackets import BracketManager
	from ..order import Order


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

	@staticmethod
	def _classify(status: FillStatus) -> "tuple[bool, Optional[OrderStatus]]":
		"""
		Name the exchange-truth fill status -> order-mirror transition mapping
		and its terminal-ness, for READABILITY only (D-06 clarity cleanup).

		Returns ``(terminal, transition)``:
		- EXECUTED  -> (True,  OrderStatus.FILLED)
		- CANCELLED -> (True,  OrderStatus.CANCELLED)
		- REFUSED   -> (True,  OrderStatus.REJECTED)
		- EXPIRED   -> (True,  OrderStatus.EXPIRED)
		- anything else (unknown / non-terminal) -> (False, None)

		This is a pure naming aid: it does NOT drive the mirror transition (the
		per-status arms below call ``order.add_fill``/``cancel_order``/
		``reject_order`` directly, exactly as before). The non-terminal
		``(False, None)`` case stays an early-return INSIDE ``on_fill`` so the
		reservation is intentionally HELD — the early-return is NOT pushed into
		this helper (it must not arm ``should_release``).

		IN-03 — DUAL-EDIT REQUIREMENT: the terminal-status vocabulary is encoded
		in TWO places: here (the ``(terminal, transition)`` mapping) and the
		per-status ``if/elif`` dispatch in ``on_fill`` (the ``_apply_*`` arms).
		Adding a new terminal ``FillStatus`` (as LIFE-01 did with EXPIRED)
		requires editing BOTH sites. A missed dispatch arm is caught loud at
		runtime by the ``else: raise NotImplementedError`` fallthrough in
		``on_fill`` — that guard is the safety net, but the duplication is a
		maintenance trap, so it is documented here rather than left to be
		re-discovered on the next status addition.
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
		EXECUTED arm: apply an exchange fill increment to the order mirror (D-12).

		Live venues deliver PARTIAL fills; the mirror accumulates each increment
		against cumulative-filled and terminalizes to FILLED only when the fill
		covers the entire remaining quantity (the full-quantity ``add_fill``
		contract). A shortfall stays OPEN at PARTIALLY_FILLED — the order keeps
		working, its reservation is HELD, and no engine-imposed timeout ages it
		out (D-12 no premature terminalization; D-13 aging is a strategy concern).

		Returns ``(applied, terminalized)``:
		- ``applied``      — ``True`` when the mirror moved. On a rejected mirror
		                     update the caller must NOT early-return: the portfolio
		                     already settled this fill (FILL dispatches
		                     portfolio-first), so a terminal fill's uniform release
		                     must still run or the BUY's reservation is stuck
		                     forever (WR-02 / T-05-17).
		- ``terminalized`` — ``True`` only when THIS fill completed the order
		                     (-> FILLED). ``False`` when the order stayed open
		                     (a partial, D-12) so the caller HOLDS the reservation
		                     and SKIPS the terminal-only bracket post-processing.
		"""
		# D-22: fill_event.price/quantity are Decimal — to_money is an identity
		# normalization at this domain entry (the mirror never trusts an
		# unnormalized money input).
		increment = to_money(fill_event.quantity)
		fill_price = to_money(fill_event.price)
		# COMMON PATH (tried FIRST): a fill that covers the ENTIRE remaining
		# quantity completes the order via the full-quantity add_fill contract ->
		# FILLED. The simulated single-fill path stays byte-exact (filled 0,
		# increment == quantity). Trying add_fill first also keeps any mirror/fake
		# whose add_fill simply succeeds (existing reconcile suites) untouched: the
		# state inspection below runs ONLY when add_fill rejects.
		if order.add_fill(increment, fill_price, fill_event.time, "exchange fill"):
			return True, True
		# add_fill REJECTED the increment. Distinguish three outcomes:
		if not order.is_active:
			# WR-02 / T-05-17: an EXECUTED fill for an ALREADY-TERMINAL mirror
			# (e.g. locally CANCELLED before the exchange ack) can never move the
			# order — but the portfolio already settled the fill (FILL dispatches
			# portfolio-first), so this is still a TERMINAL reconciliation whose
			# uniform release MUST run or the reservation is stuck forever. Preserve
			# the pre-D-12 contract: rejected mirror, but terminalized -> release.
			self.logger.warning(
				'add_fill rejected for order %s (mirror already terminal); left unchanged', order_id)
			return False, True
		# The order is ACTIVE, so add_fill rejected at its full-quantity guard
		# WITHOUT mutating filled_quantity — the remaining quantity is accurate.
		remaining = order.remaining_quantity
		if 0 < increment < remaining:
			# Partial fill (D-12): a strict shortfall against the remaining leaves
			# the order OPEN at PARTIALLY_FILLED — accumulate the increment, HOLD
			# the reservation, and impose NO timeout (D-13 — aging is a strategy
			# concern). add_fill did not mutate, so this does not double-count.
			#
			# WR-03: validate the transition BEFORE mutating filled_quantity.
			# Compute the prospective total WITHOUT assigning it yet, so a rejected
			# transition leaves the mirror literally unchanged (the "mirror left
			# unchanged" contract below now holds — pre-reorder the quantity was
			# bumped before the validation could reject it).
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
			# Transition accepted — NOW accumulate the increment (mirror moves only
			# after the validation passed).
			order.filled_quantity = new_filled
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
		"""CANCELLED arm: mark the order CANCELLED (exchange cancellation)."""
		order.cancel_order("exchange cancellation")

	@staticmethod
	def _apply_refused(order: "Order") -> None:
		"""REFUSED arm: mark the order REJECTED (exchange rejection)."""
		order.reject_order("exchange rejection")

	@staticmethod
	def _apply_expired(order: "Order") -> None:
		"""EXPIRED arm: mark the order EXPIRED (exchange expiration).

		D-09 LANDMINE: NO custom already-EXPIRED guard. When the run-end sweep
		already transitioned the mirror locally to EXPIRED, ``expire_order`` here
		is a silent no-op — ``add_state_change`` returns False on the invalid
		EXPIRED->EXPIRED transition (``VALID_ORDER_TRANSITIONS[EXPIRED] == []``,
		order.py:307-309), so idempotency is FREE without a guard. The terminal
		release still runs in the byte-identical finally; the second release is
		idempotent (pops nothing)."""
		order.expire_order("exchange expiration")

	def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]:
		"""
		Reconcile the order mirror against an exchange fill.

		EXECUTED -> mark the order FILLED; CANCELLED -> mark CANCELLED;
		REFUSED -> mark REJECTED. The terminal status change alone moves the
		order out of active queries (D-20: "active" is an entity predicate,
		not a container) — the order stays in storage for the audit trail.

		D-06 (RECON-01 clarity cleanup): the per-status arms are named helpers
		(``_apply_executed``/``_apply_cancelled``/``_apply_refused``), the
		status->transition mapping is named ``_classify``, and the finally body
		is named ``_release_reservation`` — but the ``try``/``finally``
		exception-safety skeleton and the two load-bearing gate points
		(``should_release`` armed AFTER the terminal status and BEFORE further
		work; the inner re-raise gated on ``not body_raised``) are BYTE-IDENTICAL
		to the verbatim move. This is a readability extraction, NOT a control-flow
		rewrite: a sequential ``apply(); release()`` state machine is the REJECTED
		anti-pattern (it reintroduces the WR-04 skip-release-on-raise bug).

		Returns
		-------
		List[OrderEvent]
			CANCEL OrderEvents for bracket children orphaned by a parent that
			reached a terminal state without any fill (WR-05), CANCEL OrderEvents
			for bracket children orphaned when an EXECUTED fill FLATTENED their
			portfolio+ticker position (OVERSELL-B), plus the fill-anchored
			PercentFromFill children created on the parent's EXECUTED fill (D-13,
			Pattern 5 Option B). The manager never touches the queue (D-18) — the
			handler enqueues these.
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
			# D-12: CANCELLED/REFUSED/EXPIRED terminalize unconditionally; an
			# EXECUTED fill overrides this below — a PARTIAL fill leaves the order
			# OPEN (PARTIALLY_FILLED), so it is NOT terminal and the reservation is
			# HELD. ``terminalized`` (not merely the fill-status classification)
			# now drives ``should_release`` and the terminal-only bracket work.
			terminalized = True
			# _classify names the EXECUTED/CANCELLED/REFUSED -> FILLED/CANCELLED/
			# REJECTED mapping + terminal-ness (READABILITY only — it does not
			# drive the mirror transition; the arms below do). The unknown /
			# non-terminal case stays an early-return HERE (NOT in the helper) so
			# the reservation is intentionally HELD (should_release stays False).
			terminal, _transition = self._classify(fill_event.status)
			if not terminal:
				# Truly unknown / non-terminal status: leave the order active
				# and alert. (No release either — an unknown status is not a
				# terminal reconciliation, so the reservation is intentionally
				# held: should_release stays False on this early-return path.)
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
				# Defensive: _classify marked this status terminal but no arm
				# dispatches it (a future FillStatus added to _classify without a
				# matching arm here). Fail loud BEFORE should_release is armed so the
				# reservation stays held — never silently mis-reconcile as REFUSED.
				raise NotImplementedError(
					f'terminal fill status {fill_event.status!r} has no reconcile arm')
			# D-12: arm the release only when THIS fill terminalized the order.
			# CANCELLED/REFUSED/EXPIRED always terminalize; an EXECUTED fill does
			# so only when it fully filled the order — a PARTIAL leaves it OPEN, so
			# ``terminalized`` is False and the reservation is intentionally HELD.
			# should_release is still armed BEFORE the update/bracket work below so
			# a raise there still releases a TERMINAL fill (the WR-04 skeleton is
			# preserved — the arm point and the finally re-raise gate are unchanged).
			should_release = terminalized
			# Reached for every terminal-status fill AND for an accumulating
			# partial (whose mirror moved to PARTIALLY_FILLED). Persist whenever
			# the mirror moved (D-13: the store's cumulative-filled is the
			# restart cross-check). D-20: no deactivate step — a terminal status
			# already removes the order from active queries via is_active.
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
			if fill_event.status == FillStatus.EXECUTED and terminalized:
				# D-12: only a TERMINAL (fully-filled) EXECUTED fill consumes the
				# pending bracket + mints the fill-anchored children / runs the
				# OVERSELL flatten. A PARTIAL leaves the parent working, so the
				# bracket stays PENDING for the completing fill (no premature
				# child creation, no bracket discard).
				pending = self._brackets.consume(order_id)
				# WR-03 (part 1): only anchor children when the mirror actually
				# applied the fill. If add_fill was rejected (applied=False) the
				# parent never moved, so creating fill-anchored children would
				# link live SL/TP to a parent the engine still considers unfilled.
				if pending is not None and applied:
					out_events.extend(
						self.bracket_manager._create_fill_anchored_children(order, pending, fill_event))
				# OVERSELL-B (the SEED fix): when an EXECUTED fill FLATTENS the
				# (portfolio, ticker) position, cancel that portfolio+ticker's
				# resting bracket children. Root cause:
				# .planning/debug/spot-long-only-oversell.md — a discretionary
				# market SELL flattens a bracketed long but the matching engine's
				# OCO only cancels a bracket's OWN sibling, so the orphaned SL/TP
				# survive and fire later as a SELL fill against a flat portfolio,
				# bypassing admission and seeding the silent over-sell. This is
				# DISTINCT from the WR-05 case above (a PARENT that terminated
				# WITHOUT any fill); here a SEPARATE order's EXECUTED fill closed
				# the position. Stays in the ORDER domain: reads the portfolio
				# ONLY through the injected read-model and cancels ONLY through the
				# injected coordinator callback (D-04 star / D-08 — no cross-domain
				# reach). Oracle-dark: SMA_MACD declares no brackets.
				if self.portfolio_handler is not None:
					view = self.portfolio_handler.get_position(
						fill_event.portfolio_id, fill_event.ticker)
					if view is None:  # the fill closed the position — now FLAT
						for active in self.order_storage.get_active_orders(fill_event.portfolio_id):
							# Scope PRECISELY: same ticker, a bracket child
							# (parent_order_id is not None), never the just-filled
							# order itself, never other tickers / non-bracket orders.
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
				# D-12: a PARTIAL EXECUTED fill (EXECUTED but not terminalized)
				# falls through NEITHER branch, so the bracket stays PENDING for
				# the completing fill (never prematurely discarded).
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
			# WR-04: the finally STATEMENT stays in on_fill; only its CONTENTS
			# move into the named _release_reservation helper (D-06 clarity —
			# release-once-on-terminal made obvious by name, control flow
			# unchanged).
			self._release_reservation(order, should_release, body_raised)
		return out_events

	def _release_reservation(self, order: "Order", should_release: bool, body_raised: bool) -> None:
		"""
		Idempotent terminal-release of the order's cash reservation (D-06).

		Holds the CONTENTS of ``on_fill``'s ``finally`` body byte-for-byte: the
		``should_release``/``portfolio_handler`` guard, the inner release
		``try``/``except``, and the ``if not body_raised: raise`` re-raise gate.
		The ``finally`` STATEMENT itself stays in ``on_fill``; only this body was
		extracted for clarity.
		"""
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
