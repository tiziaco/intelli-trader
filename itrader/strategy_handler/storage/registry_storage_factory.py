"""StrategyRegistryStorageFactory (Plan 10.1-01, DECOMP-01a, D-09/D-21).

Environment-keyed construction of the durable strategy-instance registry, mirroring
``SignalStorageFactory`` next door. ``'backtest'``/``'test'`` carry no registry at all;
the ``'live'`` arm builds a ``StrategyRegistryStore`` over the shared SQL spine. There
is NO ``'postgresql'`` arm — the SQL backend is selected by the ``'live'`` environment
key alone (mirrors the existing factory layout).

This factory exists so ``StrategiesHandler`` can OWN its ``registry_store`` from
``(environment, sql_engine)`` at construction time, ending the ``None``-then-assign
pattern the live composition root used to perform after the handler was already built.

Returns ``None`` rather than a null-object store on the storeless arms: every persist
arm in the handler already short-circuits on ``registry_store is not None``, so a null
object would be NEW behaviour, not a refactor.

The SQL imports (``StrategyRegistryStore``, SQLAlchemy's ``inspect``) are LAZY,
performed INSIDE the ``'live'`` branch, so importing this factory on the backtest path
never pulls SQLAlchemy (GATE-01 inertness — ``itrader.storage.strategy_registry_store``
is in the ``test_okx_inertness.py`` ``_FORBIDDEN`` tuple).

4-space indentation (matches the ``strategy_handler/storage/`` siblings — the
DIRECTORY, not the surrounding tab-indented ``strategy_handler/`` package).
"""

from typing import TYPE_CHECKING

from itrader.core.exceptions import ConfigurationError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.storage import SqlEngine
    from itrader.storage.strategy_registry_store import StrategyRegistryStore


class StrategyRegistryStorageFactory:
    """Factory for the durable ``StrategyRegistryStore``, keyed on environment.

    - ``None`` for backtesting/testing (no durable registry; persist arms no-op).
    - ``StrategyRegistryStore`` over the injected spine for live trading — built
      lazily so the backtest path stays SQL-free (GATE-01).
    """

    @staticmethod
    def create(
        environment: str,
        sql_engine: "SqlEngine | None" = None,
    ) -> "StrategyRegistryStore | None":
        """Create the registry store for the given environment.

        Parameters
        ----------
        environment : str
            The environment type ('backtest', 'test', 'live').
        sql_engine : SqlEngine, optional
            The already-constructed shared spine to compose the live store over.
            ``None`` means no SQL spine was wired, which yields ``None`` even on
            the ``'live'`` arm — matching the ``system_db_backend is not None``
            gate the live composition root already applies.

        Returns
        -------
        StrategyRegistryStore | None
            The durable registry, or ``None`` when this environment carries none
            (backtest/test), when no spine was wired, or on the D-21 first-start
            state below.

        Raises
        ------
        ConfigurationError
            If the environment is unknown.
        """
        environment = environment.lower()

        if environment in ('backtest', 'test'):
            return None
        elif environment == 'live':
            if sql_engine is None:
                # WR-02 — this arm is LOUD for the same reason the D-21 has-table arm
                # below is: both return None, and a None registry makes every persist
                # arm in the control plane a clean no-op, so every enable / disable /
                # subscribe / add / reconfigure applies in memory and vanishes on
                # restart with no audit trail. Today's wiring makes this unreachable
                # (build_live_system falls back to environment='backtest' when the
                # credential probe fails), but the factory is now the SINGLE owner of
                # this decision and is a public seam — the invariant belongs here, not
                # in one caller's coincidental gating.
                #
                # Names the CONDITION only: no credentials, no connection string, no
                # sql_engine repr (the D-21 arm logs no connection detail either).
                logger = get_itrader_logger().bind(
                    component="StrategyRegistryStorageFactory")
                logger.warning(
                    "environment='live' but no SQL spine was wired — the strategy "
                    "registry is DISABLED. Every STRATEGY_COMMAND verb (enable, disable, "
                    "subscribe, add, reconfigure) will apply IN MEMORY ONLY and is lost "
                    "on restart.")
                return None
            # GATE-01 — lazy imports keep SQLAlchemy and the registry store off the
            # backtest import path.
            from sqlalchemy import inspect as _sa_inspect

            from itrader.storage.strategy_registry_store import StrategyRegistryStore

            # An UNPROVISIONED registry table is not a D-19 infrastructure failure — it
            # is the D-21 first-start state expressed at the schema level. The
            # distinction is exact rather than convenient: D-19's loud arm exists to
            # stop a boot with zero strategies WHILE ROWS EXIST, and without the table
            # there provably are no rows, so returning None here cannot produce the
            # outcome D-19 forbids. Probed explicitly with has_table instead of
            # swallowing the query's error, so a genuine store fault (connection lost,
            # permissions, corrupt data) still PROPAGATES loud out of the caller's
            # rehydrate — an exception-swallow could not tell those apart. Logged at
            # WARNING, not silently: on a live deployment an absent table means the
            # Alembic chain was never run, which the operator needs to see.
            if not _sa_inspect(sql_engine.engine).has_table("strategy_registry"):
                logger = get_itrader_logger().bind(
                    component="StrategyRegistryStorageFactory")
                logger.warning(
                    "strategy_registry table absent — skipping strategy rehydrate and booting "
                    "with ZERO strategies (D-21 first-start). On a live deployment this means "
                    "the Alembic migration chain has not been applied to this database.")
                return None
            return StrategyRegistryStore(sql_engine)
        else:
            raise ConfigurationError(
                "environment", environment,
                f"Unknown environment: {environment}. "
                f"Supported environments are: 'backtest', 'test', 'live'"
            )
