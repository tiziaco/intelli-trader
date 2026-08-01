"""Signal Storage module for the iTrader trading system (Plan 05-03, SIG-02).

Pluggable storage for captured strategy signals (D-07), mirroring the
``order_handler`` storage seam:
- SignalStore: the abstract backend interface
- InMemorySignalStore: fast in-memory backend for backtesting/testing
- build_signal_store: environment-keyed construction

Also hosts the environment-keyed construction of the durable strategy-instance
registry (build_strategy_registry_store), which the handler owns from
(environment, sql_engine) the same way it owns its signal store.
"""

from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore
from itrader.strategy_handler.storage.registry_storage_factory import (
    build_strategy_registry_store,
)
from itrader.strategy_handler.storage.storage_factory import build_signal_store

__all__ = [
    'SignalStore',
    'InMemorySignalStore',
    'build_signal_store',
    'build_strategy_registry_store',
]
