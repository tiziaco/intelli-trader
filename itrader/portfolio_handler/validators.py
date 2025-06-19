"""
Validation utilities for portfolio handler components.
"""

import decimal
from typing import Union, Optional
from datetime import datetime

from .exceptions import InvalidTransactionError, PortfolioError

# Use Decimal for financial calculations to avoid floating point precision issues
DECIMAL_PRECISION = decimal.Decimal('0.00000001')  # 8 decimal places for crypto
MIN_CASH_BALANCE = decimal.Decimal('0.00')

class PortfolioValidator:
    """Validates portfolio operations and data integrity."""
    
    @staticmethod
    def validate_transaction_data(
        ticker: str, 
        price: float, 
        quantity: float, 
        commission: float,
        transaction_type: str
    ) -> None:
        """
        Validate transaction data before processing.
        
        Raises:
            InvalidTransactionError: If any validation fails
        """
        if not ticker or not isinstance(ticker, str):
            raise InvalidTransactionError("Ticker must be a non-empty string")
        
        if not isinstance(price, (int, float)) or price <= 0:
            raise InvalidTransactionError(f"Price must be positive, got {price}")
        
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            raise InvalidTransactionError(f"Quantity must be positive, got {quantity}")
        
        if not isinstance(commission, (int, float)) or commission < 0:
            raise InvalidTransactionError(f"Commission must be non-negative, got {commission}")
        
        if transaction_type not in ['BUY', 'SELL']:
            raise InvalidTransactionError(f"Invalid transaction type: {transaction_type}")
        
        # Check for reasonable limits
        if price > 1_000_000:  # $1M per unit seems unreasonable
            raise InvalidTransactionError(f"Price {price} seems unreasonably high")
        
        if quantity > 1_000_000:  # 1M units seems unreasonable
            raise InvalidTransactionError(f"Quantity {quantity} seems unreasonably high")
    
    @staticmethod
    def validate_portfolio_data(
        user_id: int,
        name: str,
        exchange: str,
        cash: float
    ) -> None:
        """
        Validate portfolio creation data.
        
        Raises:
            InvalidTransactionError: If any validation fails
        """
        if not isinstance(user_id, int) or user_id <= 0:
            raise InvalidTransactionError("User ID must be a positive integer")
        
        if not name or not isinstance(name, str) or len(name.strip()) == 0:
            raise InvalidTransactionError("Portfolio name must be a non-empty string")
        
        if not exchange or not isinstance(exchange, str):
            raise InvalidTransactionError("Exchange must be a non-empty string")
        
        if not isinstance(cash, (int, float)) or cash < 0:
            raise InvalidTransactionError(f"Initial cash must be non-negative, got {cash}")
    
    @staticmethod
    def validate_sufficient_funds(
        required_cash: decimal.Decimal,
        available_cash: decimal.Decimal,
        transaction_id: Optional[int] = None
    ) -> None:
        """
        Validate sufficient funds for a transaction.
        
        Raises:
            InsufficientFundsError: If insufficient funds
        """
        from .exceptions import InsufficientFundsError
        
        if available_cash < required_cash:
            raise InsufficientFundsError(
                float(required_cash), 
                float(available_cash), 
                transaction_id
            )
    
    @staticmethod
    def validate_cash_balance(cash_balance: decimal.Decimal) -> None:
        """
        Validate cash balance doesn't go negative.
        
        Raises:
            PortfolioError: If cash balance is negative
        """
        if cash_balance < MIN_CASH_BALANCE:
            raise PortfolioError(f"Cash balance cannot be negative: {cash_balance}")
    
    @staticmethod
    def to_decimal(value: Union[int, float]) -> decimal.Decimal:
        """Convert float to Decimal for precise financial calculations."""
        return decimal.Decimal(str(value)).quantize(DECIMAL_PRECISION)
    
    @staticmethod
    def from_decimal(value: decimal.Decimal) -> float:
        """Convert Decimal back to float for external APIs."""
        return float(value)

class PositionValidator:
    """Validates position calculations and state."""
    
    @staticmethod
    def validate_position_consistency(
        buy_quantity: float,
        sell_quantity: float,
        avg_bought: float,
        avg_sold: float
    ) -> None:
        """
        Validate position calculations are consistent.
        
        Raises:
            PositionCalculationError: If position data is inconsistent
        """
        from .exceptions import PositionCalculationError
        
        if buy_quantity > 0 and avg_bought <= 0:
            raise PositionCalculationError(
                "Average bought price must be positive when buy quantity > 0"
            )
        
        if sell_quantity > 0 and avg_sold <= 0:
            raise PositionCalculationError(
                "Average sold price must be positive when sell quantity > 0"
            )
        
        if buy_quantity < 0 or sell_quantity < 0:
            raise PositionCalculationError(
                "Quantities cannot be negative"
            )
