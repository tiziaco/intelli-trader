"""Unit tests for the ``VenueStore`` per-venue config + enabled durable store (STORE-02).

Exercises the ``HaltRecordStore``-template clone over an in-memory SQLite ``SqlEngine``:
config/enabled round-trip, the ``list_enabled`` typed-column query, and — the D-05
defense-in-depth arm — the recursive secret-denylist guard that rejects a secret-like key at
ANY depth (top-level and nested) with a ``ValidationError`` BEFORE any write (Pitfall 6).

4-space indentation. NO ``__init__.py`` in this dir (package-collision hazard).
``filterwarnings=["error"]`` → every store wrapped in ``try/finally: store.dispose()``.
"""

from datetime import UTC, datetime

import pytest

from itrader.config.sql import SqlSettings
from itrader.core.exceptions import ValidationError
from itrader.storage import SqlEngine
from itrader.storage.venue_store import VenueStore, build_venue_store_table

_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_store() -> VenueStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite."""
    return VenueStore(SqlEngine(SqlSettings.default()))


def test_upsert_get_round_trip() -> None:
    """upsert(venue, config, enabled, at) → get(venue) round-trips config/enabled/updated_at."""
    store = _make_store()
    try:
        config = {"region": "eea", "sandbox": True, "rate_limit": 10}
        store.upsert("okx", config, True, _AT)
        row = store.get("okx")
        assert row is not None
        assert row["config"] == config
        assert row["enabled"] is True
        assert row["updated_at"] == _AT
    finally:
        store.dispose()


def test_list_enabled_returns_only_enabled() -> None:
    """list_enabled() returns only enabled=True venues (typed-column query)."""
    store = _make_store()
    try:
        store.upsert("okx", {"region": "eea"}, True, _AT)
        store.upsert("binance", {"region": "global"}, False, _AT)
        store.upsert("kraken", {"region": "us"}, True, _AT)
        names = {row["venue_name"] for row in store.list_enabled()}
        assert names == {"okx", "kraken"}
    finally:
        store.dispose()


def test_top_level_secret_key_rejected_and_writes_nothing() -> None:
    """A top-level secret-like key raises ValidationError and leaves the store empty."""
    store = _make_store()
    try:
        with pytest.raises(ValidationError):
            store.upsert("okx", {"api_key": "leaked", "region": "eea"}, True, _AT)
        assert store.get("okx") is None
        assert store.read_all() == []
    finally:
        store.dispose()


def test_nested_secret_key_rejected_and_writes_nothing() -> None:
    """A secret-like key nested at depth raises ValidationError and writes nothing (Pitfall 6)."""
    store = _make_store()
    try:
        with pytest.raises(ValidationError):
            store.upsert(
                "okx",
                {"region": "eea", "nested": {"deeper": {"password": "leaked"}}},
                True,
                _AT,
            )
        assert store.get("okx") is None
    finally:
        store.dispose()


def test_secret_key_in_list_of_dicts_rejected() -> None:
    """A secret-like key inside a list-of-dicts is caught by the recursive walk (Pitfall 6)."""
    store = _make_store()
    try:
        with pytest.raises(ValidationError):
            store.upsert(
                "okx",
                {"accounts": [{"name": "main"}, {"secret": "leaked"}]},
                True,
                _AT,
            )
        assert store.get("okx") is None
    finally:
        store.dispose()


def test_delete_and_read_all() -> None:
    """delete(venue) removes the row; read_all rehydrates every venue."""
    store = _make_store()
    try:
        store.upsert("okx", {"region": "eea"}, True, _AT)
        store.upsert("binance", {"region": "global"}, False, _AT)
        assert {r["venue_name"] for r in store.read_all()} == {"okx", "binance"}
        store.delete("okx")
        assert store.get("okx") is None
        assert {r["venue_name"] for r in store.read_all()} == {"binance"}
    finally:
        store.dispose()


def test_build_venue_store_table_is_idempotent() -> None:
    """The registrar reuses an already-registered table; enabled is a typed Boolean column."""
    backend = SqlEngine(SqlSettings.default())
    try:
        first = build_venue_store_table(backend.metadata)
        second = build_venue_store_table(backend.metadata)
        assert first is second
        assert first.c.venue_name.primary_key is True
        assert "enabled" in first.c
    finally:
        backend.dispose()
