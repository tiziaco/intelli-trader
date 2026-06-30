"""Integration suite for ``CachedSqlSignalStorage`` on testcontainers Postgres (04-03).

The live-only signal-seam wrapper (D-04) composes the untouched Phase-3
``SqlSignalStorage`` (system of record) with an in-memory ``InMemorySignalStore`` full
mirror. Signals are append-only and NEVER purged (D-02's purge gate applies to
orders/positions, not signals), so this is the simplest of the three cached-SQL wrappers:
``add`` is store-first then cache-mirror (Pitfall 8 persist-then-acknowledge), the filtered
reads serve straight from the full mirror (no read-through, no terminal gate), and the
optional ``rehydrate`` rebuilds the mirror from the store's stable-ORDER BY read.

Substrate: the ``pg_backend`` fixture (tests/integration/storage/conftest.py) — a
``SqlBackend`` over the session-scoped testcontainers Postgres DB. The arm SKIPS (never
hard-fails) when Docker is absent (D-11), inherited transitively from ``pg_engine``. The
function-scoped backend binds to the SAME database across tests, so every test uses FRESH
unique ``strategy_id`` / ``ticker`` values and asserts through the per-instance mirror (a
fresh ``InMemorySignalStore`` per wrapper) or the indexed filter queries — never a
table-wide ``get_all`` that would see sibling tests' rows.

4-space indentation (matches tests/integration/*).
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
import uuid_utils.compat as uc
from sqlalchemy import text

from itrader.core.enums import OrderType, Side
from itrader.core.ids import StrategyId
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage.cached_sql_storage import CachedSqlSignalStorage
from itrader.strategy_handler.storage.sql_storage import SqlSignalStorage

# A stable, JSON-safe params snapshot (the strategy.to_dict() shape, D-04).
_CONFIG: dict[str, Any] = {
    "fast_window": 10,
    "slow_window": 50,
    "signal_window": 9,
    "name": "SMA_MACD",
}


@pytest.fixture(autouse=True)
def _drop_operational_signal_table(pg_backend):
    """Keep the shared session Postgres container pristine for sibling storage tests.

    ``_wrapper`` builds the ``signals`` table via ``create_all`` on the session-scoped
    container. This file sorts alphabetically BEFORE ``test_migrations.py``, whose
    ``alembic upgrade head`` would raise ``ProgrammingError`` on the pre-existing ``signals``
    table. Drop it in teardown (CASCADE covers any FK) so the container is left clean — the
    same pristine-container discipline ``test_migrations`` follows with its ``downgrade base``.
    Teardown runs before ``pg_backend`` disposes (LIFO), so the engine is still live.
    """
    yield
    with pg_backend.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS signals CASCADE"))


def _make_record(strategy_id, ticker, *, time):
    """Build a ``SignalRecord`` (fresh default signal_id) for the given strategy/ticker."""
    return SignalRecord(
        strategy_id=strategy_id,
        ticker=ticker,
        time=time,
        action=Side.BUY,
        order_type=OrderType.MARKET,
        exit_fraction=Decimal("1"),
        config=dict(_CONFIG),
    )


def _wrapper(pg_backend):
    """Construct the composed wrapper over a fresh Postgres-backed store.

    Constructing ``SqlSignalStorage`` registers the ``signals`` table on
    ``pg_backend.metadata`` and creates it idempotently; the explicit
    ``metadata.create_all`` is a redundant idempotent guard (checkfirst).
    """
    store = SqlSignalStorage(pg_backend)
    pg_backend.metadata.create_all(pg_backend.engine, checkfirst=True)
    return store, CachedSqlSignalStorage(store)


def test_add_store_first(pg_backend):
    """add persists store-first then mirrors: the row is in Postgres AND the cache."""
    store, wrapper = _wrapper(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    record = _make_record(
        strategy_id, "BTCUSD", time=datetime(2018, 1, 1, tzinfo=timezone.utc)
    )

    wrapper.add(record)

    # Present in the in-memory full mirror immediately.
    assert record in wrapper.get_all()
    assert wrapper.by_strategy(strategy_id) == [record]
    # Durably persisted: a SEPARATE store reads the row straight from Postgres.
    persisted = SqlSignalStorage(pg_backend).by_strategy(strategy_id)
    assert [r.signal_id for r in persisted] == [record.signal_id]


def test_filters_from_mirror(pg_backend):
    """by_strategy / by_ticker serve the right subset from the full cache mirror."""
    _store, wrapper = _wrapper(pg_backend)
    strat_a = StrategyId(uc.uuid7())
    strat_b = StrategyId(uc.uuid7())
    ticker_x = f"XCOIN-{uuid.uuid4().hex[:8]}"
    ticker_y = f"YCOIN-{uuid.uuid4().hex[:8]}"
    rec_a = _make_record(
        strat_a, ticker_x, time=datetime(2021, 1, 1, tzinfo=timezone.utc)
    )
    rec_b = _make_record(
        strat_b, ticker_y, time=datetime(2021, 1, 2, tzinfo=timezone.utc)
    )

    wrapper.add(rec_a)
    wrapper.add(rec_b)

    # The mirror is fresh per wrapper, so the filtered reads see only these two.
    assert wrapper.by_strategy(strat_a) == [rec_a]
    assert wrapper.by_strategy(strat_b) == [rec_b]
    assert wrapper.by_ticker(ticker_x) == [rec_a]
    assert wrapper.by_ticker(ticker_y) == [rec_b]


def test_duplicate_rejected(pg_backend):
    """Adding the same signal_id twice raises ValueError (the mirror inherits the contract)."""
    _store, wrapper = _wrapper(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    record = _make_record(
        strategy_id, "BTCUSD", time=datetime(2022, 1, 1, tzinfo=timezone.utc)
    )

    wrapper.add(record)
    with pytest.raises(ValueError):
        wrapper.add(record)


def test_rehydrate_full_mirror(pg_backend):
    """rehydrate repopulates the full mirror from the store, order-stable (time, id)."""
    store, wrapper = _wrapper(pg_backend)
    strategy_id = StrategyId(uc.uuid7())
    records = [
        _make_record(
            strategy_id, "BTCUSD", time=datetime(2023, 1, day, tzinfo=timezone.utc)
        )
        for day in (1, 2, 3)
    ]
    # Persist out of chronological order; the store's ORDER BY restores it.
    for record in (records[1], records[2], records[0]):
        wrapper.add(record)

    # A fresh wrapper has an EMPTY mirror until rehydrate populates it.
    fresh = CachedSqlSignalStorage(store)
    assert fresh.by_strategy(strategy_id) == []

    fresh.rehydrate()

    assert fresh.by_strategy(strategy_id) == records
