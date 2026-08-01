"""Selection of the ``SignalStore`` backend, keyed on environment.

Mirrors ``build_order_storage``. ``'backtest'``/``'test'`` stay on the in-memory
backend (zero hot-path SQL — GATE-01 inertness); the ``'live'`` arm routes to the
concrete Postgres-backed ``SqlSignalStorage``. There is NO ``'postgresql'`` arm — the
SQL backend is selected by the ``'live'`` environment key alone.

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


def build_signal_store(
    environment: str,
    db_url: Optional[str] = None,
    sql_engine: "SqlEngine | None" = None,
) -> SignalStore:
    """Build the ``SignalStore`` backend this environment selects.

    A module-level function rather than a class of static methods: the selection is
    DATA (an environment string picks a branch) and there is no state to hold.

    - ``InMemorySignalStore`` for backtesting/testing (fast, no persistence).
    - ``CachedSqlSignalStorage`` over ``SqlSignalStorage`` (Postgres-backed, on the
      shared SQL spine) for live trading — built lazily so the backtest path stays
      SQL-free.

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
    if environment == 'live':
        # Lazy imports keep SQLAlchemy off the backtest import path.
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
        # Wrap the untouched system-of-record store in the live-only store-first cache
        # mirror. The wrapper import stays INSIDE this branch so the backtest path
        # pulls neither SQLAlchemy nor the wrapper (GATE-01 quarantine).
        return CachedSqlSignalStorage(SqlSignalStorage(sql_engine))
    raise ConfigurationError(
        "environment", environment,
        f"Unknown environment: {environment}. "
        f"Supported environments are: 'backtest', 'test', 'live'"
    )
