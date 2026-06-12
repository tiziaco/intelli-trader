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

import pydantic

from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderStatus, MarketExecution
from ..core.ids import OrderId, PortfolioId
from ..core.commission_estimator import CommissionEstimator
from ..core.portfolio_read_model import PortfolioReadModel
from ..core.exceptions.base import ConfigurationError
from ..config import OrderConfig, deep_merge
from .base import OrderStorage
from .brackets import BracketBook, BracketManager
from .admission import AdmissionManager
from .lifecycle import LifecycleManager
from .reconcile import ReconcileManager
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
	             market_execution: "str | MarketExecution | None" = None,
	             portfolio_handler: Optional[PortfolioReadModel] = None,
	             commission_estimator: Optional[CommissionEstimator] = None,
	             order_config: Optional[OrderConfig] = None) -> None:
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
		order_config : OrderConfig, optional
			Order-domain config (D-05) carrying ``market_execution``. The
			str->enum coercion now lives in ``OrderConfig`` validation
			(``model_validate`` on a plain Enum field), replacing the loose
			ctor-boundary ``MarketExecution(market_execution)`` parse. None
			defaults to ``OrderConfig.default()`` ("immediate").
		market_execution : str | MarketExecution, optional
			DEPRECATED backward-compat override (D-05): when provided it builds
			an ``OrderConfig`` with this ``market_execution`` (still coerced via
			OrderConfig validation), so existing ``market_execution=`` callers
			keep working until Wave 4 migrates them to ``order_config``:
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Execute market orders on next bar (realistic backtesting)
		portfolio_handler : PortfolioReadModel, optional
			Narrow portfolio read boundary for position-aware operations
			(D-16: the concrete handler conforms structurally)
		commission_estimator : CommissionEstimator, optional
			Estimates the commission for an order as f(quantity, price) ->
			Decimal, feeding the admission reservation amount (Plan 05-06,
			D-04/D-15). INJECTED at wiring time as a typed read-model seam —
			order_manager never imports across the execution boundary (RESEARCH
			Pattern 1). None means a zero estimate, which reproduces the
			pre-reservation funds-check math exactly (the golden run pins fees 0).
		"""
		self.order_storage = order_storage
		self.logger = logger
		# D-05: the str->enum coercion lives in OrderConfig validation now. A
		# loose market_execution= override (backward-compat) builds an OrderConfig
		# from it; otherwise order_config (default "immediate") is used. The
		# stored member is byte-identical to the old MarketExecution() ctor parse.
		if order_config is None:
			order_config = (
				OrderConfig(market_execution=MarketExecution(market_execution))
				if market_execution is not None
				else OrderConfig.default())
		self.order_config = order_config
		self.market_execution = order_config.market_execution
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

		# D-04/D-09 coordinator-owned star: construct the FRAGILE fill-reconcile
		# collaborator ONCE — AFTER self.bracket_manager and self.cancel_order
		# (the plan-04 lifecycle delegation) resolve. on_fill's two cross-bucket
		# calls route through the injected coordinator-owned BracketManager
		# (fill-anchored children) and the self.cancel_order coordinator callback
		# (WR-05 orphaned-child cancel), preserving the D-04 star with NO sibling
		# reconcile→lifecycle/brackets edge and no circular import (D-08). on_fill
		# below is a 1-line delegation into it (D-07).
		self.reconcile_manager = ReconcileManager(
			order_storage, logger, portfolio_handler, self._brackets,
			self.bracket_manager, self.cancel_order)

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

	def update_config(self, updates: dict[str, Any]) -> None:
		"""Update order-domain configuration at runtime (D-05/D-07/D-08/D-09).

		Canonical contract over ``OrderConfig``: deep_merge -> model_validate ->
		atomic-swap, wrapping pydantic ``ValidationError`` (which also rejects
		unknown keys via ``extra="forbid"``) into ``ConfigurationError``. Returns
		``None`` and RAISES on failure. After the swap the cached
		``self.market_execution`` is re-derived from the new config (Pitfall 1).
		"""
		merged = deep_merge(self.order_config.model_dump(), updates)
		try:
			new_config = OrderConfig.model_validate(merged)
		except pydantic.ValidationError as e:
			raise ConfigurationError(reason=str(e)) from e
		self.order_config = new_config  # atomic GIL-safe reference swap (D-11)
		self.market_execution = self.order_config.market_execution

	def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]:
		"""Delegate fill reconciliation to ReconcileManager (D-07)."""
		return self.reconcile_manager.on_fill(fill_event)

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
