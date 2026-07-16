"""RETAIN-01/02/03 — ``CachedSqlOrderStorage`` live-wrapper concern tests (GATE-02 gate-b).

The order seam's live decorator composes the gate-passed Phase-3 ``SqlOrderStorage`` (system of
record) with an in-memory ``InMemoryOrderStorage`` working set. These tests exercise the six live
concerns over the testcontainers Postgres substrate (the ``pg_backend`` fixture in
``conftest.py`` — reused, never a second container; Dockerless runs skip via ``pg_engine``, D-11):

* ``test_evict_read_through``      — a terminalized standalone order is purged from the cache and
  reads back via read-through to the store (D-02 immediate purge + read-through).
* ``test_flat_rss``               — the cache working set stays bounded by the live/active count
  while the store row count grows unbounded (retention / flat-RSS).
* ``test_bracket_parent_resident``— a filled bracket parent stays resident until ALL children
  terminalize, then is purged (D-02 terminal-state gate + bracket-parent-resident).
* ``test_rehydrate_open_only``     — restart rehydration loads open-only (+ the brackets of live
  children) and never standalone terminal history (D-03 load-open-only).
* ``test_crash_restart``          — orders store-committed before a crash rehydrate order-stable
  into the new working set (D-03 / Pitfall 10 stable ORDER BY).
* ``test_atomic_within_method``   — the Pitfall-8 within-method target: a mid-``add_order`` txn
  failure leaves NO half-written order (orders row + state-change rows are all-or-nothing).

A1 (research): the atomicity test targets WITHIN-method atomicity only. Cross-method bracket
atomicity (a 3-call bracket assembled across three ``add_order`` calls) is N+4 reconciliation's
job, NOT a Phase-4 failure — so there is deliberately NO test asserting a 3-call bracket is one
transaction. The wrapper persists per-write store-first, FK-ordered (parent before children).

4-space indentation (matches ``tests/integration/*``); NO ``__init__.py`` in this dir
(auto-memory: package-collision hazard). Folder-derived ``integration``/``slow`` markers.
"""

from decimal import Decimal
from datetime import datetime, timezone

import pytest
import uuid_utils.compat as uc
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from itrader.core.enums import OrderStatus, OrderTriggerSource, OrderType, Side
from itrader.core.ids import PortfolioId, StrategyId
from itrader.order_handler.order import Order
from itrader.order_handler.storage.cached_sql_storage import CachedSqlOrderStorage
from itrader.order_handler.storage.sql_storage import SqlOrderStorage

# A business time (never wall clock) reused so derived created_at/updated_at are deterministic.
_BT = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _drop_operational_order_tables(pg_backend):
    """Keep the shared session Postgres container pristine for sibling storage tests.

    ``_make_storage`` builds the order schema via ``create_all`` on the session-scoped
    container. This file sorts alphabetically BEFORE ``test_migrations.py``, whose
    ``alembic upgrade head`` would raise ``ProgrammingError`` on the pre-existing ``orders`` /
    ``order_state_changes`` tables. Drop them in teardown (child table first for the FK) so the
    container is left clean — the same pristine-container discipline ``test_migrations`` follows
    with its ``downgrade base``. This fixture's teardown runs before ``pg_backend`` disposes
    (LIFO), so the engine is still live.

    ``SqlOrderStorage`` also registers the D-25 cardinality-1 ``order_config`` table (Plan 03),
    which ``create_all`` builds on the shared container too. Since Phase 9's ``module_config``
    migration now creates ``order_config`` during ``upgrade head``, a leftover would collide —
    so it is dropped here as well (no FK, order-independent).
    """
    yield
    with pg_backend.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS order_state_changes CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS orders CASCADE"))
        conn.execute(text("DROP TABLE IF EXISTS order_config CASCADE"))


def _make_storage(pg_backend):
    """Build the wrapper under test over the Postgres substrate (D-09 — create_all, no Alembic)."""
    store = SqlOrderStorage(pg_backend)
    # Idempotent (SqlOrderStorage.__init__ already created the tables); explicit per D-09.
    pg_backend.metadata.create_all(pg_backend.engine)
    return CachedSqlOrderStorage(store)


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


def test_evict_read_through(pg_backend):
    """A terminalized standalone order leaves the cache and reads back via store read-through."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())
    order = _make_order(portfolio_id=pid)

    storage.add_order(order)
    # Resident while open: present in the cache working set.
    assert storage._cache.get_order_by_id(order.id) is not None
    assert [o.id for o in storage.get_active_orders(pid)] == [order.id]

    _terminalize(storage, order, OrderStatus.FILLED)

    # Purged from the cache working set (D-02 immediate purge on terminalize).
    assert storage._cache.get_order_by_id(order.id) is None
    assert storage.get_active_orders(pid) == []
    # But still served via read-through to the store (the system of record).
    got = storage.get_order_by_id(order.id)
    assert got is not None
    assert got.status == OrderStatus.FILLED


def test_flat_rss(pg_backend):
    """The cache working set stays bounded by the active count while the store grows to N."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())
    total = 200
    keep_open = 10

    orders = []
    for _ in range(total):
        order = _make_order(portfolio_id=pid)
        storage.add_order(order)
        orders.append(order)

    # Terminalize all but ``keep_open`` standalone orders.
    for order in orders[keep_open:]:
        _terminalize(storage, order, OrderStatus.FILLED)

    # Cache working set is bounded by the live/active count, NOT by N.
    assert len(storage._cache._by_id) == keep_open
    assert len(storage.get_active_orders(pid)) == keep_open
    # The store, by contrast, retains every row (terminal history grows unbounded).
    assert sum(storage.count_orders_by_status(pid).values()) == total


def test_bracket_parent_resident(pg_backend):
    """A filled bracket parent stays resident until ALL children terminalize, then is purged."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    # The bracket entry parent has FILLED (terminal); its SL/TP children are still live.
    parent = _make_order(portfolio_id=pid, status=OrderStatus.FILLED)
    child_sl = _make_order(
        portfolio_id=pid, parent_order_id=parent.id, type=OrderType.STOP, action=Side.SELL
    )
    child_tp = _make_order(
        portfolio_id=pid, parent_order_id=parent.id, type=OrderType.LIMIT, action=Side.SELL
    )
    # child_order_ids is NOT a column (D-02) — set it on the in-memory parent so the wrapper's
    # bracket-parent-resident gate can evaluate it.
    parent.child_order_ids = [child_sl.id, child_tp.id]

    storage.add_order(parent)  # parent FIRST — the self-ref FK target must exist
    storage.add_order(child_sl)
    storage.add_order(child_tp)

    # Terminalize ONE child: the filled parent + the other child stay resident.
    _terminalize(storage, child_sl, OrderStatus.FILLED)
    assert storage._cache.get_order_by_id(parent.id) is not None
    assert storage._cache.get_order_by_id(child_tp.id) is not None
    assert storage._cache.get_order_by_id(child_sl.id) is None

    # Terminalize the LAST child: the parent is now evictable and purged.
    _terminalize(storage, child_tp, OrderStatus.FILLED)
    assert storage._cache.get_order_by_id(parent.id) is None
    # Still served from the store via read-through.
    assert storage.get_order_by_id(parent.id) is not None


def test_rehydrate_open_only(pg_backend):
    """Restart rehydration loads the open set + live-child brackets, never standalone terminals."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    open_one = _make_order(portfolio_id=pid)
    open_two = _make_order(portfolio_id=pid)
    standalone_terminal = _make_order(portfolio_id=pid)
    filled_parent = _make_order(portfolio_id=pid, status=OrderStatus.FILLED)
    live_child = _make_order(portfolio_id=pid, parent_order_id=filled_parent.id, action=Side.SELL)

    storage.add_order(open_one)
    storage.add_order(open_two)
    storage.add_order(standalone_terminal)
    _terminalize(storage, standalone_terminal, OrderStatus.FILLED)
    storage.add_order(filled_parent)  # parent FIRST (FK)
    storage.add_order(live_child)

    # Fresh wrapper over the SAME database — simulate a process restart.
    fresh = CachedSqlOrderStorage(SqlOrderStorage(pg_backend))
    fresh.rehydrate()

    # Open orders + the live child are resident.
    assert fresh._cache.get_order_by_id(open_one.id) is not None
    assert fresh._cache.get_order_by_id(open_two.id) is not None
    assert fresh._cache.get_order_by_id(live_child.id) is not None
    # The live child's (terminal) parent is pulled in (bracket-parent-resident on rehydrate).
    assert fresh._cache.get_order_by_id(filled_parent.id) is not None
    # A standalone terminal order is NEVER rehydrated into the working set (D-03 open-only).
    assert fresh._cache.get_order_by_id(standalone_terminal.id) is None


def test_crash_restart(pg_backend):
    """Store-committed open orders rehydrate order-stable into the new working set after a crash."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    pre_crash = [_make_order(portfolio_id=pid) for _ in range(3)]
    for order in pre_crash:
        storage.add_order(order)

    # Drop the pre-crash wrapper; bring up a fresh one over the same store and rehydrate.
    fresh = CachedSqlOrderStorage(SqlOrderStorage(pg_backend))
    fresh.rehydrate()

    rehydrated_ids = [o.id for o in fresh.get_active_orders(pid)]
    # The rehydrated working set equals the pre-crash open set (no loss, no extras for this pid).
    assert set(rehydrated_ids) == {o.id for o in pre_crash}
    # Order-stable: the cache order matches the store's stable (created_at, id) ORDER BY (Pitfall 10).
    assert rehydrated_ids == [o.id for o in fresh._store.get_active_orders(pid)]


def test_atomic_within_method(pg_backend, monkeypatch):
    """Pitfall 8 within-method atomicity: a mid-add_order txn failure writes NO half order.

    Force the second insert (order_state_changes) to violate the ``to_status`` NOT NULL
    constraint AFTER the orders row insert in the same ``engine.begin()`` transaction; the
    whole transaction must roll back, leaving neither an orders row nor state-change rows.
    """
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())
    order = _make_order(portfolio_id=pid)

    def _bad_state_change_rows(o):
        # A single row that passes the orders insert but violates to_status NOT NULL.
        return [
            {
                "order_id": o.id,
                "seq": 0,
                "from_status": None,
                "to_status": None,  # NOT NULL violation -> IntegrityError mid-transaction
                "timestamp": o.time,
                "reason": "atomicity probe",
                "triggered_by": "system",
                "additional_data": None,
            }
        ]

    monkeypatch.setattr(storage._store, "_state_change_rows", _bad_state_change_rows)

    with pytest.raises(IntegrityError):
        storage.add_order(order)

    # All-or-nothing: the orders row never persisted (store-first means the cache never saw it).
    assert storage._store.get_order_by_id(order.id) is None
    assert storage._cache.get_order_by_id(order.id) is None
    assert storage._store.get_order_history(order.id) == []


def test_terminal_add_order_not_resident(pg_backend):
    """CR-01 — a terminal order persisted straight through ``add_order`` (the audited REJECTED
    admission path: admission_manager.py persists every sizing/direction/validator rejection via
    ``add_order``) is purged on the add-time terminal-state gate, so it never stays resident and
    repeated rejections do not grow the working set (flat-RSS on the add_order path)."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    rejected = _make_order(portfolio_id=pid, status=OrderStatus.REJECTED)
    assert rejected.is_terminal  # guards the precondition the gate keys on
    storage.add_order(rejected)

    # Not resident in the working set (purged at add time, CR-01) ...
    assert storage._cache.get_order_by_id(rejected.id) is None
    assert storage.get_active_orders(pid) == []
    # ... but durably persisted and served via read-through to the store.
    got = storage.get_order_by_id(rejected.id)
    assert got is not None
    assert got.status == OrderStatus.REJECTED

    # Many rejections never accumulate in the cache; the store keeps every audit row.
    for _ in range(50):
        storage.add_order(_make_order(portfolio_id=pid, status=OrderStatus.REJECTED))
    assert len(storage._cache._by_id) == 0
    assert sum(storage.count_orders_by_status(pid).values()) == 51


def test_clear_evicts_orphaned_terminal_parent(pg_backend):
    """WR-02 — ``clear_portfolio_orders`` drops only active children; a terminal bracket parent
    held resident under bracket-parent-resident is re-evaluated and evicted (not leaked until
    restart) once its live children are cleared."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    parent = _make_order(portfolio_id=pid, status=OrderStatus.FILLED)
    child_sl = _make_order(
        portfolio_id=pid, parent_order_id=parent.id, type=OrderType.STOP, action=Side.SELL
    )
    child_tp = _make_order(
        portfolio_id=pid, parent_order_id=parent.id, type=OrderType.LIMIT, action=Side.SELL
    )
    parent.child_order_ids = [child_sl.id, child_tp.id]

    storage.add_order(parent)  # parent FIRST (self-ref FK target)
    storage.add_order(child_sl)
    storage.add_order(child_tp)
    assert storage._cache.get_order_by_id(parent.id) is not None  # terminal parent, live children

    storage.clear_portfolio_orders(pid)  # clears the two live children

    # The now-orphaned terminal parent is evicted (WR-02); the cache is empty ...
    assert storage._cache.get_order_by_id(parent.id) is None
    assert len(storage._cache._by_id) == 0
    # ... and the parent is still served from the store via read-through.
    assert storage.get_order_by_id(parent.id) is not None


def test_remove_by_ticker_evicts_orphaned_terminal_parent(pg_backend):
    """WR-02 — ``remove_orders_by_ticker`` mirrors ``clear``: an orphaned terminal bracket parent
    is re-evaluated and evicted after its last live child for the ticker is removed."""
    storage = _make_storage(pg_backend)
    pid = PortfolioId(uc.uuid7())

    parent = _make_order(portfolio_id=pid, status=OrderStatus.FILLED, ticker="ETHUSD")
    child = _make_order(
        portfolio_id=pid, parent_order_id=parent.id, ticker="ETHUSD",
        type=OrderType.STOP, action=Side.SELL,
    )
    parent.child_order_ids = [child.id]

    storage.add_order(parent)
    storage.add_order(child)
    assert storage._cache.get_order_by_id(parent.id) is not None

    storage.remove_orders_by_ticker("ETHUSD", pid)

    assert storage._cache.get_order_by_id(parent.id) is None
    assert storage.get_order_by_id(parent.id) is not None
