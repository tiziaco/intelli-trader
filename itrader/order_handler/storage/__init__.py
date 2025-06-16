"""
Order Storage module for the iTrader trading system.

This module provides different storage implementations for order management:
- InMemoryOrderStorage: Fast in-memory storage for backtesting
- PostgreSQLOrderStorage: Persistent database storage for live trading
"""

from ..base import OrderStorage
from .in_memory_storage import InMemoryOrderStorage
from .storage_factory import OrderStorageFactory

# PostgreSQL storage is imported on-demand to avoid dependency issues
# from .postgresql_storage import PostgreSQLOrderStorage

__all__ = [
    'OrderStorage',
    'InMemoryOrderStorage', 
    'OrderStorageFactory'
]
