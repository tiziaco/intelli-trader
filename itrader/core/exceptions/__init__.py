"""
Core exceptions for the iTrader system.

This module provides all exception classes used throughout the iTrader system,
organized by domain and with a clear inheritance hierarchy.
"""

# Base exceptions
from .base import (
    ITraderError,
    ValidationError,
    ConfigurationError,
    StateError,
    NotFoundError
)

# Portfolio exceptions
from .portfolio import (
    PortfolioError,
    InsufficientFundsError,
    InvalidTransactionError,
    PortfolioNotFoundError,
    PositionCalculationError,
    PortfolioHandlerError,
    InvalidPortfolioOperationError,
    PortfolioStateError,
    PortfolioConfigurationError,
    PortfolioValidationError
)

# Order exceptions
from .order import (
    OrderError,
    SizingPolicyViolation,
    UnsizedSignalError
)

# Data exceptions
from .data import (
    DataError,
    MalformedDataError,
    MissingPriceDataError
)

__all__ = [
    # Base exceptions
    'ITraderError',
    'ValidationError',
    'ConfigurationError',
    'StateError',
    'NotFoundError',

    # Portfolio exceptions
    'PortfolioError',
    'InsufficientFundsError',
    'InvalidTransactionError',
    'PortfolioNotFoundError',
    'PositionCalculationError',
    'PortfolioHandlerError',
    'InvalidPortfolioOperationError',
    'PortfolioStateError',
    'PortfolioConfigurationError',
    'PortfolioValidationError',

    # Order exceptions
    'OrderError',
    'SizingPolicyViolation',
    'UnsizedSignalError',

    # Data exceptions
    'DataError',
    'MalformedDataError',
    'MissingPriceDataError'
]
