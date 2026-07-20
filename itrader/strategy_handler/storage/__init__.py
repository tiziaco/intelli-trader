"""Signal Storage module for the iTrader trading system (Plan 05-03, SIG-02).

Pluggable storage for captured strategy signals (D-07), mirroring the
``order_handler`` storage seam:
- SignalStore: the abstract backend interface
- InMemorySignalStore: fast in-memory backend for backtesting/testing
- SignalStorageFactory: environment-keyed construction

Also hosts the environment-keyed construction of the durable strategy-instance
registry (StrategyRegistryStorageFactory, DECOMP-01a), which the handler owns from
(environment, sql_engine) the same way it owns its signal store.
"""

from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore
from itrader.strategy_handler.storage.registry_storage_factory import (
    StrategyRegistryStorageFactory,
)
from itrader.strategy_handler.storage.storage_factory import SignalStorageFactory

__all__ = [
    'SignalStore',
    'InMemorySignalStore',
    'SignalStorageFactory',
    'StrategyRegistryStorageFactory',
]
