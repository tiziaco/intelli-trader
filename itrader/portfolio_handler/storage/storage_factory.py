"""Factory for PortfolioStateStorage backends (D-09, M2-08).

Routes by environment: backtest/test -> in-memory (UNCHANGED — oracle inertness),
live -> ``SqlPortfolioStateStorage`` on the shared SQL spine (OPS-02, D-06), unknown ->
ValueError with the supported-environments message. The ``SqlPortfolioStateStorage``
import is lazy (inside the ``'live'`` arm) so the backtest import path stays SQL-free
(GATE-01 inertness). No ``'postgresql'`` arm — the live arm IS the Postgres path (D-06).
"""

import uuid
from typing import Optional, TYPE_CHECKING

from ..base import PortfolioStateStorage
from .in_memory_storage import InMemoryPortfolioStateStorage

if TYPE_CHECKING:
    from itrader.storage import SqlBackend


class PortfolioStateStorageFactory:
    """
    Factory class for creating PortfolioStateStorage instances based on environment.

    This factory enables seamless switching between storage backends:
    - InMemoryPortfolioStateStorage for backtesting (fast, no persistence)
    - PostgreSQL backend for live trading (deferred to D-sql)
    """

    @staticmethod
    def create(environment: str, db_url: Optional[str] = None,
               max_snapshots: int = 10000, *,
               backend: "Optional[SqlBackend]" = None,
               portfolio_id: Optional[uuid.UUID] = None,
               ) -> PortfolioStateStorage:
        """
        Create a PortfolioStateStorage instance based on the environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'live', 'test')
        db_url : str, optional
            Legacy parameter (predates ``SqlSettings``); unused by the live arm now —
            the live backend takes a shared ``SqlBackend`` instead (research §Factory wiring).
        max_snapshots : int, optional
            Snapshot-retention bound for the in-memory backend's bounded deque
            (D-03). WR-01: threaded through so the caller's retention bound (e.g.
            ``MetricsManager.max_snapshots``) actually governs the live deque
            instead of silently diverging from a hardcoded default.
        backend : SqlBackend, optional
            The shared SQL spine for the ``'live'`` arm (one engine/MetaData co-registering
            all operational tables). If omitted, a default ``SqlBackend(SqlSettings.default())``
            is built. Phase 4 wires the real Postgres backend at the live composition root.
        portfolio_id : uuid.UUID, optional
            REQUIRED for the ``'live'`` arm — the SQL backend binds it and scopes every query
            to it (Pitfall 1; the ABC has no ``portfolio_id`` parameter).

        Returns
        -------
        PortfolioStateStorage
            Appropriate storage implementation for the environment

        Raises
        ------
        ValueError
            If environment is not supported or required parameters are missing
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)
        elif environment == 'live':
            if portfolio_id is None:
                raise ValueError(
                    "portfolio_id is required for the live SQL portfolio-state backend"
                )
            # D-06 / GATE-01: lazy import keeps the SQL backend off the backtest
            # import path. The live arm IS the Postgres path — no 'postgresql' arm.
            from itrader.config.sql import SqlSettings
            from itrader.storage import SqlBackend
            from .sql_storage import SqlPortfolioStateStorage

            sql_backend = (
                backend if backend is not None
                else SqlBackend(SqlSettings.default())
            )
            return SqlPortfolioStateStorage(sql_backend, portfolio_id)
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
