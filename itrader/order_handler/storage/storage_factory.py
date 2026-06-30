from typing import TYPE_CHECKING, Optional

from itrader.core.exceptions import ConfigurationError

from ..base import OrderStorage
from .in_memory_storage import InMemoryOrderStorage

if TYPE_CHECKING:
    from itrader.storage import SqlBackend


class OrderStorageFactory:
    """
    Factory class for creating OrderStorage instances based on environment.

    This factory enables seamless switching between storage backends:
    - InMemoryOrderStorage for backtesting (fast, no persistence)
    - SqlOrderStorage for live trading (persistent, audit trail) — D-06: the
      ``'live'`` arm routes to the SQL spine backend; there is deliberately NO
      ``'postgresql'`` arm.
    """

    @staticmethod
    def create(
        environment: str, backend: "Optional[SqlBackend]" = None
    ) -> OrderStorage:
        """
        Create an OrderStorage instance based on the environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'live', 'test')
        backend : SqlBackend, optional
            The shared SQL spine for the 'live' arm (D-06). When omitted, a default
            ``SqlBackend(SqlSettings.default())`` is built; Phase 4 injects the shared
            operational backend at the live composition root.

        Returns
        -------
        OrderStorage
            Appropriate storage implementation for the environment

        Raises
        ------
        ConfigurationError
            If environment is not supported
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return InMemoryOrderStorage()
        elif environment == 'live':
            # Import here so the backtest import path stays SQL-free (GATE-01 quarantine).
            from itrader.config.sql import SqlSettings
            from itrader.storage import SqlBackend

            from .cached_sql_storage import CachedSqlOrderStorage
            from .sql_storage import SqlOrderStorage

            resolved = backend if backend is not None else SqlBackend(SqlSettings.default())
            # D-04 — the live arm returns the cache wrapper composing the untouched SQL store.
            return CachedSqlOrderStorage(SqlOrderStorage(resolved))
        else:
            raise ConfigurationError(
                "environment", environment,
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'live', 'test'"
            )
    
    @staticmethod
    def create_in_memory() -> InMemoryOrderStorage:
        """
        Create an in-memory storage directly.
        
        Convenience method for testing and backtesting scenarios.
        
        Returns
        -------
        InMemoryOrderStorage
            In-memory storage instance
        """
        return InMemoryOrderStorage()
