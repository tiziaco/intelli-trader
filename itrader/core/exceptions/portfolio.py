"""
Portfolio-specific exceptions for the iTrader system.
"""

from .base import ITradingSystemError, ValidationError, ConfigurationError, StateError, ConcurrencyError, NotFoundError


class PortfolioError(ITradingSystemError):
    """Base exception for portfolio-related errors."""
    pass


class InsufficientFundsError(PortfolioError):
    """Raised when attempting to execute a transaction with insufficient funds."""
    
    def __init__(self, required_cash: float, available_cash: float, transaction_id: int = None):
        self.required_cash = required_cash
        self.available_cash = available_cash
        self.transaction_id = transaction_id
        super().__init__(
            f"Insufficient funds: Required ${required_cash:.2f}, Available ${available_cash:.2f}"
        )


class InvalidTransactionError(PortfolioError):
    """Raised when transaction data is invalid."""
    
    def __init__(self, message: str, transaction_data: dict = None):
        self.transaction_data = transaction_data
        super().__init__(f"Invalid transaction: {message}")


class PortfolioNotFoundError(NotFoundError):
    """Raised when trying to access a non-existent portfolio."""
    
    def __init__(self, portfolio_id: int):
        self.portfolio_id = portfolio_id
        super().__init__("Portfolio", portfolio_id)


class PositionCalculationError(PortfolioError):
    """Raised when position calculations result in inconsistent state."""
    
    def __init__(self, message: str, position_data: dict = None):
        self.position_data = position_data
        super().__init__(f"Position calculation error: {message}")


class PortfolioConcurrencyError(ConcurrencyError):
    """Raised when concurrent access causes data inconsistency in portfolios."""
    
    def __init__(self, operation: str, portfolio_id: int = None):
        super().__init__(operation, portfolio_id, "portfolio")


# PortfolioHandler specific exceptions
class PortfolioHandlerError(PortfolioError):
    """Base exception for all portfolio handler errors."""
    pass


class InvalidPortfolioOperationError(PortfolioHandlerError):
    """Raised when attempting an invalid operation on a portfolio."""
    
    def __init__(self, operation: str, portfolio_id: int = None, reason: str = None):
        self.operation = operation
        self.portfolio_id = portfolio_id
        self.reason = reason
        message = f"Invalid portfolio operation: {operation}"
        if portfolio_id:
            message += f" on portfolio {portfolio_id}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)


class PortfolioStateError(StateError):
    """Raised when portfolio is in invalid state for requested operation."""
    
    def __init__(self, portfolio_id: int, current_state: str, required_state: str = None, operation: str = None):
        super().__init__(portfolio_id, current_state, required_state, operation)
        self.portfolio_id = portfolio_id


class PortfolioConfigurationError(ConfigurationError):
    """Raised when portfolio configuration is invalid."""
    pass


class PortfolioValidationError(ValidationError):
    """Raised when portfolio validation fails."""
    
    def __init__(self, portfolio_id: int, validation_type: str, details: str = None):
        self.portfolio_id = portfolio_id
        self.validation_type = validation_type
        self.details = details
        message = f"Portfolio {portfolio_id} failed {validation_type} validation"
        if details:
            message += f": {details}"
        super().__init__(validation_type, str(portfolio_id), message)
