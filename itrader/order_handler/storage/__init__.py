"""
Order Storage module for the iTrader trading system.

This module provides different storage implementations for order management:
- InMemoryOrderStorage: Fast in-memory storage for backtesting
- CachedSqlOrderStorage wrapping SqlOrderStorage: persistent storage for live
  trading, built by ``build_order_storage``'s ``live`` arm, which lazy-imports
  the SQL backend inside the branch so the backtest import path stays SQL-free.
"""

from ..base import OrderStorage
from .in_memory_storage import InMemoryOrderStorage
from .storage_factory import build_order_storage

__all__ = [
    'OrderStorage',
    'InMemoryOrderStorage', 
    'build_order_storage',
]
