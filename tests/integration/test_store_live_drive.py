"""RECON-04 — the v1.6 operational store driven off the live composition root (05-06).

These integration tests exercise the split-write-path store wiring completed in
``LiveTradingSystem.__init__`` (D-10/D-11):

* the SYNC-DURABLE working set (order lifecycle — create/terminalize) persists store-first
  via ``CachedSqlOrderStorage`` and survives a simulated process restart via ``rehydrate()``
  (D-10 — the two-sided restart precondition);
* the DERIVED / advisory signal store is live-driven (``CachedSqlSignalStorage``) and its
  persist runs on the engine (queue-draining) thread — off the connector asyncio coroutine —
  so a signal write can never stall the loop (D-11 / Pitfall 9);
* the ``SYSTEM_DB_URL``-unset path falls back loudly to in-memory storage and does NOT crash
  (WR-10 — no hardcoded credential fallback).

Substrate: a module-scoped testcontainers Postgres container (mirrors
``tests/integration/storage/conftest.py::pg_engine``). The container-backed tests SKIP (never
hard-fail) when Docker is absent (D-11); the ``SYSTEM_DB_URL``-unset test needs no container and
runs even Dockerless. This file lives at ``tests/integration/`` root (NOT under ``storage/``), so
it builds its OWN container fixture rather than reusing the ``storage/`` package's ``pg_backend``.

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration``/``slow`` markers.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
import uuid_utils.compat as uc

from itrader.core.enums import (
    OrderStatus,
    OrderTriggerSource,
    OrderType,
    Side,
)
from itrader.core.ids import PortfolioId, StrategyId
from itrader.order_handler.order import Order
from itrader.strategy_handler.signal_record import SignalRecord
from itrader.strategy_handler.storage import SignalStorageFactory

# A business time (never wall clock) reused so derived timestamps are deterministic.
_BT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# A stable, JSON-safe params snapshot (the strategy.to_dict() shape, D-04).
_CONFIG: dict[str, Any] = {"fast_window": 10, "slow_window": 50, "name": "SMA_MACD"}

# Operational tables dropped between container-backed tests so the shared DB stays pristine.
_OPERATIONAL_TABLES = (
    "order_state_changes",
    "orders",
    "signals",
    "portfolio_snapshots",
    "portfolio_states",
    "account_states",
)


@pytest.fixture(scope="module")
def pg_url():
    """Module-scoped testcontainers Postgres connection URL; skip if Dockerless (D-11).

    The heavy ``testcontainers``/``docker`` imports live INSIDE the body so collection
    needs no Docker daemon; any startup failure is converted to a ``pytest.skip`` — the
    container-backed arm must never hard-fail a Dockerless run.
    """
    from testcontainers.postgres import PostgresContainer

    container = None
    try:
        # The PostgresContainer constructor eagerly builds a DockerClient, so an
        # absent/unreachable daemon raises as early as construction — keep it in the try.
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:
        if container is not None:
            try:
                container.stop()
            except Exception:
                pass
        pytest.skip(f"PostgreSQL container unavailable — skipped (D-11): {exc}")

    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _make_backend(pg_url):
    """Build a fresh ``SqlBackend`` bound to the container DB (verbatim-URL escape hatch)."""
    from pydantic import SecretStr

    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlBackend

    return SqlBackend(SqlSettings(
        driver=SqlDriver.POSTGRESQL_PSYCOPG2,
        url=SecretStr(pg_url),
    ))


def _drop_operational_tables(pg_url):
    """Drop the operational tables so the shared session DB is left pristine (LIFO teardown)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    try:
        with engine.begin() as conn:
            for table in _OPERATIONAL_TABLES:
                conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
    finally:
        engine.dispose()


def _make_order(**overrides):
    """Build a fully-populated ``Order`` with unique UUIDv7 ids (overridable per field)."""
    base = dict(
        time=_BT,
        type=OrderType.LIMIT,
        status=OrderStatus.PENDING,
        ticker="BTCUSD",
        action=Side.BUY,
        price=Decimal("45000.12345678"),
        quantity=Decimal("0.5"),
        exchange="simulated",
        strategy_id=StrategyId(uc.uuid7()),
        portfolio_id=PortfolioId(uc.uuid7()),
    )
    base.update(overrides)
    return Order(**base)


def _terminalize(storage, order, status=OrderStatus.FILLED):
    """Drive an order to a terminal status through the wrapper's store-first update path."""
    order.add_state_change(status, "terminalize", OrderTriggerSource.EXCHANGE)
    assert storage.update_order(order) is True


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


def test_order_create_terminalize_durable_survives_restart(pg_url):
    """Order create/terminalize is durable store-first and survives a simulated restart (D-10).

    Adds an open order + a terminalized order through the CachedSql wrapper (store-first),
    then builds a FRESH wrapper (empty cache) over the SAME backend — the process-restart
    analog — and asserts ``rehydrate()`` loads the durable open set while the terminal order
    is still recoverable via store read-through. This is the two-sided-restart precondition:
    the working set must survive a crash.
    """
    from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
    from itrader.order_handler.storage.sql_storage import SqlOrderStorage

    backend = _make_backend(pg_url)
    try:
        store = SqlOrderStorage(backend)
        backend.metadata.create_all(backend.engine, checkfirst=True)
        wrapper = CachedSqlOrderStorage(store)

        pid = PortfolioId(uc.uuid7())
        open_order = _make_order(portfolio_id=pid)      # stays PENDING
        term_order = _make_order(portfolio_id=pid)      # driven terminal
        wrapper.add_order(open_order)
        wrapper.add_order(term_order)
        _terminalize(wrapper, term_order, OrderStatus.FILLED)

        # Process-restart analog: a fresh wrapper with an EMPTY cache over the same
        # backend rehydrates the durable open set store-first.
        restarted = CachedSqlOrderStorage(SqlOrderStorage(backend))
        restarted.rehydrate()

        got_open = restarted.get_order_by_id(open_order.id)
        assert got_open is not None                     # create survived the crash
        assert got_open.status == OrderStatus.PENDING

        # Terminalize is durable too — the store read-through returns the FILLED record.
        got_term = restarted.get_order_by_id(term_order.id)
        assert got_term is not None
        assert got_term.status == OrderStatus.FILLED
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()


def test_signal_store_live_driven_off_engine_critical_path(pg_url):
    """The signal store is live-driven and its persist is off the connector coroutine (D-11).

    ``SignalStorageFactory.create('live', backend=...)`` returns the live
    ``CachedSqlSignalStorage`` wrapper. The persist runs on the calling (engine-thread analog)
    with NO running asyncio loop — proving it is off the connector's event loop (Pitfall 9),
    so a signal write can never stall the loop. The store-first write returns promptly and the
    record round-trips through the full mirror.
    """
    backend = _make_backend(pg_url)
    try:
        signal_store = SignalStorageFactory.create('live', backend=backend)
        backend.metadata.create_all(backend.engine, checkfirst=True)
        assert type(signal_store).__name__ == "CachedSqlSignalStorage"

        # No running asyncio loop on this (engine) thread — the persist is NOT inside a
        # connector coroutine, so it cannot block the connector's event loop (D-11).
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()

        sid = StrategyId(uc.uuid7())
        record = _make_record(sid, "BTCUSD", time=_BT)
        signal_store.add(record)                        # store-first, returns promptly

        got = signal_store.get_all()
        assert len(got) == 1
        assert got[0].signal_id == record.signal_id
    finally:
        _drop_operational_tables(pg_url)
        backend.dispose()


def test_live_system_wires_cached_sql_when_system_db_url_set(pg_url, monkeypatch):
    """With SYSTEM_DB_URL set, the composition root drives the store via the CachedSql wrappers.

    The heart of RECON-04: constructing ``LiveTradingSystem`` with ``SYSTEM_DB_URL`` pointing at
    the operational DB wires the sync-durable order working set (``CachedSqlOrderStorage``) and
    the live signal store (``CachedSqlSignalStorage``) off ONE shared ``SqlBackend`` — the v1.6
    operational store driven off the composition root for the first time.
    """
    import itrader.trading_system.live_trading_system as lts

    monkeypatch.setattr(lts, "_SYSTEM_DB_URL", pg_url)
    system = lts.LiveTradingSystem(exchange="binance")
    try:
        assert type(system._signal_store).__name__ == "CachedSqlSignalStorage"
        assert type(system.portfolio_handler._order_storage).__name__ == "CachedSqlOrderStorage"
    finally:
        system.stop()
        _drop_operational_tables(pg_url)


def test_unset_system_db_url_falls_back_to_in_memory(monkeypatch):
    """SYSTEM_DB_URL unset → loud in-memory fallback for BOTH order and signal stores, no crash.

    WR-10: no hardcoded credential fallback. An unset ``SYSTEM_DB_URL`` must not crash the
    composition root — it falls back to in-memory storage (orders/signals will not survive a
    restart). Needs no container, so it runs even on a Dockerless box.
    """
    import itrader.trading_system.live_trading_system as lts

    monkeypatch.setattr(lts, "_SYSTEM_DB_URL", "")
    system = lts.LiveTradingSystem(exchange="binance")
    try:
        assert type(system._signal_store).__name__ == "InMemorySignalStore"
        assert type(system.portfolio_handler._order_storage).__name__ == "InMemoryOrderStorage"
    finally:
        system.stop()
