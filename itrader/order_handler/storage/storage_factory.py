from typing import Optional
from ..base import OrderStorage
from .in_memory_storage import InMemoryOrderStorage


class OrderStorageFactory:
    """
    Factory class for creating OrderStorage instances based on environment.
    
    This factory enables seamless switching between storage backends:
    - InMemoryOrderStorage for backtesting (fast, no persistence)
    - PostgreSQLOrderStorage for live trading (persistent, audit trail)
    """
    
    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> OrderStorage:
        """
        Create an OrderStorage instance based on the environment.
        
        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'live', 'test')
        db_url : str, optional
            Database URL for persistent storage (required for 'live' environment)
            
        Returns
        -------
        OrderStorage
            Appropriate storage implementation for the environment
            
        Raises
        ------
        ValueError
            If environment is not supported or required parameters are missing
        """
        environment = environment.lower()
        
        if environment in ('backtest', 'test'):
            return InMemoryOrderStorage()
        elif environment == 'live':
            if not db_url:
                raise ValueError("Database URL is required for live environment")
            # Import here to avoid circular imports and optional dependencies
            from .postgresql_storage import PostgreSQLOrderStorage
            return PostgreSQLOrderStorage(db_url)
        else:
            raise ValueError(
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
