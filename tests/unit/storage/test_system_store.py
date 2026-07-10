"""Unit tests for the ``SystemStore`` cardinality-1 KV durable store (STORE-01 / D-06/D-08).

A disciplined clone of the ``HaltRecordStore`` template exercised over an in-memory SQLite
``SqlEngine`` double. Proves: namespaced upsert round-trip (exact ``value`` dict + ``at``
datetime), one-row-per-key idempotency, missing-key ``None``, delete, and read-all rehydrate.

4-space indentation (matches ``itrader/storage`` + the storage test convention). NO
``__init__.py`` in this dir (auto-memory: package-collision hazard). ``filterwarnings=["error"]``
turns an unclosed-sqlite ``ResourceWarning`` into a failure, so every store is wrapped in
``try/finally: store.dispose()``.
"""

from datetime import UTC, datetime

from itrader.config.sql import SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.system_store import SystemStore, build_system_store_table
from tests.support.schema import provision_schema

# A FIXED timezone-aware instant (D-07 determinism — no clock in the store; the caller
# supplies ``at``). Two distinct instants prove the second upsert overwrites the first.
_AT1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_AT2 = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)


def _make_store() -> SystemStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite.

    WR-03/D-14 — the store is schema-pure now, so provision the schema explicitly after
    construction (before the first query) via the shared ``provision_schema`` helper.
    """
    store = SystemStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def test_upsert_get_round_trip() -> None:
    """upsert(key, value, at) → get(key) returns the exact value dict + updated_at."""
    store = _make_store()
    try:
        value = {"universe_poll_seconds": 30, "mode": "paper"}
        store.upsert("runtime_config", value, _AT1)
        row = store.get("runtime_config")
        assert row is not None
        assert row["value"] == value
        assert row["updated_at"] == _AT1
    finally:
        store.dispose()


def test_namespaced_upsert_leaves_one_row() -> None:
    """Two upserts on the SAME key leave ONE row carrying the latest value + at."""
    store = _make_store()
    try:
        store.upsert("runtime_config", {"v": 1}, _AT1)
        store.upsert("runtime_config", {"v": 2}, _AT2)
        rows = store.read_all()
        assert len(rows) == 1
        assert rows[0]["key"] == "runtime_config"
        assert rows[0]["value"] == {"v": 2}
        assert rows[0]["updated_at"] == _AT2
    finally:
        store.dispose()


def test_get_missing_key_returns_none() -> None:
    """get(missing_key) returns None (no row)."""
    store = _make_store()
    try:
        assert store.get("absent") is None
    finally:
        store.dispose()


def test_delete_removes_row() -> None:
    """delete(key) removes the row; a subsequent get returns None."""
    store = _make_store()
    try:
        store.upsert("k", {"a": 1}, _AT1)
        assert store.get("k") is not None
        store.delete("k")
        assert store.get("k") is None
    finally:
        store.dispose()


def test_read_all_rehydrates_every_row() -> None:
    """read_all() returns every (key, value, updated_at) row for rehydrate."""
    store = _make_store()
    try:
        store.upsert("a", {"n": 1}, _AT1)
        store.upsert("b", {"n": 2}, _AT2)
        rows = {r["key"]: r for r in store.read_all()}
        assert set(rows) == {"a", "b"}
        assert rows["a"]["value"] == {"n": 1}
        assert rows["a"]["updated_at"] == _AT1
        assert rows["b"]["value"] == {"n": 2}
        assert rows["b"]["updated_at"] == _AT2
    finally:
        store.dispose()


def test_build_system_store_table_is_idempotent() -> None:
    """The registrar reuses an already-registered table on a shared backend."""
    backend = SqlEngine(SqlSettings.default())
    try:
        first = build_system_store_table(backend.metadata)
        second = build_system_store_table(backend.metadata)
        assert first is second
        assert "key" in first.c
        assert first.c.key.primary_key is True
    finally:
        backend.dispose()
