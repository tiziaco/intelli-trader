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
class OrderStatus(Enum):
	"""Order lifecycle status (D-01).

	Class-based with explicit string values (member name == ``.value``) and a
	case-insensitive ``_missing_`` (OrderType house pattern) so an unknown
	string raises a clear ``ValueError`` instead of silently coercing. The
	int->string ``.value`` flip is byte-inert: status serializes via ``.name``,
	never ``.value`` (D-02 audit).
	"""
	PENDING = "PENDING"
	PARTIALLY_FILLED = "PARTIALLY_FILLED"
	FILLED = "FILLED"
	CANCELLED = "CANCELLED"
	REJECTED = "REJECTED"
	EXPIRED = "EXPIRED"

	@classmethod
	def _missing_(cls, value: object) -> "OrderStatus":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderStatus: {value!r}")

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
class OrderCommand(Enum):
	"""Order command verb (D-01).

	Class-based with explicit string values (member name == ``.value``) and a
	case-insensitive ``_missing_`` (OrderType house pattern).
	"""
	NEW = "NEW"
	CANCEL = "CANCEL"
	MODIFY = "MODIFY"

	@classmethod
	def _missing_(cls, value: object) -> "OrderCommand":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderCommand: {value!r}")

# Order Command Mapping
order_command_map = {
	"NEW": OrderCommand.NEW,
	"CANCEL": OrderCommand.CANCEL,
	"MODIFY": OrderCommand.MODIFY
}
