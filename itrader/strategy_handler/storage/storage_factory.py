"""SignalStorageFactory (Plan 05-03 / 03-04, SIG-02 / OPS-03, D-06/D-07).

Environment-keyed construction of a ``SignalStore``, mirroring
``OrderStorageFactory``. ``'backtest'``/``'test'`` stay on the in-memory backend
(zero hot-path SQL — GATE-01 inertness); the ``'live'`` arm now routes to the
concrete Postgres-backed ``SqlSignalStorage`` (OPS-03, D-06). There is NO
``'postgresql'`` arm — the SQL backend is selected by the ``'live'`` environment
key alone (mirrors the existing factory layout).

The SQL imports (``SqlSignalStorage``/``SqlEngine``/``SqlSettings``) are LAZY,
performed INSIDE the ``'live'`` branch, so importing this factory on the backtest
path never pulls SQLAlchemy (D-06 quarantine — GATE-01 inertness).

4-space indentation (matches the ``order_handler/storage/`` siblings).
"""

from typing import TYPE_CHECKING, Optional

from itrader.core.exceptions import ConfigurationError
from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore

if TYPE_CHECKING:
    from itrader.storage import SqlEngine


class SignalStorageFactory:
    """Factory for creating ``SignalStore`` instances based on environment.

    - ``InMemorySignalStore`` for backtesting/testing (fast, no persistence).
    - ``SqlSignalStorage`` (Postgres-backed, on the shared SQL spine) for live
      trading — built lazily so the backtest path stays SQL-free (D-06).
    """

    @staticmethod
    def create(
        environment: str,
        db_url: Optional[str] = None,
        sql_engine: "SqlEngine | None" = None,
    ) -> SignalStore:
        """Create a ``SignalStore`` for the given environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'test', 'live').
        db_url : str, optional
            Reserved for a future persistent backend; unused.
        sql_engine : SqlEngine, optional
            An already-constructed shared spine to compose the live store over.
            When omitted, the ``'live'`` arm builds its own from
            ``SqlSettings.default()`` (the wiring caller injects the real
            Postgres engine in the live composition root).

        Returns
        -------
        SignalStore
            Appropriate store implementation for the environment.

        Raises
        ------
        ConfigurationError
            If the environment is unknown.
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return InMemorySignalStore()
        elif environment == 'live':
            # D-06 — lazy imports keep SQLAlchemy off the backtest import path.
            from itrader.config.sql import SqlSettings
            from itrader.storage import SqlEngine
            from itrader.strategy_handler.storage.cached_sql_storage import (
                CachedSqlSignalStorage,
            )
            from itrader.strategy_handler.storage.sql_storage import (
                SqlSignalStorage,
            )

            if sql_engine is None:
                sql_engine = SqlEngine(SqlSettings.default())
            # Wrap the untouched system-of-record store in the live-only
            # store-first cache mirror (D-04 / Pitfall 8). The wrapper import
            # stays INSIDE this branch so the backtest path pulls no SQLAlchemy
            # nor the wrapper (GATE-01 quarantine).
            return CachedSqlSignalStorage(SqlSignalStorage(sql_engine))
        else:
            raise ConfigurationError(
                "environment", environment,
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'test', 'live'"
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
