"""Unit tests for ``StrategyRegistryStore`` — two-table registry + normalized subscriptions.

Two flavors (STORE-03 / D-04 / D-06):

* **In-memory SQLite** — round-trip, FK-join rehydrate, ``list_active`` filtering, and the
  subscribe-by-symbol lookup. The durable key is the strategy NAME (never the ephemeral
  runtime ``strategy_id`` UUID).
* **File-backed restart survival** (Pitfall 4) — write → ``store.dispose()`` → construct a NEW
  store over the SAME sqlite FILE → read back registry + subscriptions identical. ``:memory:``
  is deliberately NOT used here: disposing an in-memory DB destroys it and proves nothing.

4-space indentation. NO ``__init__.py`` in this dir. ``filterwarnings=["error"]`` → every
store wrapped in ``try/finally: store.dispose()``.
"""

import pathlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import (
    StrategyRegistryStore,
    build_strategy_registry_tables,
)

_AT1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_AT2 = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)


def _make_memory_store() -> StrategyRegistryStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite."""
    return StrategyRegistryStore(SqlEngine(SqlSettings.default()))


def _make_file_store(db_path: pathlib.Path) -> StrategyRegistryStore:
    """A file-backed durable store over ``db_path`` — survives dispose→reopen (Pitfall 4)."""
    settings = SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE, database=str(db_path))
    return StrategyRegistryStore(SqlEngine(settings))


def test_upsert_get_round_trip() -> None:
    """upsert(name, config, enabled, at) → get(name) round-trips config/enabled/updated_at."""
    store = _make_memory_store()
    try:
        config = {"fast": 10, "slow": 30}
        store.upsert("sma_macd", config, True, _AT1)
        row = store.get("sma_macd")
        assert row is not None
        assert row["config"] == config
        assert row["enabled"] is True
        assert row["updated_at"] == _AT1
    finally:
        store.dispose()


def test_set_subscriptions_and_join_rehydrate() -> None:
    """rehydrate JOINs registry + subscriptions into one grouped view (D-04)."""
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", {"fast": 10}, True, _AT1)
        store.set_subscriptions(
            "sma_macd",
            [("okx", "BTC/USDC", "1h"), ("okx", "ETH/USDC", "1h")],
            _AT2,
        )
        rows = {r["strategy_name"]: r for r in store.read_all()}
        assert set(rows) == {"sma_macd"}
        rec = rows["sma_macd"]
        assert rec["config"] == {"fast": 10}
        assert set(rec["subscriptions"]) == {
            ("okx", "BTC/USDC", "1h"),
            ("okx", "ETH/USDC", "1h"),
        }
    finally:
        store.dispose()


def test_set_subscriptions_replaces_all() -> None:
    """set_subscriptions replaces the full set for a strategy (not append)."""
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", {"fast": 10}, True, _AT1)
        store.set_subscriptions("sma_macd", [("okx", "BTC/USDC", "1h")], _AT1)
        store.set_subscriptions("sma_macd", [("okx", "ETH/USDC", "4h")], _AT2)
        rec = {r["strategy_name"]: r for r in store.read_all()}["sma_macd"]
        assert set(rec["subscriptions"]) == {("okx", "ETH/USDC", "4h")}
    finally:
        store.dispose()


def test_list_active_filters_disabled() -> None:
    """list_active() returns only enabled=True strategies."""
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", {"fast": 10}, True, _AT1)
        store.upsert("rsi_rev", {"period": 14}, False, _AT1)
        store.upsert("bbands", {"n": 20}, True, _AT1)
        names = {r["strategy_name"] for r in store.list_active()}
        assert names == {"sma_macd", "bbands"}
    finally:
        store.dispose()


def test_strategies_subscribed_to_symbol() -> None:
    """A subscription query answers 'which strategies subscribe to symbol X'."""
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", {"fast": 10}, True, _AT1)
        store.upsert("rsi_rev", {"period": 14}, True, _AT1)
        store.set_subscriptions("sma_macd", [("okx", "BTC/USDC", "1h")], _AT1)
        store.set_subscriptions("rsi_rev", [("okx", "ETH/USDC", "1h")], _AT1)
        assert store.strategies_subscribed_to("BTC/USDC") == ["sma_macd"]
        assert store.strategies_subscribed_to("ETH/USDC") == ["rsi_rev"]
        assert store.strategies_subscribed_to("SOL/USDC") == []
    finally:
        store.dispose()


def test_delete_removes_registry_and_subscriptions() -> None:
    """delete(name) removes the registry row AND its subscriptions (FK child order)."""
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", {"fast": 10}, True, _AT1)
        store.set_subscriptions("sma_macd", [("okx", "BTC/USDC", "1h")], _AT1)
        store.delete("sma_macd")
        assert store.get("sma_macd") is None
        assert store.read_all() == []
        assert store.strategies_subscribed_to("BTC/USDC") == []
    finally:
        store.dispose()


def test_restart_survival_file_backed(tmp_path: pathlib.Path) -> None:
    """write → dispose → NEW store over the SAME db file → read back identical (Pitfall 4)."""
    db_path = tmp_path / "strategy_registry.db"

    store = _make_file_store(db_path)
    try:
        store.upsert("sma_macd", {"fast": 10, "slow": 30}, True, _AT1)
        store.set_subscriptions(
            "sma_macd",
            [("okx", "BTC/USDC", "1h"), ("okx", "ETH/USDC", "1h")],
            _AT2,
        )
    finally:
        store.dispose()

    reopened = _make_file_store(db_path)
    try:
        rec = {r["strategy_name"]: r for r in reopened.read_all()}["sma_macd"]
        assert rec["config"] == {"fast": 10, "slow": 30}
        assert rec["enabled"] is True
        assert set(rec["subscriptions"]) == {
            ("okx", "BTC/USDC", "1h"),
            ("okx", "ETH/USDC", "1h"),
        }
    finally:
        reopened.dispose()


def test_set_subscriptions_on_unregistered_strategy_raises_integrity_error() -> None:
    """WR-02 — an orphan subscription (no parent registry row) raises IntegrityError.

    Before the SqlEngine PRAGMA foreign_keys=ON hook, SQLite silently inserted the orphan
    child row; Postgres always raised. This pins the intended cross-backend FK contract:
    set_subscriptions for a strategy_name with no registry row now raises on SQLite too.
    """
    store = _make_memory_store()
    try:
        with pytest.raises(IntegrityError):
            store.set_subscriptions(
                "ghost_strategy", [("okx", "BTC/USDC", "1h")], _AT1
            )
    finally:
        store.dispose()


def test_read_all_is_deterministically_ordered() -> None:
    """IN-01 — read_all returns strategies in strategy_name ASC and each record's
    subscriptions in (venue, symbol, timeframe) ASC, regardless of insertion order."""
    store = _make_memory_store()
    try:
        # Upsert in NON-sorted name order.
        store.upsert("charlie", {"n": 1}, True, _AT1)
        store.upsert("alpha", {"n": 2}, True, _AT1)
        store.upsert("bravo", {"n": 3}, True, _AT1)
        # Set subscriptions in NON-sorted (venue, symbol, timeframe) order.
        store.set_subscriptions(
            "alpha",
            [
                ("okx", "ETH/USDC", "4h"),
                ("binance", "BTC/USDC", "1h"),
                ("okx", "BTC/USDC", "1h"),
            ],
            _AT2,
        )
        records = store.read_all()
        # Records ordered by strategy_name ASC.
        assert [r["strategy_name"] for r in records] == ["alpha", "bravo", "charlie"]
        # alpha's subscriptions ordered by (venue, symbol, timeframe) ASC (assert the LIST).
        alpha = records[0]
        assert alpha["subscriptions"] == [
            ("binance", "BTC/USDC", "1h"),
            ("okx", "BTC/USDC", "1h"),
            ("okx", "ETH/USDC", "4h"),
        ]
    finally:
        store.dispose()


def test_build_strategy_registry_tables_shape() -> None:
    """The registrar returns both tables; the FK + composite PK are declared (D-06)."""
    backend = SqlEngine(SqlSettings.default())
    try:
        tables = build_strategy_registry_tables(backend.metadata)
        assert set(tables) == {"strategy_registry", "strategy_subscriptions"}
        registry = tables["strategy_registry"]
        subs = tables["strategy_subscriptions"]
        assert registry.c.strategy_name.primary_key is True
        # composite natural PK on the subscriptions child (no surrogate UUID)
        pk_cols = {col.name for col in subs.primary_key.columns}
        assert pk_cols == {"strategy_name", "venue", "symbol", "timeframe"}
        # FK back to the registry natural name key
        fk = next(iter(subs.c.strategy_name.foreign_keys))
        assert fk.column.table.name == "strategy_registry"
        assert fk.column.name == "strategy_name"
        # idempotent reuse
        assert build_strategy_registry_tables(backend.metadata) == tables
    finally:
        backend.dispose()
