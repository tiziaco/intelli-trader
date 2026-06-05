"""
Cash subdomain package.

Re-exports the public cash manager + its CashOperation entity so consumer import
paths stay short after the D-11 subdomain reorg (pure move, no behavior change).
"""

from .cash_manager import CashManager, CashOperation

__all__ = ["CashManager", "CashOperation"]
