"""
Execution-specific exceptions for the iTrader system.
"""

from .base import ITradingSystemError, ValidationError, ConfigurationError, StateError, ConcurrencyError, NotFoundError
from ..enums.execution import ExecutionErrorCode


class ExecutionError(ITradingSystemError):
    """Base exception for execution-related errors."""
    
    def __init__(self, message: str, error_code: ExecutionErrorCode = ExecutionErrorCode.EXCHANGE_ERROR):
        self.error_code = error_code
        super().__init__(message)


class ExchangeConnectionError(ExecutionError):
    """Raised when exchange connection fails."""
    
    def __init__(self, exchange_name: str, reason: str = None):
        self.exchange_name = exchange_name
        self.reason = reason
        message = f"Connection failed to exchange '{exchange_name}'"
        if reason:
            message += f": {reason}"
        super().__init__(message, ExecutionErrorCode.NETWORK_ERROR)


class OrderExecutionError(ExecutionError):
    """Raised when order execution fails."""
    
    def __init__(self, order_id: str = None, reason: str = None, error_code: ExecutionErrorCode = ExecutionErrorCode.EXCHANGE_ERROR):
        self.order_id = order_id
        self.reason = reason
        message = "Order execution failed"
        if order_id:
            message += f" for order {order_id}"
        if reason:
            message += f": {reason}"
        super().__init__(message, error_code)


class InsufficientFundsExecutionError(ExecutionError):
    """Raised when insufficient funds for order execution."""
    
    def __init__(self, required_amount: float, available_amount: float, symbol: str = None):
        self.required_amount = required_amount
        self.available_amount = available_amount
        self.symbol = symbol
        message = f"Insufficient funds: Required {required_amount:.4f}, Available {available_amount:.4f}"
        if symbol:
            message += f" for {symbol}"
        super().__init__(message, ExecutionErrorCode.INSUFFICIENT_FUNDS)


class InvalidSymbolExecutionError(ExecutionError):
    """Raised when trading symbol is invalid or not supported."""
    
    def __init__(self, symbol: str, exchange: str = None):
        self.symbol = symbol
        self.exchange = exchange
        message = f"Invalid symbol: {symbol}"
        if exchange:
            message += f" on exchange {exchange}"
        super().__init__(message, ExecutionErrorCode.SYMBOL_NOT_FOUND)


class RateLimitExecutionError(ExecutionError):
    """Raised when exchange rate limit is exceeded."""
    
    def __init__(self, exchange: str = None, retry_after: int = None):
        self.exchange = exchange
        self.retry_after = retry_after
        message = "Rate limit exceeded"
        if exchange:
            message += f" on exchange {exchange}"
        if retry_after:
            message += f", retry after {retry_after} seconds"
        super().__init__(message, ExecutionErrorCode.RATE_LIMIT_EXCEEDED)


class OrderValidationExecutionError(ValidationError):
    """Raised when order validation fails before execution."""
    
    def __init__(self, field: str, value: str = None, message: str = None):
        super().__init__(field, value, message)


class ExchangeConfigurationError(ConfigurationError):
    """Raised when exchange configuration is invalid."""
    
    def __init__(self, exchange_name: str, config_key: str = None, reason: str = None):
        self.exchange_name = exchange_name
        message = f"Configuration error for exchange '{exchange_name}'"
        if config_key:
            message += f" (key: {config_key})"
        if reason:
            message += f": {reason}"
        super().__init__(config_key, reason=message)


class ExchangeStateError(StateError):
    """Raised when exchange is in invalid state for operation."""
    
    def __init__(self, exchange_name: str, current_state: str, required_state: str = None, operation: str = None):
        self.exchange_name = exchange_name
        # Use exchange_name as entity_id for consistency with base class
        super().__init__(exchange_name, current_state, required_state, operation)


class ExchangeNotFoundError(NotFoundError):
    """Raised when trying to access a non-existent exchange."""
    
    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
        super().__init__("Exchange", identifier=exchange_name)


class ExecutionTimeoutError(ExecutionError):
    """Raised when order execution times out."""
    
    def __init__(self, order_id: str = None, timeout_seconds: int = None):
        self.order_id = order_id
        self.timeout_seconds = timeout_seconds
        message = "Order execution timed out"
        if order_id:
            message += f" for order {order_id}"
        if timeout_seconds:
            message += f" after {timeout_seconds} seconds"
        super().__init__(message, ExecutionErrorCode.TIMEOUT)


class MarketClosedExecutionError(ExecutionError):
    """Raised when attempting to trade while market is closed."""
    
    def __init__(self, symbol: str, market_hours: str = None):
        self.symbol = symbol
        self.market_hours = market_hours
        message = f"Market is closed for {symbol}"
        if market_hours:
            message += f" (market hours: {market_hours})"
        super().__init__(message, ExecutionErrorCode.MARKET_CLOSED)
