"""
Data-specific exceptions for the iTrader system.
"""

from .base import ITraderError


class DataError(ITraderError):
    """Base exception for price/market data errors."""
    pass


class MalformedDataError(DataError):
    """Raised when a data source's structure is invalid (e.g. missing columns)."""

    def __init__(self, source: str, details: str):
        self.source = source
        self.details = details
        super().__init__(f"Malformed data in '{source}': {details}")


class MissingPriceDataError(DataError):
    """Raised when a data source yields no usable price data."""

    def __init__(self, source: str, reason: str):
        self.source = source
        self.reason = reason
        super().__init__(f"No price data from '{source}': {reason}")
