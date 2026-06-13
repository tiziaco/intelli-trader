"""
Execution-related enums for the iTrader system.
"""

from enum import Enum


class ExecutionStatus(Enum):
    """Execution status codes for order processing."""
    SUCCESS = "success"
    PARTIAL_FILL = "partial_fill"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_SYMBOL = "invalid_symbol"
    MARKET_CLOSED = "market_closed"


class ExecutionErrorCode(Enum):
    """Standardized error codes for execution operations."""
    NO_ERROR = "no_error"
    INVALID_ORDER = "invalid_order"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    EXCHANGE_ERROR = "exchange_error"
    NETWORK_ERROR = "network_error"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    MARKET_CLOSED = "market_closed"
    ORDER_SIZE_TOO_SMALL = "order_size_too_small"
    ORDER_SIZE_TOO_LARGE = "order_size_too_large"
    INVALID_PRICE = "invalid_price"
    EXCHANGE_MAINTENANCE = "exchange_maintenance"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_DENIED = "permission_denied"
    # Referenced by ExecutionTimeoutError; previously missing (would AttributeError
    # at raise-time). Added to back the existing timeout error path.
    TIMEOUT = "timeout"


class ExchangeConnectionStatus(Enum):
    """Exchange connection status states."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    DISCONNECTING = "disconnecting"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class ExchangeType(Enum):
    """Types of exchanges supported."""
    SIMULATED = "simulated"
    LIVE = "live"
    PAPER = "paper"
    SANDBOX = "sandbox"


class FillStatus(Enum):
    """Execution-truth fill status emitted by the exchange.

    Kept DISTINCT from ``OrderStatus`` (the order mirror): the
    ``FillStatus.EXECUTED -> OrderStatus.FILLED`` mapping in
    ``order_manager`` is the intended exchange-truth -> mirror reconciliation
    (D-04) and must be preserved. (The former portfolio transaction-state
    lifecycle enum died with the saga machinery — Plan 05-05 D-11.)

    Member values are explicit uppercase strings, preserving the exact member
    names of the prior functional ``Enum("FillStatus", "EXECUTED REFUSED
    CANCELLED")`` definition. No code relies on the ``.value`` being an int
    (verified), so explicit string values are safe and clearer.
    """
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    @classmethod
    def _missing_(cls, value: object) -> "FillStatus":
        """Case-insensitive string parse; raise a clear f-string error.

        Invoked by ``FillStatus(value)`` on lookup failure. Replaces the
        scattered ``fill_status_map.get(status)`` dict pattern and the buggy
        ``raise ValueError('Value %s', x)`` printf-tuple form (D-04).
        """
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown FillStatus: {value!r}")
