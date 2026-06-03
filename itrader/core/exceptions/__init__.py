"""
Core exceptions for the iTrader system.

This module provides all exception classes used throughout the iTrader system,
organized by domain and with a clear inheritance hierarchy.
"""

# Base exceptions
from .base import (
    ITradingSystemError,
    ValidationError,
    ConfigurationError,
    StateError,
    ConcurrencyError,
    NotFoundError
)

# Portfolio exceptions
from .portfolio import (
    PortfolioError,
    InsufficientFundsError,
    InvalidTransactionError,
    PortfolioNotFoundError,
    PositionCalculationError,
    PortfolioConcurrencyError,
    PortfolioHandlerError,
    InvalidPortfolioOperationError,
    PortfolioStateError,
    PortfolioConfigurationError,
    PortfolioValidationError
)

# Execution exceptions
from .execution import (
    ExecutionError,
    ExchangeConnectionError,
    OrderExecutionError,
    InsufficientFundsExecutionError,
    InvalidSymbolExecutionError,
    RateLimitExecutionError,
    OrderValidationExecutionError,
    ExchangeConfigurationError,
    ExchangeStateError,
    ExchangeNotFoundError,
    ExecutionTimeoutError,
    MarketClosedExecutionError
)

__all__ = [
    # Base exceptions
    'ITradingSystemError',
    'ValidationError',
    'ConfigurationError',
    'StateError',
    'ConcurrencyError',
    'NotFoundError',
    
    # Portfolio exceptions
    'PortfolioError',
    'InsufficientFundsError',
    'InvalidTransactionError',
    'PortfolioNotFoundError',
    'PositionCalculationError',
    'PortfolioConcurrencyError',
    'PortfolioHandlerError',
    'InvalidPortfolioOperationError',
    'PortfolioStateError',
    'PortfolioConfigurationError',
    'PortfolioValidationError',
    
    # Execution exceptions
    'ExecutionError',
    'ExchangeConnectionError',
    'OrderExecutionError',
    'InsufficientFundsExecutionError',
    'InvalidSymbolExecutionError',
    'RateLimitExecutionError',
    'OrderValidationExecutionError',
    'ExchangeConfigurationError',
    'ExchangeStateError',
    'ExchangeNotFoundError',
    'ExecutionTimeoutError',
    'MarketClosedExecutionError'
]
