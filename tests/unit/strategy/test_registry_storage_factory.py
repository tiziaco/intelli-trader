"""StrategyRegistryStorageFactory tests (Plan 10.1-01, DECOMP-01a, D-09/D-21).

These pin the environment-keyed construction of the durable strategy registry that
``StrategiesHandler.__init__`` now derives for itself, replacing the post-construction
attribute injection that used to live in ``build_live_system``:

- ``'backtest'``/``'test'`` yield ``None`` — the backtest path carries no durable
  registry and every persist arm in the handler stays a clean no-op.
- ``'live'`` without a wired SQL spine likewise yields ``None`` (mirrors the existing
  ``if system_db_backend is not None:`` gate in the live composition root).
- ``'live'`` against a spine whose ``strategy_registry`` table is UNPROVISIONED is the
  D-21 first-start state: ``None`` plus a WARNING naming the unapplied Alembic chain.
  This is the behaviour relocated verbatim out of ``live_trading_system.py``.
- An unknown environment raises ``ConfigurationError`` (same shape as
  ``SignalStorageFactory``).

The spine is stubbed to a real in-memory SQLite engine so the ``has_table`` probe is
genuinely exercised without a Postgres — the factory only ever touches ``.engine`` and
``.metadata`` on it. 4-space indentation (tests house style).
"""

import logging
from dataclasses import dataclass

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine
from sqlalchemy.engine import Engine

from itrader.core.exceptions import ConfigurationError
from itrader.strategy_handler.storage import StrategyRegistryStorageFactory

pytestmark = pytest.mark.unit


@dataclass
class _StubSpine:
    """Minimal stand-in for ``SqlEngine`` — the factory reads exactly these two."""

    engine: Engine
    metadata: MetaData


def _spine(*, provisioned: bool) -> _StubSpine:
    """An in-memory SQLite spine, optionally carrying a ``strategy_registry`` table."""
    engine = create_engine("sqlite://")
    if provisioned:
        probe = MetaData()
        Table(
            "strategy_registry",
            probe,
            Column("strategy_name", String, primary_key=True),
        )
        probe.create_all(engine)
    # A SEPARATE MetaData for the store itself: build_strategy_registry_tables
    # registers its two tables here, and reusing the probe's would collide.
    return _StubSpine(engine=engine, metadata=MetaData())


def test_backtest_environment_yields_no_registry() -> None:
    assert StrategyRegistryStorageFactory.create("backtest") is None


def test_test_environment_yields_no_registry() -> None:
    assert StrategyRegistryStorageFactory.create("test") is None


def test_live_without_sql_engine_yields_no_registry() -> None:
    # No SQL spine was wired — mirrors the `system_db_backend is not None` gate.
    assert StrategyRegistryStorageFactory.create("live", sql_engine=None) is None


def test_live_first_start_unprovisioned_table_warns_and_yields_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # D-21 first-start: the table is absent, so there provably are no rows to lose.
    # None + a WARNING naming the Alembic chain, NOT a loud D-19 failure.
    with caplog.at_level(logging.WARNING):
        store = StrategyRegistryStorageFactory.create(
            "live", sql_engine=_spine(provisioned=False)
        )
    assert store is None
    assert "strategy_registry" in caplog.text
    assert "Alembic" in caplog.text


def test_live_with_provisioned_table_builds_store_over_that_spine() -> None:
    spine = _spine(provisioned=True)
    store = StrategyRegistryStorageFactory.create("live", sql_engine=spine)
    assert store is not None
    # Composed over the SAME spine it was handed (never a second engine).
    assert store.backend is spine
    assert store.engine is spine.engine


def test_environment_key_is_case_insensitive() -> None:
    assert StrategyRegistryStorageFactory.create("BACKTEST") is None


def test_unknown_environment_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError) as exc:
        StrategyRegistryStorageFactory.create("banana")
    assert "banana" in str(exc.value)
