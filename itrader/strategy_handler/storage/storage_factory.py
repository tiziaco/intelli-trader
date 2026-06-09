"""SignalStorageFactory (Plan 05-03, SIG-02, D-07).

Environment-keyed construction of a ``SignalStore``, mirroring
``OrderStorageFactory``. v1.1 ships the in-memory backend only — a persistent
('live') backend is deferred, so the factory rejects it loudly with a
``ConfigurationError`` rather than silently degrading.

4-space indentation (matches the ``order_handler/storage/`` siblings).
"""

from typing import Optional

from itrader.core.exceptions import ConfigurationError
from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore


class SignalStorageFactory:
    """Factory for creating ``SignalStore`` instances based on environment.

    - ``InMemorySignalStore`` for backtesting/testing (fast, no persistence).
    - A persistent backend for live trading is deferred to a later milestone;
      ``'live'`` raises ``ConfigurationError`` until it lands.
    """

    @staticmethod
    def create(environment: str, db_url: Optional[str] = None) -> SignalStore:
        """Create a ``SignalStore`` for the given environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'test', 'live').
        db_url : str, optional
            Reserved for a future persistent backend; unused in v1.1.

        Returns
        -------
        SignalStore
            Appropriate store implementation for the environment.

        Raises
        ------
        NotImplementedError
            If the environment is 'live' (no persistent backend in v1.1).
        ConfigurationError
            If the environment is otherwise unknown.
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return InMemorySignalStore()
        elif environment == 'live':
            # IN-02: align the deferred-backend exception type with
            # OrderStorageFactory (which raises NotImplementedError for an
            # unimplemented live backend). A future live wiring can then catch
            # one exception type for both storage seams rather than catching
            # ConfigurationError for signals and NotImplementedError for orders.
            raise NotImplementedError(
                "No persistent SignalStore backend in v1.1 — 'live' signal "
                "storage is deferred to a later milestone"
            )
        else:
            raise ConfigurationError(
                "environment", environment,
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'test'"
            )

    @staticmethod
    def create_in_memory() -> InMemorySignalStore:
        """Create an in-memory store directly (testing/backtesting convenience).

        Returns
        -------
        InMemorySignalStore
            In-memory store instance.
        """
        return InMemorySignalStore()
