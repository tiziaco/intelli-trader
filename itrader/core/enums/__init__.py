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
    PortfolioEventType,
    CashOperationType,
    PositionEvent,
    MetricsPeriod,
    TransactionState
)

# Execution enums
from .execution import (
    ExecutionStatus,
    ExecutionErrorCode,
    ExchangeConnectionStatus,
    ExchangeType,
    FillStatus
)

# Event enums
from .event import (
    EventType,
    Side
)

# Order enums
from .order import (
    OrderType,
    OrderStatus,
    OrderCommand,
    order_type_map,
    order_status_map,
    order_command_map,
    VALID_ORDER_TRANSITIONS
)

__all__ = [
    # Portfolio enums
    'PortfolioState',
    'PositionSide',
    'TransactionType',
    'PortfolioEventType',
    'CashOperationType',
    'PositionEvent',
    'MetricsPeriod',
    'TransactionState',

    # Execution enums
    'ExecutionStatus',
    'ExecutionErrorCode',
    'ExchangeConnectionStatus',
    'ExchangeType',
    'FillStatus',

    # Event enums
    'EventType',
    'Side',


    # Order enums
    'OrderType',
    'OrderStatus',
    'OrderCommand',
    'order_type_map',
    'order_status_map',
    'order_command_map',
    'VALID_ORDER_TRANSITIONS'
]
