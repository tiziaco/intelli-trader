from typing import TYPE_CHECKING, Optional

from itrader.core.exceptions import ConfigurationError

from ..base import OrderStorage
from .in_memory_storage import InMemoryOrderStorage

if TYPE_CHECKING:
    from itrader.storage import SqlEngine


def build_order_storage(
    environment: str, sql_engine: "Optional[SqlEngine]" = None
) -> OrderStorage:
    """Build the ``OrderStorage`` backend this environment selects.

    A module-level function rather than a class of static methods: the selection is
    DATA (an environment string picks a branch) and there is no state to hold, so a
    class would be ceremony around a call.

    - ``'backtest'``/``'test'`` -> ``InMemoryOrderStorage`` (fast, no persistence).
    - ``'live'`` -> ``CachedSqlOrderStorage`` over ``SqlOrderStorage`` on the SQL spine
      (persistent, audit trail). There is deliberately NO ``'postgresql'`` arm.

    Parameters
    ----------
    environment : str
        The environment type ('backtest', 'live', 'test')
    sql_engine : SqlEngine, optional
        The shared SQL spine for the 'live' arm. When omitted, a default
        ``SqlEngine(SqlSettings.default())`` is built; the live composition root
        injects the shared operational engine.

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
    if environment == 'live':
        # Import here so the backtest import path stays SQL-free (GATE-01 quarantine).
        from itrader.config.sql import SqlSettings
        from itrader.storage import SqlEngine

        from .cached_sql_storage import CachedSqlOrderStorage
        from .sql_storage import SqlOrderStorage

        resolved = sql_engine if sql_engine is not None else SqlEngine(SqlSettings.default())
        # The live arm returns the cache wrapper composing the untouched SQL store.
        return CachedSqlOrderStorage(SqlOrderStorage(resolved))
    raise ConfigurationError(
        "environment", environment,
        f"Unknown environment: {environment}. "
        f"Supported environments are: 'backtest', 'live', 'test'"
    )
