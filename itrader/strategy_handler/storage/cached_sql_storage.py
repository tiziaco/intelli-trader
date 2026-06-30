"""Live-only ``CachedSqlSignalStorage`` — the signal-seam write-through wrapper (D-04).

The simplest of the three Phase-4 cached-SQL wrappers. It *composes* (has-a, D-04 — never a
cross-concern god base) the untouched Phase-3 ``SqlSignalStorage`` (system of record) with an
in-memory ``InMemorySignalStore`` working set and implements the 4-method ``SignalStore`` ABC
by forwarding. Signals are append-only and NEVER purged (D-02's purge gate applies to
orders/positions, not signals), so there is NO terminal-state gate and NO read-through — the
cache is a pure FULL mirror:

- ``add`` is store-first then cache-mirror (Pitfall 8 persist-then-acknowledge): the durable
  Postgres write commits BEFORE the in-memory mirror is touched, so the cache is always
  rebuildable from the store (the inverse is not). A duplicate ``signal_id`` is rejected up
  front with the working set's own ``ValueError`` (the mirror inherits
  ``InMemorySignalStore``'s contract, in_memory_storage.py:41) so no doomed row is written.
- ``get_all`` / ``by_strategy`` / ``by_ticker`` serve straight from the full cache mirror.
- ``rehydrate`` (optional) rebuilds the mirror from the store's stable-ORDER BY read.

The wrapper writes NO SQL of its own (T-04-01) — it forwards to the parameterized-Core
Phase-3 store; it sources the injected backend and never re-resolves DB creds (T-04-02 /
SEC-01). It is NOT re-exported from ``__init__.py`` and ``SqlSignalStorage`` is imported under
``TYPE_CHECKING`` only, so importing the backtest path never pulls SQLAlchemy (GATE-01
inertness — the factory ``'live'`` arm imports this lazily).

A single ``threading.RLock`` guards the mirror — uncontended under the daemon-sole-writer
contract, but API-thread-safe for the imminent FastAPI layer (research A4).

4-space indentation (matches the ``strategy_handler/storage/`` siblings).
"""

import threading
from typing import List, TYPE_CHECKING

from itrader.core.ids import StrategyId
from itrader.logger import get_itrader_logger
from itrader.strategy_handler.storage.base import SignalStore
from itrader.strategy_handler.storage.in_memory_storage import InMemorySignalStore

if TYPE_CHECKING:
    # Type-only — keep the module SQL-import-light (GATE-01 quarantine).
    from itrader.strategy_handler.signal_record import SignalRecord
    from itrader.strategy_handler.storage.sql_storage import SqlSignalStorage


class CachedSqlSignalStorage(SignalStore):
    """Store-first, append-only full-mirror signal store (live-only, D-04).

    Composes a ``SqlSignalStorage`` (system of record) and an ``InMemorySignalStore``
    (full working-set mirror). Signals are never purged, so the mirror is exhaustive and
    every read serves from it — no read-through, no terminal-state gate.

    Parameters
    ----------
    store:
        The untouched Phase-3 ``SqlSignalStorage`` to compose as the durable system of
        record. The wrapper forwards writes to it store-first and mirrors into the cache.
    """

    def __init__(self, store: "SqlSignalStorage") -> None:
        self._store = store
        # CACHE-CLASS: (d) live-retention working-set cache (built in Phase 4) — see docs/CACHE-CLASSIFICATION.md
        self._cache = InMemorySignalStore()
        self._lock = threading.RLock()
        self.logger = get_itrader_logger().bind(component="CachedSqlSignalStorage")

    def add(self, record: "SignalRecord") -> None:
        """Persist store-first, then mirror into the cache (Pitfall 8).

        The duplicate-id check, the store write and the cache mirror all run under ONE lock
        acquisition so they are atomic: a concurrent second writer of the same ``signal_id``
        cannot slip between the check and the persist and provoke a partial-commit
        ``IntegrityError`` — it always sees the resident first record and fails fast with the
        house ``ValueError`` (the mirror inherits ``InMemorySignalStore``'s contract), and no
        doomed row is written. Store-first ordering is preserved within the lock (durable write
        commits before the mirror is touched). The lock is uncontended under the daemon-sole-
        writer wiring; this holds it across the store I/O to stay correct for the FastAPI layer.
        """
        with self._lock:
            if any(r.signal_id == record.signal_id for r in self._cache.get_all()):
                raise ValueError(f"duplicate signal_id: {record.signal_id!r}")
            self._store.add(record)
            self._cache.add(record)

    def get_all(self) -> List["SignalRecord"]:
        """Return every mirrored record (full mirror — no read-through)."""
        with self._lock:
            return self._cache.get_all()

    def by_strategy(self, strategy_id: StrategyId) -> List["SignalRecord"]:
        """Return the mirror's records produced by ``strategy_id`` (no store touch)."""
        with self._lock:
            return self._cache.by_strategy(strategy_id)

    def by_ticker(self, ticker: str) -> List["SignalRecord"]:
        """Return the mirror's records targeting ``ticker`` (no store touch)."""
        with self._lock:
            return self._cache.by_ticker(ticker)

    def rehydrate(self) -> None:
        """Rebuild the full mirror from the store's stable-ORDER BY read (optional).

        Re-creates the working set then re-mirrors every persisted record in the store's
        deterministic ``(time, signal_id)`` order (Pitfall 10), making the call an
        idempotent full refresh.
        """
        with self._lock:
            self._cache = InMemorySignalStore()
            for record in self._store.get_all():
                self._cache.add(record)
