"""Order orchestration engine — the business logic layer behind OrderHandler."""

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

import pydantic

from .order import Order
from .operation_result import OperationResult
from ..core.enums import OrderStatus, MarketExecution
from ..core.ids import OrderId, PortfolioId
from ..core.commission_estimator import FeeModelProvider
from ..core.portfolio_read_model import PortfolioReadModel
from ..core.exceptions.base import ConfigurationError
from ..config import OrderConfig
from ..outils.dict_merge import recursive_merge
from .base import OrderStorage
from .brackets import BracketBook, BracketManager
from .admission import AdmissionManager
from .lifecycle import LifecycleManager
from .reconcile import ReconcileManager
from ..events_handler.events import OrderEvent, SignalEvent, FillEvent
from .order_validator import EnhancedOrderValidator
from .sizing_resolver import SizingResolver
from ..universe import Universe


class OrderManager:
	"""
	Order orchestration engine — the business logic layer behind OrderHandler.

	Coordinator over four collaborators: signal→order admission, order
	lifecycle (modify/cancel/expire), bracket assembly, and fill reconciliation.
	It declares brackets but never matches orders — the exchange holds the
	resting book and is the source of truth for fills.
	"""
	
	def __init__(self, order_storage: OrderStorage, logger: Any,
	             market_execution: "str | MarketExecution | None" = None,
	             portfolio_handler: Optional[PortfolioReadModel] = None,
	             fee_model_provider: Optional[FeeModelProvider] = None,
	             order_config: Optional[OrderConfig] = None,
	             enable_margin: bool = False,
	             portfolio_max_leverage: Decimal = Decimal("1")) -> None:
		"""
		Initialize the OrderManager.

		The manager has EXCLUSIVE ownership of the order storage and no
		back-reference to OrderHandler — layering is one-directional
		(facade -> manager -> storage). It never touches the events queue: it
		returns OperationResults carrying OrderEvents and the handler performs
		all queue puts.

		Parameters
		----------
		order_storage : OrderStorage
			Storage interface for order operations (manager-owned)
		logger : Logger
			Logger instance for order processing events
		order_config : OrderConfig, optional
			Order-domain config carrying ``market_execution``; the str->enum
			coercion lives in ``OrderConfig`` validation. None defaults to
			``OrderConfig.default()`` ("immediate").
		market_execution : str | MarketExecution, optional
			DEPRECATED backward-compat override: when provided it builds an
			``OrderConfig`` with this ``market_execution``.
			- "immediate": Execute market orders immediately (live trading)
			- "next_bar": Execute market orders on next bar (realistic backtesting)
		portfolio_handler : PortfolioReadModel, optional
			Narrow portfolio read boundary for position-aware operations; the
			concrete handler conforms structurally.
		fee_model_provider : FeeModelProvider, optional
			``(venue, account_id) -> FeeModel | None`` — the CURRENT fee model of
			the exchange serving an order's pair, feeding the admission
			reservation amount. Injected at wiring time as a typed read-model
			seam so this module never imports across the execution boundary.
			Pair-keyed on purpose: a zero-arg provider could only ever answer for
			the one exchange the wiring captured. The side/order-type convention
			the estimate is read at is admission POLICY and lives in
			``AdmissionManager``. ``None`` (or a provider returning ``None``)
			means a zero estimate, reproducing the pre-reservation funds-check
			math exactly.
		"""
		self.order_storage = order_storage
		self.logger = logger
		if order_config is None:
			order_config = (
				OrderConfig(market_execution=MarketExecution(market_execution))
				if market_execution is not None
				else OrderConfig.default())
		self.order_config = order_config
		self.market_execution = order_config.market_execution
		self.portfolio_handler = portfolio_handler
		self.fee_model_provider = fee_model_provider

		# enable_margin makes the validator DEFER its full-notional cash-cost check
		# to the AdmissionManager reservation gate, which reserves notional/L; see
		# EnhancedOrderValidator._check_cash_availability for why the full-notional
		# verdict is the wrong authority under margin.
		self.order_validator = EnhancedOrderValidator(portfolio_handler, enable_margin=enable_margin) if portfolio_handler else None

		# The ONE sizing resolver: dispatches on the signal's DECLARED SizingPolicy.
		# Optional for the same reason the read model is — resolution reads portfolio
		# state exclusively through the Protocol, so there is nothing to build without one.
		self.sizing_resolver = SizingResolver(portfolio_handler) if portfolio_handler else None

		# The shared pending-bracket book, owned here and injected into every
		# collaborator that touches it — a second copy would let a fill-anchored
		# child be built from a bracket another bucket already discarded.
		self._brackets = BracketBook()

		# Construction order matters below: bracket_manager must exist before the
		# admission and reconcile collaborators, which take it as an injected dep.
		self.bracket_manager = BracketManager(order_storage, logger, self._brackets)

		self.admission_manager = AdmissionManager(
			order_storage, logger, self.order_validator, self.sizing_resolver,
			portfolio_handler, fee_model_provider, self._brackets,
			self.bracket_manager, enable_margin=enable_margin,
			portfolio_max_leverage=portfolio_max_leverage)

		self.lifecycle_manager = LifecycleManager(
			order_storage, logger, self.order_validator, portfolio_handler,
			self._brackets)

		# Reconcile's orphaned-child cancel arrives as the `self.cancel_order`
		# coordinator callback rather than a direct LifecycleManager reference:
		# collaborators stay siblings-unaware, so the reconcile bucket cannot
		# reach past the coordinator into lifecycle state.
		self.reconcile_manager = ReconcileManager(
			order_storage, logger, portfolio_handler, self._brackets,
			self.bracket_manager, self.cancel_order)

	@property
	def _pending_brackets(self) -> BracketBook:
		"""Read-only accessor for the pending-bracket owner.

		Exposes the BracketBook under the legacy attribute name that
		``test_sltp_policy.py`` couples to; the book's dict-compat dunders make
		its ``== {}`` / ``in`` assertions pass. It is an alias, not a copy — a
		second raw dict alongside would let the two owners diverge.
		"""
		return self._brackets

	def update_config(self, updates: dict[str, Any]) -> None:
		"""Update order-domain configuration at runtime.

		recursive_merge -> model_validate -> atomic swap. Validation runs against
		the MERGED config before anything is stored, so a rejected update leaves
		the live config untouched; ``self.market_execution`` is re-derived only
		after the swap.

		Raises
		------
		ConfigurationError
			Wrapping the pydantic ``ValidationError``, which also rejects unknown
			keys via ``extra="forbid"``.
		"""
		merged = recursive_merge(self.order_config.model_dump(), updates)
		try:
			new_config = OrderConfig.model_validate(merged)
		except pydantic.ValidationError as e:
			raise ConfigurationError(reason=str(e)) from e
		self.order_config = new_config  # atomic GIL-safe reference swap
		self.market_execution = self.order_config.market_execution

	def on_fill(self, fill_event: FillEvent) -> List[OrderEvent]:
		"""Delegate fill reconciliation to ReconcileManager."""
		return self.reconcile_manager.on_fill(fill_event)

	def seed_applied_trades(self, keys: Iterable[str]) -> None:
		"""Restart-seed the reconcile dedup ring.

		``PortfolioHandler.rehydrate`` forwards the durable
		``f"{ticker}:{venue_trade_id}"`` history here so the order-mirror dedup arm
		is seeded SYMMETRICALLY with the portfolio ledger — seeding one side only
		would let a redelivered fill re-apply against the unseeded side.
		Live-path only; the backtest never rehydrates.
		"""
		self.reconcile_manager.seed_applied_trades(keys)

	def process_signal(self, signal_event: SignalEvent) -> List[OperationResult]:
		"""Delegate the signal→order pipeline to AdmissionManager."""
		return self.admission_manager.process_signal(signal_event)

	def set_universe(self, universe: "Universe") -> None:
		"""Forward the Universe injection to AdmissionManager.

		The runner builds the ``Universe`` after the order domain is constructed,
		so the seam is set late (mirrors ``SimulatedExchange.set_universe``). The
		order/risk leverage cap reads ``Instrument.max_leverage`` through it.
		"""
		self.admission_manager.set_universe(universe)

	def modify_order(self, order_id: OrderId, new_price: Optional[Decimal] = None, new_quantity: Optional[Decimal] = None,
	                portfolio_id: Optional[PortfolioId] = None, reason: str = "user modification") -> OperationResult:
		"""Delegate order modification to LifecycleManager."""
		return self.lifecycle_manager.modify_order(order_id, new_price, new_quantity, portfolio_id, reason)

	def cancel_order(self, order_id: OrderId, portfolio_id: Optional[PortfolioId] = None,
	                reason: str = "user cancellation") -> OperationResult:
		"""Delegate order cancellation to LifecycleManager."""
		return self.lifecycle_manager.cancel_order(order_id, portfolio_id, reason)

	def expire_all_resting(self) -> List[OperationResult]:
		"""Delegate the run-end time-in-force sweep to LifecycleManager."""
		return self.lifecycle_manager.expire_all_resting()

	def stamp_venue_order_id(self, order_id: OrderId, venue_order_id: str,
	                         portfolio_id: Optional[PortfolioId] = None) -> bool:
		"""Persist the venue ack onto the stored order mirror.

		Driven by ``OrderHandler.on_order_ack`` off a queued ORDER-ACK event: look up
		the stored order, stamp ``venue_order_id``, and persist via
		``order_storage.update_order``. The id must be PERSISTED, not just held in
		memory: the ``VenueCorrelationIndex`` is lost across a restart, so the
		stored id is the only way the post-restart reconciler can match its
		working-set orders to venue fills.

		Returns
		-------
		bool
			False if the order is unknown (e.g. an ack for an order already pruned
			from the mirror) or if the storage write did not take.
		"""
		order = self.order_storage.get_order_by_id(order_id, portfolio_id)
		if order is None:
			self.logger.warning(
				"ORDER-ACK for unknown order %s — venue_order_id %s not stamped",
				order_id, venue_order_id)
			return False
		order.venue_order_id = venue_order_id
		stamped = self.order_storage.update_order(order)
		# Once the venue acks, IT owns the real reservation: holding the local
		# pending overlay until terminal release would double-count the hold and
		# understate buying power. Dropped through the same injected read-model seam
		# admission uses for reserve/release, and only on a successful stamp — an
		# unknown order returned False above and never had a live overlay.
		if stamped and self.portfolio_handler is not None and portfolio_id is not None:
			self.portfolio_handler.drop_pending(portfolio_id, order_id)
		return stamped

	# --- Read interface --------------------------------------------------------
	# The manager owns the storage; OrderHandler read methods delegate here.

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
