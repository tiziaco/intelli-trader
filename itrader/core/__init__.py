"""
Core module for the iTrader system.

This module provides the foundational components used throughout the system:
- Exception classes organized by domain
- Enum definitions for system-wide constants
- Common utilities and types
"""

# Import all exceptions and enums for easy access
from .exceptions import *
from .enums import *

# Re-export everything for backward compatibility and convenience
__all__ = [
    # All exceptions are exported via exceptions.__all__
    # All enums are exported via enums.__all__
]

# Extend __all__ with imported items
from .exceptions import __all__ as exceptions_all
from .enums import __all__ as enums_all

__all__.extend(exceptions_all)
__all__.extend(enums_all)
