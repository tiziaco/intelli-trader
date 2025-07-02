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
