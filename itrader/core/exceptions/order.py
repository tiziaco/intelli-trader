"""
Order-specific exceptions for the iTrader system.
"""

from .base import ITraderError


class OrderError(ITraderError):
    """Base exception for order-related errors."""
    pass


class UnsizedSignalError(OrderError):
    """Raised when an order is constructed from a signal that was never sized."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Cannot create order from unsized signal for {ticker}")
