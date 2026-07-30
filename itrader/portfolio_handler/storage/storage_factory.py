"""Selection of the ``PortfolioStateStorage`` backend, keyed on environment.

Routes by environment: backtest/test -> in-memory (oracle inertness), live ->
``SqlPortfolioStateStorage`` on the shared SQL spine, unknown -> ``ConfigurationError``
naming the supported environments. The ``SqlPortfolioStateStorage`` import is lazy
(inside the ``'live'`` arm) so the backtest import path stays SQL-free (GATE-01
inertness). No ``'postgresql'`` arm — the live arm IS the Postgres path.
"""

import uuid
from typing import Optional, TYPE_CHECKING

from itrader.core.exceptions import ConfigurationError

from ..base import PortfolioStateStorage
from .in_memory_storage import InMemoryPortfolioStateStorage

if TYPE_CHECKING:
    from itrader.storage import SqlEngine


def build_portfolio_state_storage(
        environment: str, db_url: Optional[str] = None,
        max_snapshots: int = 10000, *,
        sql_engine: "Optional[SqlEngine]" = None,
        portfolio_id: Optional[uuid.UUID] = None,
        ) -> PortfolioStateStorage:
    """Build the ``PortfolioStateStorage`` backend this environment selects.

    A module-level function rather than a class of static methods: the selection is
    DATA (an environment string picks a branch) and there is no state to hold.

    - ``InMemoryPortfolioStateStorage`` for backtesting (fast, no persistence).
    - ``CachedSqlPortfolioStateStorage`` over ``SqlPortfolioStateStorage`` on the shared
      SQL spine for live trading; no separate ``'postgresql'`` arm.

    Parameters
    ----------
    environment : str
        The environment type ('backtest', 'live', 'test')
    db_url : str, optional
        Legacy parameter (predates ``SqlSettings``); unused by the live arm now —
        the live backend takes a shared ``SqlEngine`` instead (research §Factory wiring).
    max_snapshots : int, optional
        Snapshot-retention bound for the in-memory backend's bounded deque
        (D-03). WR-01: threaded through so the caller's retention bound (e.g.
        ``MetricsManager.max_snapshots``) actually governs the live deque
        instead of silently diverging from a hardcoded default.
    sql_engine : SqlEngine, optional
        The shared SQL spine for the ``'live'`` arm (one engine/MetaData co-registering
        all operational tables). If omitted, a default ``SqlEngine(SqlSettings.default())``
        is built. Phase 4 wires the real Postgres engine at the live composition root.
    portfolio_id : uuid.UUID, optional
        REQUIRED for the ``'live'`` arm — the SQL backend binds it and scopes every query
        to it (Pitfall 1; the ABC has no ``portfolio_id`` parameter).

    Returns
    -------
    PortfolioStateStorage
        Appropriate storage implementation for the environment

    Raises
    ------
    ConfigurationError
        If environment is not supported or required parameters are missing (WR-04 —
        typed exception matching the sibling Order/Signal factories, per the CLAUDE.md
        "raise typed exceptions, not bare ``Exception``" convention).
    """
    environment = environment.lower()

    if environment in ('backtest', 'test'):
        return InMemoryPortfolioStateStorage(max_snapshots=max_snapshots)
    if environment == 'live':
        if portfolio_id is None:
            raise ConfigurationError(
                "portfolio_id", None,
                "portfolio_id is required for the live SQL portfolio-state backend"
            )
        # GATE-01: lazy import keeps the SQL backend off the backtest import path.
        # The live arm IS the Postgres path — no 'postgresql' arm.
        from itrader.config.sql import SqlSettings
        from itrader.storage import SqlEngine
        from .cached_sql_storage import CachedSqlPortfolioStateStorage
        from .sql_storage import SqlPortfolioStateStorage

        resolved = (
            sql_engine if sql_engine is not None
            else SqlEngine(SqlSettings.default())
        )
        # The live arm constructs the store-first cache wrapper over the untouched store.
        return CachedSqlPortfolioStateStorage(
            SqlPortfolioStateStorage(resolved, portfolio_id),
            max_snapshots=max_snapshots,
        )
    raise ConfigurationError(
        "environment", environment,
        f"Unknown environment: {environment}. "
        f"Supported environments are: 'backtest', 'live', 'test'"
    )
