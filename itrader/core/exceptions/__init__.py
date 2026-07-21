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
    PortfolioValidationError,
    ReconciliationError
)

# Order exceptions
from .order import (
    OrderError,
    SizingPolicyViolation,
    UnsizedSignalError
)

# Strategy exceptions
from .strategy import (
    StrategyAdmissionError,
    UnknownParamError,
    MissingParamError,
    StrategyValidationError
)

# Credential exceptions
from .credential import (
    CredentialResolutionError
)

# Data exceptions
from .data import (
    DataError,
    MalformedDataError,
    MissingPriceDataError
)

# Results exceptions
from .results import (
    ResultsNotFound
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
    'ReconciliationError',

    # Order exceptions
    'OrderError',
    'SizingPolicyViolation',
    'UnsizedSignalError',

    # Strategy exceptions
    'StrategyAdmissionError',
    'UnknownParamError',
    'MissingParamError',
    'StrategyValidationError',

    # Credential exceptions
    'CredentialResolutionError',

    # Data exceptions
    'DataError',
    'MalformedDataError',
    'MissingPriceDataError',

    # Results exceptions
    'ResultsNotFound'
]
