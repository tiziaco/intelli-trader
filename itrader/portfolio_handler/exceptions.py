"""
Portfolio handler specific exceptions for production error handling.
"""

class PortfolioError(Exception):
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

class PortfolioNotFoundError(PortfolioError):
    """Raised when trying to access a non-existent portfolio."""
    
    def __init__(self, portfolio_id: int):
        self.portfolio_id = portfolio_id
        super().__init__(f"Portfolio {portfolio_id} not found")

class PositionCalculationError(PortfolioError):
    """Raised when position calculations result in inconsistent state."""
    
    def __init__(self, message: str, position_data: dict = None):
        self.position_data = position_data
        super().__init__(f"Position calculation error: {message}")

class ConcurrencyError(PortfolioError):
    """Raised when concurrent access causes data inconsistency."""
    
    def __init__(self, operation: str, portfolio_id: int = None):
        self.operation = operation
        self.portfolio_id = portfolio_id
        super().__init__(f"Concurrency error during {operation}")
