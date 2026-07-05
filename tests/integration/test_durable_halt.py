"""05.2-06 (D-10 / ARCH-4 Layer 2) — the HALTED latch survives a process restart.

Phase 05.1 D-05 landed an IN-PROCESS HALTED latch, but a supervised auto-restart builds a
FRESH ``LiveTradingSystem`` whose in-process ``_status`` is ``STOPPED`` — so a breaker-class
halt whose cause is not re-detectable at start would be silently cleared. This plan adds a
DURABLE halt record on the shared ``SqlBackend`` spine: ``halt()`` persists it, ``start()``
refuses RUNNING while an unresolved record exists (the DURABLE record is what latches across a
restart), and ``reset_halt()`` resolves it.

Security (V7 secret-scrub, T-05.2-18): the durable record persists ONLY the machine-readable
reason literal + timestamp — never ``str(exc)`` or a connector payload. The schema deliberately
has NO free-form exception/payload column.

Two arms:

* **Store round-trip (Task 1).** ``HaltRecordStore`` over an in-memory ``SqlBackend`` double:
  record → ``has_unresolved()`` True → ``resolve_all()`` → False.
* **Fresh-instance refuse-RUNNING (Task 2).** A FRESH ``LiveTradingSystem`` sharing the SAME
  store (in-process ``_status`` STOPPED) refuses RUNNING while the durable record is unresolved;
  ``reset_halt()`` resolves it so a subsequent ``start()`` is no longer refused. Asserting on the
  SAME object would only re-test the D-05 in-process latch — the observable MUST be a fresh
  instance (RESEARCH Pitfall 7).

4-space indentation (``tests/integration/*`` convention); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration`` marker. The in-memory
``:memory:`` SQLite double keeps this fully OFFLINE — no Docker, no Postgres, no credentials.
"""

from datetime import UTC, datetime

from itrader.config.sql import SqlSettings
from itrader.storage import SqlBackend
from itrader.storage.halt_record_store import HaltRecordStore


def _make_store() -> HaltRecordStore:
    """An in-memory durable double — the shared ``SqlBackend`` on ``:memory:`` SQLite.

    ``SqlSettings.default()`` pins the in-process SQLite arm; the ``SingletonThreadPool``
    that pysqlite uses for ``:memory:`` keeps the same in-memory DB alive across
    ``engine.begin()`` calls on the test thread, so a single store instance persists its
    rows for the life of the test (the fresh-instance arm shares ONE store).
    """
    return HaltRecordStore(SqlBackend(SqlSettings.default()))


def test_halt_record_round_trip() -> None:
    """record → has_unresolved True → get_unresolved returns the literal → resolve → False.

    RED before ``halt_record_store`` existed (ImportError); GREEN once the store + its
    chained migration land. Proves ONLY the reason literal + timestamp are stored.
    """
    store = _make_store()
    assert store.has_unresolved() is False
    assert store.get_unresolved() is None

    at = datetime(2026, 7, 5, 12, 0, 0, tzinfo=UTC)
    store.record_halt("drift", at)

    assert store.has_unresolved() is True
    record = store.get_unresolved()
    assert record is not None
    # The machine-readable literal + timestamp round-trip — nothing else is persisted.
    assert record.reason == "drift"
    assert record.created_at == at

    store.resolve_all()
    assert store.has_unresolved() is False
    assert store.get_unresolved() is None
