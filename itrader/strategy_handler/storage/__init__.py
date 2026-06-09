"""Signal Storage module for the iTrader trading system (Plan 05-03, SIG-02).

Pluggable storage for captured strategy signals (D-07), mirroring the
``order_handler`` storage seam:
- SignalStore: the abstract backend interface
- InMemorySignalStore: fast in-memory backend for backtesting/testing
- SignalStorageFactory: environment-keyed construction
"""

from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore
from itrader.strategy_handler.storage.storage_factory import SignalStorageFactory

__all__ = [
    'SignalStore',
    'InMemorySignalStore',
    'SignalStorageFactory',
]
