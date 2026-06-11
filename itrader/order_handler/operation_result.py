"""
Operation result classes for OrderManager operations.

These classes provide structured responses for all order management operations,
ensuring consistent error handling and event generation.
"""

from dataclasses import dataclass
from typing import Any, List, Optional
from ..core.enums import OrderOperationType
from ..events_handler.events import OrderEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationResult:
	"""
	Result of an order management operation.

	Provides structured response with success status, error details,
	and generated OrderEvents for execution pipeline.
	"""
	success: bool
	message: str
	operation_type: OrderOperationType
	order_events: tuple[OrderEvent, ...] = ()
	error_details: Optional[str] = None
	affected_order_ids: tuple[Any, ...] = ()

	@classmethod
	def success_result(cls, message: str, operation_type: OrderOperationType,
	                  order_events: Optional[List[OrderEvent]] = None,
	                  affected_order_ids: Optional[List[Any]] = None) -> "OperationResult":
		"""Create a successful operation result."""
		return cls(
			success=True,
			message=message,
			order_events=tuple(order_events or ()),
			operation_type=operation_type,
			affected_order_ids=tuple(affected_order_ids or ())
		)
	
	@classmethod
	def failure_result(cls, message: str, operation_type: OrderOperationType,
	                  error_details: Optional[str] = None) -> "OperationResult":
		"""Create a failed operation result."""
		return cls(
			success=False,
			message=message,
			error_details=error_details,
			operation_type=operation_type
		)
	
	def __str__(self) -> str:
		status = "SUCCESS" if self.success else "FAILURE"
		return f"{status}: {self.message}"


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalProcessingResult:
	"""
	Result of processing a signal event.

	Contains results for all operations performed (create market order,
	create stop loss, create take profit, modify existing orders, etc.)
	"""
	overall_success: bool
	message: str
	operation_results: tuple[OperationResult, ...] = ()

	@property
	def all_order_events(self) -> List[OrderEvent]:
		"""Get all OrderEvents from all operation results."""
		events: List[OrderEvent] = []
		for result in self.operation_results:
			events.extend(result.order_events)
		return events

	@classmethod
	def from_operations(cls, operation_results: List[OperationResult],
	                   overall_message: str = "") -> "SignalProcessingResult":
		"""Create SignalProcessingResult from a list of operation results."""
		overall_success = any(result.success for result in operation_results)
		if not overall_message:
			success_count = sum(1 for result in operation_results if result.success)
			total_count = len(operation_results)
			overall_message = f"Processed {success_count}/{total_count} operations successfully"

		return cls(
			overall_success=overall_success,
			message=overall_message,
			operation_results=tuple(operation_results)
		)
