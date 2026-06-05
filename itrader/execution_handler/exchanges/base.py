from typing import Any, Dict, Protocol, runtime_checkable

from itrader.events_handler.events import OrderEvent
from ..result_objects import ExecutionResult, ConnectionResult, HealthStatus, ValidationResult


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

		Concrete exchanges evaluate resting orders and emit fills/cancellations.
		"""
		...

	def execute_order(self, event: OrderEvent) -> ExecutionResult:
		"""
		Execute an order and return detailed execution result.
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
	def validate_order(self, event: OrderEvent) -> ValidationResult:
		"""Validate order before execution with comprehensive checks."""
		...

	def validate_symbol(self, symbol: str) -> bool:
		"""Check if symbol is valid for trading on this exchange."""
		...
