"""Portfolio state storage module for the iTrader trading system (M2-08).

Provides pluggable storage implementations for portfolio-manager state,
mirroring the order-storage seam:
- InMemoryPortfolioStateStorage: fast in-memory storage for backtesting
- PostgreSQL backend: persistent storage for live trading (deferred to D-sql)
"""

from ..base import PortfolioStateStorage, IdLike
from .in_memory_storage import InMemoryPortfolioStateStorage
from .storage_factory import build_portfolio_state_storage

__all__ = [
    'PortfolioStateStorage',
    'IdLike',
    'InMemoryPortfolioStateStorage',
    'build_portfolio_state_storage',
]
