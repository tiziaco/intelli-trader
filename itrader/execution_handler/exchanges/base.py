from typing import TYPE_CHECKING, Any, Dict, Protocol, runtime_checkable

from itrader.events_handler.events import OrderEvent
from ..result_objects import ConnectionResult, HealthStatus, OrderPreflightResult

if TYPE_CHECKING:
	# Type-only import (VENUE-04/D-09): keeps this Protocol module import-lean
	# on the live path — ``resolve_precision``'s return type is resolved for
	# mypy without pulling ``core.instrument`` into the runtime import graph.
	from itrader.core.instrument import Instrument


@runtime_checkable
class AbstractExchange(Protocol):
	"""
	Structural interface (D-07) for exchange operations including connection
	management, order execution, health monitoring, and error handling.

	This is a ``runtime_checkable`` ``Protocol`` rather than an ABC: it describes
	the swap-a-fake structural seam that both simulated and live exchanges must
	satisfy, with consistent error handling and monitoring capabilities.
	"""

	# Core execution methods
	def on_order(self, event: OrderEvent) -> None:
		"""
		Route an order event (NEW/CANCEL/MODIFY) for execution or resting.

		Concrete exchanges decide immediate execution vs. resting in an order book.
		"""
		...

	def on_market_data(self, bar: "Any") -> None:
		"""
		Drive resting-order matching against a new market-data bar.

		Concrete exchanges evaluate resting orders and emit fills/
		cancellations. This is the ONLY place fills happen (D-13 single
		matching path): ``execute_order`` is gone — a NEW order admitted
		by ``on_order`` rests in the book and fills on a later bar
		(next-bar-open convention for market orders, D-01/D-13).
		"""
		...

	# Connection management
	def connect(self) -> ConnectionResult:
		"""Establish connection to the exchange."""
		...

	def disconnect(self) -> ConnectionResult:
		"""Disconnect from the exchange."""
		...

	def is_connected(self) -> bool:
		"""Check if currently connected to exchange."""
		...

	# Health and monitoring
	def health_check(self) -> HealthStatus:
		"""Perform comprehensive health check of the exchange."""
		...

	# Configuration
	def configure(self, config: Dict[str, Any]) -> bool:
		"""Configure exchange with settings and credentials."""
		...

	# Validation methods
	def validate_order(self, event: OrderEvent) -> OrderPreflightResult:
		"""Run pre-trade checks before execution (OQ3: execution-domain
		preflight, distinct from the order-domain ValidationResult)."""
		...

	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is valid for trading on this exchange."""
		...

	def resolve_precision(self, symbol: str) -> "Instrument | None":
		"""Resolve the venue-precision ``Instrument`` for ``symbol`` (VENUE-04/D-09).

		Returns an ``Instrument`` carrying Decimal price/quantity scales read from
		the venue, or ``None`` when precision is unresolvable (no markets map /
		absent symbol / unusable entry) so callers fall to the ``_DEFAULT_*`` ladder.
		"""
		...
