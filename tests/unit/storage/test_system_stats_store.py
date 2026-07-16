"""Unit tests for the ``SystemStatsStore`` append-only engine-operational series (RTCFG-06/D-18).

A disciplined clone of the ``SystemStore`` test exercised over an in-memory SQLite
``SqlEngine`` double. Proves: an append round-trips via ``read_recent``/``read_all`` with
the correct engine-written ``seq`` + business ``timestamp``; multiple appends read back in
stable ``seq`` order; reads are lock-free (RTCFG-06 — the store holds NO threading lock, so
a UI read can never stall the engine thread); and the sibling ``state.*`` read-model KV
surface (``SystemStore``) round-trips ``state.status``/``state.halt_reason`` (D-19).

4-space indentation (matches ``itrader/storage`` + the storage test convention). NO
``__init__.py`` in this dir (auto-memory: package-collision hazard). ``filterwarnings=["error"]``
turns an unclosed-sqlite ``ResourceWarning`` into a failure, so every store is wrapped in
``try/finally: store.dispose()``.
"""

from datetime import UTC, datetime
from decimal import Decimal

from itrader.config.sql import SqlSettings
from itrader.storage import SqlEngine
from itrader.storage.system_stats_store import (
    SystemStatsStore,
    build_system_stats_table,
)
from itrader.storage.system_store import SystemStore
from tests.support.schema import provision_schema

# FIXED timezone-aware instants (D-07 determinism — the store is clock-free; the caller
# supplies ``at``).
_AT1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_AT2 = datetime(2026, 1, 2, 9, 30, 0, tzinfo=UTC)
_AT3 = datetime(2026, 1, 3, 6, 15, 0, tzinfo=UTC)


def _counter_row(
    *,
    breaches: int = 0,
    warnings: int = 0,
    errors: int = 0,
    criticals: int = 0,
    queue_depth: int = 0,
    uptime: str = "0",
    connector_up: bool = True,
    stream_up: bool = True,
) -> dict[str, object]:
    """A full engine-operational counter row (all columns the store's ``append`` needs)."""
    return {
        "throttle_breach_count": breaches,
        "error_count_warning": warnings,
        "error_count_error": errors,
        "error_count_critical": criticals,
        "queue_depth": queue_depth,
        "uptime_seconds": Decimal(uptime),
        "connector_up": connector_up,
        "stream_up": stream_up,
    }


def _make_stats_store() -> SystemStatsStore:
    """An in-memory durable double — the shared ``SqlEngine`` on ``:memory:`` SQLite.

    WR-03/D-14 — schema-pure, so provision the schema explicitly after construction (before
    the first query) via the shared ``provision_schema`` helper.
    """
    store = SystemStatsStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    return store


def test_append_read_round_trip() -> None:
    """append(row, at) → read_recent/read_all returns the row with seq 0 + the exact at."""
    store = _make_stats_store()
    try:
        seq = store.append(
            _counter_row(
                breaches=3,
                warnings=1,
                errors=2,
                criticals=0,
                queue_depth=7,
                uptime="12.5",
                connector_up=True,
                stream_up=False,
            ),
            _AT1,
        )
        assert seq == 0  # engine writes the first seq (no DB autoincrement).

        recent = store.read_recent(5)
        assert len(recent) == 1
        row = recent[0]
        assert row["seq"] == 0
        assert row["timestamp"] == _AT1
        assert row["throttle_breach_count"] == 3
        assert row["error_count_warning"] == 1
        assert row["error_count_error"] == 2
        assert row["error_count_critical"] == 0
        assert row["queue_depth"] == 7
        assert row["uptime_seconds"] == Decimal("12.5")
        assert row["connector_up"] is True
        assert row["stream_up"] is False

        # read_all returns the same single row.
        assert store.read_all() == recent
    finally:
        store.dispose()


def test_seq_is_engine_written_and_monotonic() -> None:
    """Multiple appends assign 0,1,2 and read back in stable seq order (D-18)."""
    store = _make_stats_store()
    try:
        assert store.append(_counter_row(breaches=1), _AT1) == 0
        assert store.append(_counter_row(breaches=2), _AT2) == 1
        assert store.append(_counter_row(breaches=3), _AT3) == 2

        # read_all is ascending (chronological): seq 0,1,2.
        all_rows = store.read_all()
        assert [r["seq"] for r in all_rows] == [0, 1, 2]
        assert [r["throttle_breach_count"] for r in all_rows] == [1, 2, 3]
        assert [r["timestamp"] for r in all_rows] == [_AT1, _AT2, _AT3]

        # read_recent is descending (newest first).
        recent = store.read_recent(2)
        assert [r["seq"] for r in recent] == [2, 1]
    finally:
        store.dispose()


def test_reads_are_lock_free() -> None:
    """RTCFG-06: the store holds NO threading lock — reads can never stall the engine thread.

    A structural proof of the lock-free-read contract: the store exposes no lock attribute
    (its reads go through a plain ``engine.connect()``), so a UI read touches no hot-path
    lock. Paired with a functional read to prove the read path itself works with no lock
    ever acquired.
    """
    store = _make_stats_store()
    try:
        import threading

        for name in vars(store):
            assert not isinstance(getattr(store, name), (
                type(threading.Lock()),
                type(threading.RLock()),
            )), f"{name} is a lock — reads must be lock-free (RTCFG-06)"

        store.append(_counter_row(queue_depth=5), _AT1)
        assert store.read_recent(1)[0]["queue_depth"] == 5
    finally:
        store.dispose()


def test_build_system_stats_table_is_idempotent() -> None:
    """The registrar reuses an already-registered table on a shared backend (single-source)."""
    backend = SqlEngine(SqlSettings.default())
    try:
        first = build_system_stats_table(backend.metadata)
        second = build_system_stats_table(backend.metadata)
        assert first is second
        assert "seq" in first.c
        assert first.c.seq.primary_key is True
        assert first.c.seq.autoincrement is False
        assert "throttle_breach_count" in first.c
    finally:
        backend.dispose()


def test_state_kv_upsert_round_trips() -> None:
    """D-19: the sibling read-model ``state.*`` KV (SystemStore) round-trips status/halt_reason.

    ``SystemStatsStore`` holds the operational SERIES; the discrete low-rate ``state.*`` KV
    (``state.status``/``state.halt_reason``/``state.last_started_at``/``state.last_error``)
    lives in ``SystemStore`` — the two together are the RTCFG-06 read-model surface. Proves
    the KV path the SafetyController/facade write at their event sources round-trips.
    """
    store = SystemStore(SqlEngine(SqlSettings.default()))
    provision_schema(store.backend)
    try:
        store.upsert("state.status", {"status": "RUNNING"}, _AT1)
        store.upsert("state.halt_reason", {"halt_reason": "drift"}, _AT2)

        status_row = store.get("state.status")
        assert status_row is not None
        assert status_row["value"] == {"status": "RUNNING"}
        assert status_row["updated_at"] == _AT1

        halt_row = store.get("state.halt_reason")
        assert halt_row is not None
        assert halt_row["value"] == {"halt_reason": "drift"}

        # Last-write-wins on the same key (a subsequent transition overwrites status).
        store.upsert("state.status", {"status": "HALTED"}, _AT3)
        assert store.get("state.status")["value"] == {"status": "HALTED"}
    finally:
        store.dispose()
