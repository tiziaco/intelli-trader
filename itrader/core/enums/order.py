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


class OrderOperationType(Enum):
	"""Order-management operation type (D-04).

	Closed vocabulary for ``OperationResult.operation_type``. Each member's
	``.value`` is EQUAL to the exact current string literal — the carrier type
	changes, the value does not (value-equal swap), so audit records and logs
	stay byte-identical.
	"""
	CANCEL_ORDER = "cancel_order"
	CASH_RESERVATION = "cash_reservation"
	CREATE_ORDERS_FROM_SIGNAL = "create_orders_from_signal"
	CREATE_PRIMARY_ORDER = "create_primary_order"
	CREATE_STOP_LOSS = "create_stop_loss"
	CREATE_TAKE_PROFIT = "create_take_profit"
	MODIFY_ORDER = "modify_order"
	SIGNAL_ADMISSION = "signal_admission"
	SIGNAL_PROCESSING = "signal_processing"
	SIGNAL_SIZING = "signal_sizing"
	SIGNAL_VALIDATION = "signal_validation"

	@classmethod
	def _missing_(cls, value: object) -> "OrderOperationType":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderOperationType: {value!r}")


class MarketExecution(Enum):
	"""Market-order execution timing mode (D-06).

	Class-based with explicit string values EQUAL to the exact current
	literals (``immediate``/``next_bar``) and a case-insensitive
	``_missing_`` (OrderType house pattern). The carrier type at the
	``OrderManager`` ctor boundary changes (``str`` -> enum), the ``.value``
	does not — coercing ``MarketExecution(market_execution)`` parses a string
	(``_missing_``) and is a no-op on an existing member, so the stored
	configuration stays byte-identical.

	Per SYN-05 only the enum lands here; the ``OrderConfig`` model + threading
	is deferred to 999.5-(b).
	"""
	IMMEDIATE = "immediate"
	NEXT_BAR = "next_bar"

	@classmethod
	def _missing_(cls, value: object) -> "MarketExecution":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown MarketExecution: {value!r}")


class OrderTriggerSource(Enum):
	"""Who/what triggered an order state change (D-04).

	Closed vocabulary for ``OrderStateChange.triggered_by``. Each member's
	``.value`` is EQUAL to the exact current string literal (value-equal swap).
	Includes the defaults (``system``) and every distinct literal actually
	passed to ``add_state_change`` (``strategy``, ``exchange``, …).
	"""
	SYSTEM = "system"
	STRATEGY = "strategy"
	USER = "user"
	EXCHANGE = "exchange"
	VALIDATOR = "validator"
	CASH_RESERVATION = "cash_reservation"
	SIZING_POLICY = "sizing_policy"
	ADMISSION_DIRECTION = "admission_direction"
	ADMISSION_INCREASE = "admission_increase"
	ADMISSION_MAX_POSITIONS = "admission_max_positions"

	@classmethod
	def _missing_(cls, value: object) -> "OrderTriggerSource":
		"""Case-insensitive string parse; raise a clear f-string error."""
		if isinstance(value, str):
			for member in cls:
				if member.value.upper() == value.upper():
					return member
		raise ValueError(f"Unknown OrderTriggerSource: {value!r}")
