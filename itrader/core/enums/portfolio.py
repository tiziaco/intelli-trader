"""
Portfolio-related enums for the iTrader system.
"""

from enum import Enum


class PortfolioState(Enum):
    """Portfolio lifecycle states."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class PositionSide(Enum):
    """Position side (long/short)."""
    LONG = "long"
    SHORT = "short"


class TransactionType(Enum):
    """Transaction types."""
    BUY = "buy"
    SELL = "sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    FEE = "fee"


class PortfolioEventType(Enum):
    """Portfolio event types for tracking changes."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATE_CHANGED = "state_changed"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
