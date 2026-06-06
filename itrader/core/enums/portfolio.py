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

    @classmethod
    def _missing_(cls, value: object) -> "TransactionType":
        """Case-insensitive string parse; raise a clear f-string error.

        Replaces the scattered ``transaction_type_map.get(action)`` dict and
        the buggy ``raise ValueError('Value %s', x)`` printf-tuple form in
        ``transaction.py`` (D-04). Accepts the upstream uppercase ``action``
        strings (e.g. ``"BUY"``/``"SELL"``) the old map keyed on.
        """
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown TransactionType: {value!r}")


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


class CashOperationType(Enum):
    """Cash operation types for the portfolio cash audit trail.

    Relocated from ``cash_manager.py`` (D-04). Member values preserve the
    prior class-based definition exactly.
    """
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    TRANSACTION_DEBIT = "TRANSACTION_DEBIT"
    TRANSACTION_CREDIT = "TRANSACTION_CREDIT"
    RESERVATION = "RESERVATION"
    RELEASE_RESERVATION = "RELEASE_RESERVATION"

    @classmethod
    def _missing_(cls, value: object) -> "CashOperationType":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown CashOperationType: {value!r}")


class PositionEvent(Enum):
    """Position lifecycle events.

    Relocated from ``position_manager.py`` (D-04). Member values preserve the
    prior class-based definition exactly.
    """
    OPENED = "OPENED"
    UPDATED = "UPDATED"
    CLOSED = "CLOSED"
    MERGED = "MERGED"
    SPLIT = "SPLIT"

    @classmethod
    def _missing_(cls, value: object) -> "PositionEvent":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown PositionEvent: {value!r}")


class MetricsPeriod(Enum):
    """Reporting periods for portfolio metrics.

    Relocated from ``metrics_manager.py`` (D-04). Member values preserve the
    prior class-based definition exactly.
    """
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"
    ALL_TIME = "ALL_TIME"

    @classmethod
    def _missing_(cls, value: object) -> "MetricsPeriod":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown MetricsPeriod: {value!r}")


# Plan 05-05 (D-11): the transaction-state lifecycle enum was deleted with
# the saga machinery —
# settlements are validate-first atomic; the applied Transaction entity is
# the audit record and carries no second lifecycle.
