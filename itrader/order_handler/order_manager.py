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
from typing import Any, Callable, Dict, List, Optional
from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderStatus, FillStatus, MarketExecution
from ..core.ids import OrderId, PortfolioId, StrategyId
from ..core.money import to_money
from ..core.portfolio_read_model import PortfolioReadModel
from .base import OrderStorage
from .brackets import BracketBook, BracketManager
from .admission import AdmissionManager
from .lifecycle import LifecycleManager
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
	             market_execution: "str | MarketExecution" = "immediate",
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
		market_execution : str | MarketExecution
			Market order execution mode (coerced to MarketExecution at this
			ctor boundary; accepts a str for backward-compat, D-06):
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
		# D-06: coerce at the ctor boundary — store the enum member (a str is
		# parsed via MarketExecution._missing_; an enum member is a no-op).
		self.market_execution = MarketExecution(market_execution)
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
		self._brackets = BracketBook()

		# D-04/D-09 coordinator-owned star: construct the bracket-assembly
		# collaborator ONCE, injecting the dep subset (order_storage, logger)
		# plus the shared BracketBook. The assembly/fill-anchored call sites
		# below delegate into it (mirror portfolio._init_managers).
		self.bracket_manager = BracketManager(order_storage, logger, self._brackets)

		# D-04/D-09 coordinator-owned star: construct the signal→order admission
		# collaborator ONCE — AFTER self._brackets and self.bracket_manager, since
		# admission reaches bracket assembly through the injected BracketManager
		# (D-08, the assembly seam) and holds NO reconcile/lifecycle ref. The
		# public process_signal / create_orders_from_signal delegate into it.
		self.admission_manager = AdmissionManager(
			order_storage, logger, self.order_validator, self.sizing_resolver,
			portfolio_handler, commission_estimator, self._brackets,
			self.bracket_manager)

		# D-04/D-09 coordinator-owned star: construct the modify/cancel lifecycle
		# collaborator ONCE, injecting the dep subset (order_storage, logger,
		# order_validator, portfolio_handler for release) plus the shared
		# BracketBook. modify_order / cancel_order below delegate into it (D-07).
		# It holds NO sibling reconcile/admission ref (D-08); on_fill's terminal
		# orphaned-child cancel routes through the OrderManager.cancel_order
		# delegation (preserving the star; the reconcile→lifecycle seam is wired
		# through the coordinator in plan 05, not via a direct sibling edge).
		self.lifecycle_manager = LifecycleManager(
			order_storage, logger, self.order_validator, portfolio_handler,
			self._brackets)

	@property
	def _pending_brackets(self) -> BracketBook:
		"""Read-only accessor for the pending-bracket owner (D-05).

		Exposes the BracketBook under the legacy attribute name so the
		internal-attribute-coupled test_sltp_policy.py reaches it unchanged;
		the book's dict-compat dunders make its `== {}` / `in` assertions
		pass byte-equal (Pitfall 2 option a). Single owner — no second raw
		dict is kept alongside (Pitfall 2 option c forbidden, D-05).
		"""
		return self._brackets

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
					child_result = self.cancel_order(
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

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""Delegate the signal→order pipeline to AdmissionManager (D-07)."""
		return self.admission_manager.process_signal(signal_event)

	def create_orders_from_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""Delegate direct order creation to AdmissionManager (D-07)."""
		return self.admission_manager.create_orders_from_signal(signal_event)

	def modify_order(self, order_id: OrderId, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[PortfolioId] = None, reason: str = "user modification") -> OperationResult:
		"""Delegate order modification to LifecycleManager (D-07)."""
		return self.lifecycle_manager.modify_order(order_id, new_price, new_quantity, portfolio_id, reason)

	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None,
	                reason: str = "user cancellation") -> OperationResult:
		"""Delegate order cancellation to LifecycleManager (D-07)."""
		return self.lifecycle_manager.cancel_order(order_id, portfolio_id, reason)

	# --- Read interface (D-18) -------------------------------------------------
	# The manager owns the storage; OrderHandler read methods delegate here.
	# Pure pass-through layer: same names, same signatures as the facade.

	def get_order_by_id(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None) -> Optional[Order]:
		"""Get an order by its ID from the manager-owned storage."""
		return self.order_storage.get_order_by_id(order_id, portfolio_id)

	def get_orders_by_status(self, status: OrderStatus, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""Get orders by their status from the manager-owned storage."""
		return self.order_storage.get_orders_by_status(status, portfolio_id)

	def get_active_orders(self, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""Get all active orders (PENDING and PARTIALLY_FILLED)."""
		return self.order_storage.get_active_orders(portfolio_id)

	def get_order_history(self, order_id: OrderId) -> List[Dict[str, Any]]:
		"""Get the state change history for an order."""
		return self.order_storage.get_order_history(order_id)

	def get_orders_by_ticker(self, ticker: str, portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""Get all orders for a specific ticker."""
		return self.order_storage.get_orders_by_ticker(ticker, portfolio_id)

	def search_orders(self, criteria: Dict[str, Any], portfolio_id: Optional[PortfolioId] = None) -> List[Order]:
		"""Search orders based on criteria."""
		return self.order_storage.search_orders(criteria, portfolio_id)

	def count_orders_by_status(self, portfolio_id: Optional[PortfolioId] = None) -> Dict[str, int]:
		"""Count orders by status (status name -> count)."""
		return self.order_storage.count_orders_by_status(portfolio_id)
