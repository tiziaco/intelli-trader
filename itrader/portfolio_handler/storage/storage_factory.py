"""Factory for PortfolioStateStorage backends (D-09, M2-08).

Copies ``OrderStorageFactory.create`` verbatim and renames it for portfolio
state: backtest/test -> in-memory, live -> deferred to D-sql (raise), unknown ->
ValueError with the supported-environments message.
"""

from typing import Optional

from ..base import PortfolioStateStorage
from .in_memory_storage import InMemoryPortfolioStateStorage


class PortfolioStateStorageFactory:
    """
    Factory class for creating PortfolioStateStorage instances based on environment.

    This factory enables seamless switching between storage backends:
    - InMemoryPortfolioStateStorage for backtesting (fast, no persistence)
    - PostgreSQL backend for live trading (deferred to D-sql)
    """

    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> PortfolioStateStorage:
        """
        Create a PortfolioStateStorage instance based on the environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'live', 'test')
        db_url : str, optional
            Database URL for persistent storage (required for 'live' environment)

        Returns
        -------
        PortfolioStateStorage
            Appropriate storage implementation for the environment

        Raises
        ------
        ValueError
            If environment is not supported or required parameters are missing
        NotImplementedError
            If the 'live' environment is requested (PostgreSQL backend deferred to D-sql)
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return InMemoryPortfolioStateStorage()
        elif environment == 'live':
            if not db_url:
                raise ValueError("Database URL is required for live environment")
            # D-sql: PostgreSQL portfolio-state backend deferred — does not exist yet.
            raise NotImplementedError(
                "PortfolioStateStorage live backend deferred to D-sql"
            )
        else:
            raise ValueError(
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'live', 'test'"
            )

    @staticmethod
    def create_in_memory() -> InMemoryPortfolioStateStorage:
        """
        Create an in-memory storage directly.

        Convenience method for testing and backtesting scenarios.

        Returns
        -------
        InMemoryPortfolioStateStorage
            In-memory storage instance
        """
        return InMemoryPortfolioStateStorage()
