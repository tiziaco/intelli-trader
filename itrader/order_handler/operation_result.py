"""
Operation result classes for OrderManager operations.

These classes provide structured responses for all order management operations,
ensuring consistent error handling and event generation.
"""

from dataclasses import dataclass, field
from typing import List, Optional
from ..events_handler.event import OrderEvent


@dataclass
class OperationResult:
	"""
	Result of an order management operation.
	
	Provides structured response with success status, error details,
	and generated OrderEvents for execution pipeline.
	"""
	success: bool
	message: str
	order_events: List[OrderEvent] = field(default_factory=list)
	error_details: Optional[str] = None
	operation_type: str = ""
	affected_order_ids: List[int] = field(default_factory=list)
	
	@classmethod
	def success_result(cls, message: str, order_events: List[OrderEvent] = None, 
	                  operation_type: str = "", affected_order_ids: List[int] = None):
		"""Create a successful operation result."""
		return cls(
			success=True,
			message=message,
			order_events=order_events or [],
			operation_type=operation_type,
			affected_order_ids=affected_order_ids or []
		)
	
	@classmethod
	def failure_result(cls, message: str, error_details: str = None, 
	                  operation_type: str = ""):
		"""Create a failed operation result."""
		return cls(
			success=False,
			message=message,
			error_details=error_details,
			operation_type=operation_type
		)
	
	def __str__(self):
		status = "SUCCESS" if self.success else "FAILURE"
		return f"{status}: {self.message}"


@dataclass
class SignalProcessingResult:
	"""
	Result of processing a signal event.
	
	Contains results for all operations performed (create market order,
	create stop loss, create take profit, modify existing orders, etc.)
	"""
	overall_success: bool
	message: str
	operation_results: List[OperationResult] = field(default_factory=list)
	
	@property
	def all_order_events(self) -> List[OrderEvent]:
		"""Get all OrderEvents from all operation results."""
		events = []
		for result in self.operation_results:
			events.extend(result.order_events)
		return events
	
	@classmethod
	def from_operations(cls, operation_results: List[OperationResult], 
	                   overall_message: str = ""):
		"""Create SignalProcessingResult from a list of operation results."""
		overall_success = any(result.success for result in operation_results)
		if not overall_message:
			success_count = sum(1 for result in operation_results if result.success)
			total_count = len(operation_results)
			overall_message = f"Processed {success_count}/{total_count} operations successfully"
		
		return cls(
			overall_success=overall_success,
			message=overall_message,
			operation_results=operation_results
		)
