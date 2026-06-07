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


class SizingPolicyViolation(OrderError):
    """Raised when a sizing/SLTP policy parameter or resolution violates its contract.

    D-06 fail-loud: invalid policy params (fraction outside (0, 1], risk_pct <= 0,
    step_size <= 0, exit_fraction outside (0, 1]) raise at construction; resolution
    violations (RiskPercent without a usable stop) raise at resolve time. The
    message names the policy, the field, and the offending value.
    """

    def __init__(self, message: str):
        super().__init__(message)
