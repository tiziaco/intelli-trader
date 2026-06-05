"""
Order-related enums for the trading system.

Contains enums for order types, status, and related mappings used
across the order management system.
"""

from enum import Enum


class OrderType(Enum):
	"""Order type at the event/entity boundary.

	Class-based with explicit string values and a case-insensitive
	``_missing_`` (FillStatus house pattern) so the Plan 04-05 boundary
	parse ``OrderType("market")`` raises a clear ``ValueError`` on unknown
	strings instead of silently coercing (T-04-12).
	"""
	MARKET = "MARKET"
	STOP = "STOP"
	LIMIT = "LIMIT"

	@classmethod
	def _missing_(cls, value: object) -> "OrderType":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderType: {value!r}")

# Order Status Enum  
OrderStatus = Enum("OrderStatus", "PENDING PARTIALLY_FILLED FILLED CANCELLED REJECTED EXPIRED")

# Order Type Mapping
order_type_map = {
	"MARKET": OrderType.MARKET,
	"STOP": OrderType.STOP,
	"LIMIT": OrderType.LIMIT
}

# Order Status Mapping
order_status_map = {
	"PENDING": OrderStatus.PENDING,
	"PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
	"FILLED": OrderStatus.FILLED,
	"CANCELLED": OrderStatus.CANCELLED,
	"REJECTED": OrderStatus.REJECTED,
	"EXPIRED": OrderStatus.EXPIRED
}

# Valid state transitions for order lifecycle
VALID_ORDER_TRANSITIONS = {
	None: [OrderStatus.PENDING],  # Initial creation
	OrderStatus.PENDING: [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED],
	OrderStatus.PARTIALLY_FILLED: [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED],
	OrderStatus.FILLED: [],  # Terminal state
	OrderStatus.CANCELLED: [],  # Terminal state
	OrderStatus.REJECTED: [],  # Terminal state
	OrderStatus.EXPIRED: []   # Terminal state
}

# Order Command Enum (NEW order, CANCEL resting order, MODIFY resting order)
OrderCommand = Enum("OrderCommand", "NEW CANCEL MODIFY")

# Order Command Mapping
order_command_map = {
	"NEW": OrderCommand.NEW,
	"CANCEL": OrderCommand.CANCEL,
	"MODIFY": OrderCommand.MODIFY
}
