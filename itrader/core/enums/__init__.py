"""
Core enums for the iTrader system.

This module provides all enum classes used throughout the iTrader system,
organized by domain for better maintainability.
"""

# Portfolio enums
from .portfolio import (
    PortfolioState,
    PositionSide,
    TransactionType,
    PortfolioEventType
)

# Execution enums
from .execution import (
    ExecutionStatus,
    ExecutionErrorCode,
    ExchangeConnectionStatus,
    ExchangeType
)

__all__ = [
    # Portfolio enums
    'PortfolioState',
    'PositionSide', 
    'TransactionType',
    'PortfolioEventType',
    
    # Execution enums
    'ExecutionStatus',
    'ExecutionErrorCode',
    'ExchangeConnectionStatus',
    'ExchangeType'
]
