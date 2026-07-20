"""Unit tests for ``StrategyRegistryStore`` — instance registry + portfolio-subscription child.

Two flavors (STRAT-01 / D-06 / D-18):

* **In-memory SQLite** — round-trip, FK-join rehydrate, ``list_active`` filtering, and the
  portfolio fan-out CRUD. The durable key is the strategy NAME (never the ephemeral runtime
  ``strategy_id`` UUID, D-02).
* **File-backed restart survival** (Pitfall 4) — write → ``store.dispose()`` → construct a NEW
  store over the SAME sqlite FILE → read back registry + subscriptions identical. ``:memory:``
  is deliberately NOT used here: disposing an in-memory DB destroys it and proves nothing.

D-06 reshaped the child table: the P4 ``strategy_subscriptions`` (venue, symbol, timeframe)
table is GONE and ``strategy_portfolio_subscriptions`` ``(strategy_name FK, portfolio_id)``
models the portfolio fan-out edge instead. Per-portfolio "off" is ROW PRESENCE; whole-instance
"off" is the ``enabled`` column.

4-space indentation. NO ``__init__.py`` in this dir. ``filterwarnings=["error"]`` → every
store wrapped in ``try/finally: store.dispose()``.
"""

import pathlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import String
from sqlalchemy.exc import IntegrityError

from itrader.config.sql import SqlDriver, SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.strategy_registry_store import (
    StrategyRegistryStore,
    build_strategy_registry_tables,
)
from tests.support.schema import provision_schema

_AT1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_AT2 = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)

_TYPE = "SMAMACDStrategy"


def _make_memory_store() -> StrategyRegistryStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite.

    WR-03/D-14 — the store is schema-pure, so provision the schema explicitly after
    construction (before the first query) via the shared ``provision_schema`` helper.
    """
    store = StrategyRegistryStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def _make_file_store(db_path: pathlib.Path) -> StrategyRegistryStore:
    """A file-backed durable store over ``db_path`` — survives dispose→reopen (Pitfall 4).

    WR-03/D-14 — schema-pure store; provision after construction. ``checkfirst=True`` makes
    the reopen case (the restart-survival test) a clean no-op against the existing tables.
    """
    settings = SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE, database=str(db_path))
    store = StrategyRegistryStore(SqlEngine(settings))
    provision_schema(store.backend)
    return store


# --------------------------------------------------------------------------------------
# Registrar shape (D-06 behaviors 1 + 2)
# --------------------------------------------------------------------------------------


def test_build_strategy_registry_tables_shape() -> None:
    """D-06 — the registrar declares EXACTLY the two tables; the P4 child is gone.

    ``strategy_subscriptions`` (venue, symbol, timeframe) was dropped: its columns are
    derivable from (the live venue, ``config_json.tickers``, ``config_json.timeframe``).
    """
    backend = SqlEngine(SqlSettings.default())
    try:
        tables = build_strategy_registry_tables(backend.metadata)
        assert set(tables) == {
            "strategy_registry",
            "strategy_portfolio_subscriptions",
        }
        subs = tables["strategy_portfolio_subscriptions"]
        # composite natural PK on the portfolio-subscription child (no surrogate UUID)
        pk_cols = {col.name for col in subs.primary_key.columns}
        assert pk_cols == {"strategy_name", "portfolio_id"}
        # FK back to the registry natural name key
        fk = next(iter(subs.c.strategy_name.foreign_keys))
        assert fk.column.table.name == "strategy_registry"
        assert fk.column.name == "strategy_name"
        # portfolio_id is String because base.py serializes each handle via str(pid)
        # and rehydrate parses it back. A Uuid column is open as B2, not decided.
        assert isinstance(subs.c.portfolio_id.type, String)
        # idempotent reuse
        assert build_strategy_registry_tables(backend.metadata) == tables
    finally:
        backend.dispose()


def test_registry_has_non_null_strategy_type_and_sole_name_pk() -> None:
    """D-06/D-02 — strategy_type is a non-null column; strategy_name stays the SOLE PK."""
    backend = SqlEngine(SqlSettings.default())
    try:
        registry = build_strategy_registry_tables(backend.metadata)["strategy_registry"]
        assert registry.c.strategy_type.nullable is False
        # D-02 — no second durable id column; the ephemeral strategy_id is never persisted.
        assert {col.name for col in registry.primary_key.columns} == {"strategy_name"}
        assert "strategy_id" not in registry.c
        # D-06 — enabled stays its OWN column (never inside config_json).
        assert "enabled" in registry.c
    finally:
        backend.dispose()


# --------------------------------------------------------------------------------------
# Registry CRUD
# --------------------------------------------------------------------------------------


def test_upsert_get_round_trip_carries_strategy_type() -> None:
    """D-06 — upsert(name, type, config, enabled, at) → get(name) round-trips every field."""
    store = _make_memory_store()
    try:
        config = {"fast": 10, "slow": 30}
        store.upsert("sma_macd", _TYPE, config, True, _AT1)
        row = store.get("sma_macd")
        assert row is not None
        assert row["strategy_type"] == _TYPE
        assert row["config"] == config
        assert row["enabled"] is True
        assert row["updated_at"] == _AT1
    finally:
        store.dispose()


def test_get_missing_strategy_returns_none() -> None:
    """get() on an unknown name is None (not an error) — the absent-row contract."""
    store = _make_memory_store()
    try:
        assert store.get("nope") is None
    finally:
        store.dispose()


def test_upsert_of_subscribed_strategy_preserves_children() -> None:
    """CR-01 — re-upserting an already-subscribed strategy must NOT delete the FK parent.

    The live re-config path is upsert(config) → set_portfolio_subscriptions(...) →
    upsert(new_config). upsert UPDATES the row in place: the new type/config/enabled/
    updated_at persist AND the portfolio subscriptions survive the config overwrite.
    """
    store = _make_memory_store()
    try:
        store.upsert("sma_macd", _TYPE, {"fast": 10}, True, _AT1)
        store.set_portfolio_subscriptions("sma_macd", ["p1"], _AT1)
        store.upsert("sma_macd", "RsiStrategy", {"fast": 20, "slow": 50}, False, _AT2)
        rec = {r["strategy_name"]: r for r in store.read_all()}["sma_macd"]
        assert rec["strategy_type"] == "RsiStrategy"
        assert rec["config"] == {"fast": 20, "slow": 50}
        assert rec["enabled"] is False
        assert rec["updated_at"] == _AT2
        # Subscriptions survived the config overwrite (parent row was never deleted).
        assert rec["portfolio_ids"] == ["p1"]
    finally:
        store.dispose()


def test_list_active_filters_disabled_and_is_name_ordered() -> None:
    """D-06 — list_active() returns only enabled=True rows, carries strategy_type, and is
    ordered by strategy_name ASC so rehydrate registration order is reproducible."""
    store = _make_memory_store()
    try:
        # Upsert in NON-sorted name order to prove the ORDER BY (not insertion order).
        store.upsert("charlie", _TYPE, {"n": 1}, True, _AT1)
        store.upsert("alpha", _TYPE, {"n": 2}, True, _AT1)
        store.upsert("rsi_rev", "RsiStrategy", {"period": 14}, False, _AT1)
        store.upsert("bravo", _TYPE, {"n": 3}, True, _AT1)
        active = store.list_active()
        assert [r["strategy_name"] for r in active] == ["alpha", "bravo", "charlie"]
        assert all(r["strategy_type"] == _TYPE for r in active)
        assert all(r["enabled"] is True for r in active)
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# Portfolio-subscription CRUD (D-06 fan-out edge / D-09 verb backing)
# --------------------------------------------------------------------------------------


def test_set_portfolio_subscriptions_replaces_and_is_ordered() -> None:
    """D-06 — set_portfolio_subscriptions REPLACES the full set; reads back id-ASC ordered."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"fast": 10}, True, _AT1)
        # Insert out of order — the read is ordered by portfolio_id ASC (IN-01).
        store.set_portfolio_subscriptions("s1", ["p2", "p1"], _AT1)
        assert store.portfolio_subscriptions("s1") == ["p1", "p2"]
        # Replace semantics (not append).
        store.set_portfolio_subscriptions("s1", ["p2"], _AT2)
        assert store.portfolio_subscriptions("s1") == ["p2"]
    finally:
        store.dispose()


def test_set_portfolio_subscriptions_bumps_parent_updated_at() -> None:
    """The caller-supplied ``at`` bumps the parent's updated_at (clock-free store, D-07)."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"fast": 10}, True, _AT1)
        store.set_portfolio_subscriptions("s1", ["p1"], _AT2)
        row = store.get("s1")
        assert row is not None
        assert row["updated_at"] == _AT2
    finally:
        store.dispose()


def test_set_portfolio_subscriptions_empty_clears_all() -> None:
    """An empty set clears every child row (the unsubscribe-all case)."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"fast": 10}, True, _AT1)
        store.set_portfolio_subscriptions("s1", ["p1", "p2"], _AT1)
        store.set_portfolio_subscriptions("s1", [], _AT2)
        assert store.portfolio_subscriptions("s1") == []
    finally:
        store.dispose()


def test_add_and_remove_portfolio_subscription_are_idempotent() -> None:
    """D-09 — add is idempotent (twice → one row); remove of an absent row is a no-op."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"fast": 10}, True, _AT1)
        store.add_portfolio_subscription("s1", "p3")
        store.add_portfolio_subscription("s1", "p3")  # idempotent — no IntegrityError
        assert store.portfolio_subscriptions("s1") == ["p3"]

        # remove of an ABSENT row is a silent no-op, not an error.
        store.remove_portfolio_subscription("s1", "p9")
        assert store.portfolio_subscriptions("s1") == ["p3"]

        store.remove_portfolio_subscription("s1", "p3")
        assert store.portfolio_subscriptions("s1") == []
    finally:
        store.dispose()


def test_portfolio_subscriptions_are_per_strategy_scoped() -> None:
    """The fan-out edge is scoped per strategy — no cross-strategy bleed."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"n": 1}, True, _AT1)
        store.upsert("s2", _TYPE, {"n": 2}, True, _AT1)
        store.set_portfolio_subscriptions("s1", ["p1", "p2"], _AT1)
        store.set_portfolio_subscriptions("s2", ["p2"], _AT1)
        assert store.portfolio_subscriptions("s1") == ["p1", "p2"]
        assert store.portfolio_subscriptions("s2") == ["p2"]
    finally:
        store.dispose()


def test_orphan_portfolio_subscription_raises_integrity_error() -> None:
    """WR-02 — a child row whose strategy_name has no parent registry row raises.

    The SqlEngine ``PRAGMA foreign_keys=ON`` hook enforces this on SQLite too (Postgres
    always raised).
    """
    store = _make_memory_store()
    try:
        with pytest.raises(IntegrityError):
            store.set_portfolio_subscriptions("ghost_strategy", ["p1"], _AT1)
        with pytest.raises(IntegrityError):
            store.add_portfolio_subscription("ghost_strategy", "p1")
    finally:
        store.dispose()


def test_delete_removes_children_before_parent() -> None:
    """P-6 — delete(name) removes the child rows BEFORE the registry row (no FK error)."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"fast": 10}, True, _AT1)
        store.set_portfolio_subscriptions("s1", ["p1", "p2"], _AT1)
        store.delete("s1")  # 2 children held — raises no FK IntegrityError
        assert store.get("s1") is None
        assert store.read_all() == []
        assert store.portfolio_subscriptions("s1") == []
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# read_all — the rehydrate join
# --------------------------------------------------------------------------------------


def test_read_all_left_outer_joins_portfolio_ids() -> None:
    """D-06 — read_all returns one record per strategy with a portfolio_ids list.

    LEFT OUTER JOIN: a strategy with ZERO subscriptions still appears (empty list).
    """
    store = _make_memory_store()
    try:
        store.upsert("subscribed", _TYPE, {"n": 1}, True, _AT1)
        store.upsert("lonely", _TYPE, {"n": 2}, True, _AT1)
        store.set_portfolio_subscriptions("subscribed", ["p1", "p2"], _AT2)
        rows = {r["strategy_name"]: r for r in store.read_all()}
        assert set(rows) == {"subscribed", "lonely"}
        assert rows["subscribed"]["portfolio_ids"] == ["p1", "p2"]
        assert rows["lonely"]["portfolio_ids"] == []  # zero-subscription strategy appears
    finally:
        store.dispose()


def test_read_all_is_deterministically_ordered() -> None:
    """IN-01 — read_all returns strategies in strategy_name ASC and each record's
    portfolio_ids in portfolio_id ASC, regardless of insertion order."""
    store = _make_memory_store()
    try:
        # Upsert in NON-sorted name order.
        store.upsert("charlie", _TYPE, {"n": 1}, True, _AT1)
        store.upsert("alpha", _TYPE, {"n": 2}, True, _AT1)
        store.upsert("bravo", _TYPE, {"n": 3}, True, _AT1)
        # Set subscriptions in NON-sorted portfolio_id order.
        store.set_portfolio_subscriptions("alpha", ["p3", "p1", "p2"], _AT2)
        records = store.read_all()
        assert [r["strategy_name"] for r in records] == ["alpha", "bravo", "charlie"]
        assert records[0]["portfolio_ids"] == ["p1", "p2", "p3"]
    finally:
        store.dispose()


def test_read_all_carries_strategy_type() -> None:
    """read_all records carry strategy_type — rehydrate resolves catalog[strategy_type]."""
    store = _make_memory_store()
    try:
        store.upsert("s1", _TYPE, {"n": 1}, True, _AT1)
        store.upsert("s2", "RsiStrategy", {"n": 2}, False, _AT1)
        rows = {r["strategy_name"]: r for r in store.read_all()}
        assert rows["s1"]["strategy_type"] == _TYPE
        assert rows["s2"]["strategy_type"] == "RsiStrategy"
        assert rows["s2"]["enabled"] is False
    finally:
        store.dispose()


# --------------------------------------------------------------------------------------
# Restart survival
# --------------------------------------------------------------------------------------


def test_restart_survival_file_backed(tmp_path: pathlib.Path) -> None:
    """write → dispose → NEW store over the SAME db file → read back identical (Pitfall 4)."""
    db_path = tmp_path / "strategy_registry.db"

    store = _make_file_store(db_path)
    try:
        store.upsert("sma_macd", _TYPE, {"fast": 10, "slow": 30}, True, _AT1)
        store.set_portfolio_subscriptions("sma_macd", ["p1", "p2"], _AT2)
    finally:
        store.dispose()

    reopened = _make_file_store(db_path)
    try:
        rec = {r["strategy_name"]: r for r in reopened.read_all()}["sma_macd"]
        assert rec["strategy_type"] == _TYPE
        assert rec["config"] == {"fast": 10, "slow": 30}
        assert rec["enabled"] is True
        assert rec["portfolio_ids"] == ["p1", "p2"]
    finally:
        reopened.dispose()
