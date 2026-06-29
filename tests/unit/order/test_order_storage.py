import uuid
from datetime import datetime, UTC
from queue import Queue
from types import SimpleNamespace

import pytest

from itrader.order_handler.storage import InMemoryOrderStorage, OrderStorageFactory
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus, OrderTriggerSource, Side
from itrader.core.exceptions import ConfigurationError
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler


# --- InMemoryOrderStorage ---------------------------------------------------


@pytest.fixture
def store():
    """In-memory storage seeded with three native-UUID orders.

    Storage keys by native ``uuid.UUID`` (D-14) and holds a SINGLE flat
    ``{order_id: order}`` dict (D-20/PERF3) — no nested per-portfolio dicts
    exist. "Active" is purely an entity predicate (``order.is_active``);
    queries scan-and-filter the flat dict. Tests assert this through the
    public ``get_order_by_id`` query API, not the private storage shape.
    """
    storage = InMemoryOrderStorage()

    pid1 = uuid.uuid4()
    pid2 = uuid.uuid4()
    oid1 = uuid.uuid4()
    oid2 = uuid.uuid4()
    oid3 = uuid.uuid4()

    order1 = Order(
        time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action=Side.BUY, price=40000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=pid1, id=oid1,
    )
    order2 = Order(
        time=datetime.now(UTC), type=OrderType.LIMIT, status=OrderStatus.PENDING,
        ticker="ETHUSDT", action=Side.SELL, price=3000.0, quantity=0.5,
        exchange="binance", strategy_id=1, portfolio_id=pid1, id=oid2,
    )
    order3 = Order(
        time=datetime.now(UTC), type=OrderType.STOP, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action=Side.SELL, price=39000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=pid2, id=oid3,
    )

    return SimpleNamespace(
        storage=storage,
        pid1=pid1, pid2=pid2, oid1=oid1, oid2=oid2, oid3=oid3,
        order1=order1, order2=order2, order3=order3,
    )


def test_add_order(store):
    """Test adding orders to storage."""
    store.storage.add_order(store.order1)

    pending_orders = store.storage.get_pending_orders()
    assert len(pending_orders) == 1
    assert store.pid1 in pending_orders  # portfolio_id as native UUID
    assert store.oid1 in pending_orders[store.pid1]  # order_id as native UUID
    assert pending_orders[store.pid1][store.oid1] == store.order1


def test_flat_dict_is_sole_container(store):
    """D-20/PERF3: a single flat container is the ONLY instance container.

    The nested per-portfolio dicts (active / all / archived) are deleted —
    M4-06 scan elimination. Order classes are predicates on the entity, not
    separate containers. We assert the deletion of the nested containers (no
    public surface exposes their absence) and confirm the single added order
    is the only one resolvable through the public ``get_order_by_id`` query.
    """
    storage = store.storage
    assert not hasattr(storage, "active_orders")
    assert not hasattr(storage, "all_orders")
    assert not hasattr(storage, "archived_orders")
    storage.add_order(store.order1)
    assert storage.get_order_by_id(store.oid1) == store.order1
    assert storage.get_order_by_id(store.oid2) is None
    assert storage.get_order_by_id(store.oid3) is None


def test_filled_order_leaves_active_queries_after_update(store):
    """A PENDING->FILLED transition + ``update_order`` drops it from active queries.

    With the active indexes (D-02/D-03), the storage write seam is where the
    index reconciles old->new: the order mutates status IN PLACE
    (``add_fill``), then the caller pairs it with ``update_order`` (the D-04
    invariant — reconcile_manager does exactly this). After the write, the
    FILLED order leaves both active queries; it stays in the flat dict as
    history (T-05-02).
    """
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order2)

    # Fill order1 in place — entity status transitions PENDING -> FILLED.
    assert store.order1.add_fill(
        store.order1.quantity, store.order1.price, store.order1.time
    )
    assert store.order1.status == OrderStatus.FILLED
    # D-04 invariant: the in-place mutation is paired with a storage write,
    # which reconciles the active index.
    assert store.storage.update_order(store.order1)

    # Active queries exclude it via the reconciled index.
    active = store.storage.get_active_orders(store.pid1)
    assert [o.id for o in active] == [store.oid2]
    pending = store.storage.get_pending_orders(store.pid1)
    assert store.oid1 not in pending[store.pid1]
    assert store.oid2 in pending[store.pid1]


def test_history_queries_return_filled_orders(store):
    """Filled (inactive) orders stay queryable from the flat dict (T-05-02).

    "All orders" audit semantics are preserved: a FILLED order leaves active
    queries but remains retrievable by id, status, and ticker.
    """
    store.storage.add_order(store.order1)
    assert store.order1.add_fill(
        store.order1.quantity, store.order1.price, store.order1.time
    )
    # D-04 invariant: pair the in-place fill with a storage write so the active
    # index reconciles (terminal-status queries below scan the flat dict, D-10).
    assert store.storage.update_order(store.order1)

    assert store.storage.get_order_by_id(store.oid1) == store.order1
    assert store.storage.get_orders_by_status(OrderStatus.FILLED, store.pid1) == [store.order1]
    assert store.storage.get_orders_by_ticker("BTCUSDT", store.pid1) == [store.order1]
    assert store.storage.get_active_orders(store.pid1) == []


def test_add_multiple_orders(store):
    """Test adding multiple orders across different portfolios."""
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order2)
    store.storage.add_order(store.order3)

    pending_orders = store.storage.get_pending_orders()
    assert len(pending_orders) == 2  # Two portfolios
    assert len(pending_orders[store.pid1]) == 2  # Two orders in portfolio 1
    assert len(pending_orders[store.pid2]) == 1  # One order in portfolio 2


def test_get_order_by_id(store):
    """Test retrieving orders by ID."""
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order3)

    # Test with portfolio_id specified
    assert store.storage.get_order_by_id(store.oid1, store.pid1) == store.order1
    # Test without portfolio_id (flat-index cross-portfolio lookup)
    assert store.storage.get_order_by_id(store.oid3) == store.order3
    # Test non-existent order
    assert store.storage.get_order_by_id(uuid.uuid4()) is None


def test_get_order_by_id_resolves_without_portfolio(store):
    """The flat index resolves a lookup with no portfolio_id / portfolio scan."""
    store.storage.add_order(store.order1)

    assert store.storage.get_order_by_id(store.oid1) is not None
    assert store.storage.get_order_by_id(store.oid1) == store.order1


def test_remove_order(store):
    """Test removing orders."""
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order2)

    # Remove with portfolio_id specified
    assert store.storage.remove_order(store.oid1, store.pid1)

    # Check it's gone (and pruned from the flat index)
    assert store.storage.get_order_by_id(store.oid1, store.pid1) is None
    assert store.storage.get_order_by_id(store.oid1) is None

    # Remove without portfolio_id
    assert store.storage.remove_order(store.oid2)
    assert store.storage.get_order_by_id(store.oid2) is None

    # Try to remove non-existent order
    assert not store.storage.remove_order(uuid.uuid4())


def test_remove_orders_by_ticker(store):
    """Test removing all orders for a ticker."""
    store.storage.add_order(store.order1)  # BTCUSDT
    store.storage.add_order(store.order2)  # ETHUSDT
    store.storage.add_order(store.order3)  # BTCUSDT in different portfolio

    # Remove BTCUSDT orders from portfolio 1
    assert store.storage.remove_orders_by_ticker("BTCUSDT", store.pid1) == 1

    # Check BTCUSDT order in portfolio 2 still exists
    assert store.storage.get_order_by_id(store.oid3, store.pid2) == store.order3
    # Check ETHUSDT order still exists
    assert store.storage.get_order_by_id(store.oid2, store.pid1) == store.order2


def test_get_orders_by_ticker(store):
    """Test getting orders by ticker."""
    store.storage.add_order(store.order1)  # BTCUSDT
    store.storage.add_order(store.order2)  # ETHUSDT
    store.storage.add_order(store.order3)  # BTCUSDT

    btc_orders = store.storage.get_orders_by_ticker("BTCUSDT")
    assert len(btc_orders) == 2

    btc_orders_p1 = store.storage.get_orders_by_ticker("BTCUSDT", store.pid1)
    assert len(btc_orders_p1) == 1
    assert btc_orders_p1[0] == store.order1


def test_update_order(store):
    """Test updating an existing order."""
    store.storage.add_order(store.order1)

    updated_order = Order(
        time=store.order1.time, type=store.order1.type, status=store.order1.status,
        ticker=store.order1.ticker, action=store.order1.action,
        price=41000.0,  # New price
        quantity=store.order1.quantity, exchange=store.order1.exchange,
        strategy_id=store.order1.strategy_id, portfolio_id=store.order1.portfolio_id,
        id=store.order1.id,
    )

    assert store.storage.update_order(updated_order)

    # Check the update (the public query reflects the new instance)
    found_order = store.storage.get_order_by_id(store.oid1, store.pid1)
    assert found_order.price == 41000.0
    assert store.storage.get_order_by_id(store.oid1).price == 41000.0


def test_clear_portfolio_orders(store):
    """Test clearing all orders for a portfolio."""
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order2)
    store.storage.add_order(store.order3)

    # Clear portfolio 1
    assert store.storage.clear_portfolio_orders(store.pid1) == 2

    # Check portfolio 1 orders are gone
    pending_orders = store.storage.get_pending_orders(store.pid1)
    assert len(pending_orders[store.pid1]) == 0

    # Check portfolio 2 orders still exist
    pending_orders = store.storage.get_pending_orders(store.pid2)
    assert len(pending_orders[store.pid2]) == 1


def test_add_rejected_order_persists_without_entering_active_book(store):
    """A REJECTED order persisted via add_order is auditable but never active (D-13).

    Rejected signals now leave a REJECTED order in storage: it must appear in
    the audit surface (by-status / by-id queries over the flat dict) while the
    active queries — get_pending_orders/get_active_orders — exclude it via the
    ``is_active`` predicate.
    """
    rejected = Order(
        time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action=Side.BUY, price=40000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=store.pid1,
    )
    assert rejected.add_state_change(
        OrderStatus.REJECTED, "validation failed", triggered_by=OrderTriggerSource.VALIDATOR
    )

    store.storage.add_order(store.order1)   # active PENDING order
    store.storage.add_order(rejected)       # persisted REJECTED order

    # Audit surface: retrievable by id and by status
    assert store.storage.get_order_by_id(rejected.id, store.pid1) == rejected
    by_status = store.storage.get_orders_by_status(OrderStatus.REJECTED, store.pid1)
    assert by_status == [rejected]

    # Active book: only the PENDING order — the REJECTED one never enters it
    active = store.storage.get_active_orders(store.pid1)
    assert [o.id for o in active] == [store.order1.id]
    pending = store.storage.get_pending_orders(store.pid1)
    assert rejected.id not in pending[store.pid1]
    assert store.order1.id in pending[store.pid1]


# --- D-09 order-equivalence + maintenance-matrix regression -----------------


def _active_oracle(storage, portfolio_id=None):
    """Independent oracle: scan ``_by_id`` in insertion order, filter is_active.

    Reproduces the prior full-scan semantics so index-backed output can be
    asserted byte-equal against it (D-09). GLOBAL add_order order on the None
    path; filtered to a portfolio otherwise.
    """
    return [
        o for o in storage._by_id.values()
        if o.is_active and (portfolio_id is None or o.portfolio_id == portfolio_id)
    ]


def test_active_queries_match_full_scan_equivalence(store):
    """D-09: index-backed query order == prior full-scan order (both paths).

    Seeds active orders across pid1/pid2, transitions one to FILLED (the active
    set is then non-trivial), and asserts the index-backed queries reproduce the
    independent flat-dict-scan oracle on the GLOBAL (None) path and the
    per-portfolio path, including get_orders_by_status(active) and the nested
    get_pending_orders shape.
    """
    s = store.storage
    s.add_order(store.order1)   # pid1 BTCUSDT PENDING
    s.add_order(store.order2)   # pid1 ETHUSDT PENDING
    s.add_order(store.order3)   # pid2 BTCUSDT PENDING

    # Transition order2 PENDING -> FILLED via the write seam so the active set
    # is non-trivial (a terminal order must drop out of every active query).
    assert store.order2.add_fill(
        store.order2.quantity, store.order2.price, store.order2.time
    )
    assert s.update_order(store.order2)

    # GLOBAL (None) path — byte-equal to the global flat-scan oracle.
    oracle_all = _active_oracle(s, None)
    assert [o.id for o in s.get_active_orders(None)] == [o.id for o in oracle_all]

    # Per-portfolio path — byte-equal to the oracle filtered to pid1.
    oracle_p1 = _active_oracle(s, store.pid1)
    assert [o.id for o in s.get_active_orders(store.pid1)] == [o.id for o in oracle_p1]

    # get_orders_by_status(active) via the index == oracle filtered to PENDING.
    pending_oracle = [o for o in oracle_all if o.status == OrderStatus.PENDING]
    assert (
        [o.id for o in s.get_orders_by_status(OrderStatus.PENDING)]
        == [o.id for o in pending_oracle]
    )

    # get_pending_orders(None) nested shape == scan-built nesting.
    nested = s.get_pending_orders(None)
    expected: dict = {}
    for o in oracle_all:
        expected.setdefault(o.portfolio_id, {})[o.id] = o
    assert {pid: list(d) for pid, d in nested.items()} == {
        pid: list(d) for pid, d in expected.items()
    }


def test_partially_filled_status_query_preserves_add_order_equivalence(store):
    """WR-01/D-08: get_orders_by_status(PARTIALLY_FILLED) yields add-order, not transition-order.

    The _by_status bucket is kept in status-transition order (an order is popped
    from PENDING and appended to PARTIALLY_FILLED at transition time). When orders
    cross into PARTIALLY_FILLED out of add-order, the bucket sequence diverges from
    add-order — yet the query must stay byte-identical to the prior flat scan
    (D-06/D-08/D-09). Here order2 (added second) transitions FIRST, so a raw
    transition-order index would return [order2, order1]; the add-order oracle
    returns [order1, order2]. PENDING never exposes this (entry == add), which is
    why the FILLED/PENDING-only equivalence test missed it (WR-03).
    """
    s = store.storage
    s.add_order(store.order1)   # pid1, added first
    s.add_order(store.order2)   # pid1, added second

    # order2 reaches PARTIALLY_FILLED BEFORE order1 — reverse of add-order. The
    # full-quantity add_fill contract (D-06) cannot produce PARTIALLY_FILLED, so
    # drive it via the valid PENDING->PARTIALLY_FILLED transition directly.
    assert store.order2.add_state_change(
        OrderStatus.PARTIALLY_FILLED, "partial", OrderTriggerSource.EXCHANGE
    )
    assert s.update_order(store.order2)
    assert store.order1.add_state_change(
        OrderStatus.PARTIALLY_FILLED, "partial", OrderTriggerSource.EXCHANGE
    )
    assert s.update_order(store.order1)

    # Independent oracle: scan _by_id (add-order), filter to PARTIALLY_FILLED.
    oracle_pf = [
        o for o in s._by_id.values() if o.status == OrderStatus.PARTIALLY_FILLED
    ]
    assert [o.id for o in oracle_pf] == [store.order1.id, store.order2.id]

    # Index-backed query must match the add-order oracle, NOT transition order.
    assert (
        [o.id for o in s.get_orders_by_status(OrderStatus.PARTIALLY_FILLED)]
        == [o.id for o in oracle_pf]
    )
    # Per-portfolio path stays add-order too.
    assert (
        [o.id for o in s.get_orders_by_status(OrderStatus.PARTIALLY_FILLED, store.pid1)]
        == [store.order1.id, store.order2.id]
    )


def test_filled_via_update_drops_from_active_index_terminal_fallback(store):
    """PENDING->FILLED via update_order drops from active AND by_status; terminal scan still finds it (D-10)."""
    s = store.storage
    s.add_order(store.order1)   # pid1 PENDING

    assert store.order1.add_fill(
        store.order1.quantity, store.order1.price, store.order1.time
    )
    assert s.update_order(store.order1)

    # Dropped from both active queries.
    assert s.get_active_orders(store.pid1) == []
    assert s.get_orders_by_status(OrderStatus.PENDING, store.pid1) == []
    # Internal index + registry have no stale active entry.
    assert store.pid1 not in s._active_by_portfolio
    assert store.oid1 not in s._by_status.get(OrderStatus.PENDING, {})
    assert s._last_indexed_status[store.oid1] == OrderStatus.FILLED
    # Terminal-status query still returns it via the flat-dict fallback (D-10).
    assert s.get_orders_by_status(OrderStatus.FILLED, store.pid1) == [store.order1]


def test_remove_orders_by_ticker_keeps_indexes_consistent(store):
    """remove_orders_by_ticker leaves both indexes + registry with no stale entries."""
    s = store.storage
    s.add_order(store.order1)   # pid1 BTCUSDT PENDING
    s.add_order(store.order2)   # pid1 ETHUSDT PENDING

    assert s.remove_orders_by_ticker("BTCUSDT", store.pid1) == 1

    # order1 (BTCUSDT) gone from active queries + internal indexes + registry.
    assert [o.id for o in s.get_active_orders(store.pid1)] == [store.oid2]
    assert store.oid1 not in s._active_by_portfolio.get(store.pid1, {})
    assert store.oid1 not in s._by_status.get(OrderStatus.PENDING, {})
    assert store.oid1 not in s._last_indexed_status
    # order2 (ETHUSDT) untouched.
    assert s._last_indexed_status[store.oid2] == OrderStatus.PENDING


def test_clear_portfolio_orders_keeps_indexes_consistent(store):
    """clear_portfolio_orders clears the active bucket + registry for that portfolio only."""
    s = store.storage
    s.add_order(store.order1)   # pid1
    s.add_order(store.order2)   # pid1
    s.add_order(store.order3)   # pid2

    assert s.clear_portfolio_orders(store.pid1) == 2

    # pid1 emptied from every index + registry.
    assert s.get_active_orders(store.pid1) == []
    assert store.pid1 not in s._active_by_portfolio
    assert store.oid1 not in s._last_indexed_status
    assert store.oid2 not in s._last_indexed_status
    # pid2 untouched.
    assert [o.id for o in s.get_active_orders(store.pid2)] == [store.oid3]
    assert s._last_indexed_status[store.oid3] == OrderStatus.PENDING


def test_re_add_order_is_idempotent(store):
    """Re-add of an existing PENDING id does not duplicate it in the active index (Pitfall 4)."""
    s = store.storage
    s.add_order(store.order1)
    s.add_order(store.order1)   # re-add same id

    active = s.get_active_orders(store.pid1)
    assert [o.id for o in active] == [store.oid1]
    assert list(s._active_by_portfolio[store.pid1]) == [store.oid1]


# --- OrderStorageFactory ----------------------------------------------------


def test_create_backtest_storage():
    """Test creating a backtest storage."""
    storage = OrderStorageFactory.create("backtest")
    assert isinstance(storage, InMemoryOrderStorage)


def test_create_test_storage():
    """Test creating a test storage."""
    storage = OrderStorageFactory.create("test")
    assert isinstance(storage, InMemoryOrderStorage)


def test_create_in_memory_directly():
    """Test creating in-memory storage directly."""
    storage = OrderStorageFactory.create_in_memory()
    assert isinstance(storage, InMemoryOrderStorage)


def test_create_live_storage_returns_sql_backend():
    """The 'live' arm routes to SqlOrderStorage on the shared SQL spine (D-06).

    With no backend supplied the factory builds a default ``SqlBackend`` (Phase 4 injects
    the shared operational backend). The store is disposed to avoid a ResourceWarning under
    ``filterwarnings=["error"]`` (WR-03 / Pitfall 4).
    """
    from itrader.order_handler.storage.sql_storage import SqlOrderStorage

    storage = OrderStorageFactory.create("live")
    try:
        assert isinstance(storage, SqlOrderStorage)
    finally:
        storage.dispose()


def test_unsupported_environment():
    """Test creating storage with unsupported environment."""
    with pytest.raises(ConfigurationError) as exc_info:
        OrderStorageFactory.create("unknown")
    assert "Unknown environment: unknown" in str(exc_info.value)


# --- OrderHandler + storage integration -------------------------------------


@pytest.fixture
def handler_env():
    """OrderHandler wired to a PortfolioHandler with one funded portfolio."""
    queue = Queue()
    ptf_handler = PortfolioHandler(queue)
    ptf_handler.add_portfolio(1, "test_ptf", "simulated", 1000)
    storage = InMemoryOrderStorage()
    order_handler = OrderHandler(queue, ptf_handler, storage)
    yield SimpleNamespace(
        queue=queue, ptf_handler=ptf_handler, storage=storage, order_handler=order_handler
    )
    while not queue.empty():
        queue.get_nowait()


def test_order_handler_initialization_with_storage(handler_env):
    """The injected storage is forwarded to (and owned by) the manager (D-18)."""
    assert isinstance(handler_env.order_handler, OrderHandler)
    # The handler retains NO storage reference — the manager owns it.
    assert not hasattr(handler_env.order_handler, "order_storage")
    assert handler_env.order_handler.order_manager.order_storage is handler_env.storage


def test_order_handler_initialization_without_storage(handler_env):
    """A default in-memory storage is created and owned by the manager (D-18)."""
    order_handler = OrderHandler(handler_env.queue, handler_env.ptf_handler)
    assert not hasattr(order_handler, "order_storage")
    assert isinstance(order_handler.order_manager.order_storage, InMemoryOrderStorage)


def test_handler_reads_delegate_through_manager(handler_env):
    """Handler get_*/search_* reads resolve through the manager-owned storage (D-18)."""
    pid = uuid.uuid4()
    oid = uuid.uuid4()
    order = Order(
        time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action=Side.BUY, price=40000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=pid, id=oid,
    )
    handler_env.storage.add_order(order)

    handler = handler_env.order_handler
    assert handler.get_order_by_id(oid, pid) == order
    assert handler.get_orders_by_status(OrderStatus.PENDING, pid) == [order]
    assert handler.get_active_orders(pid) == [order]
    assert handler.get_orders_by_ticker("BTCUSDT", pid) == [order]
    assert handler.search_orders({"ticker": "BTCUSDT"}, pid) == [order]
    assert handler.count_orders_by_status(pid) == {"PENDING": 1}
    assert handler.get_order_history(oid) == []
