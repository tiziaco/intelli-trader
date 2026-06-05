import uuid
from datetime import datetime, UTC
from queue import Queue
from types import SimpleNamespace

import pytest

from itrader.order_handler.storage import InMemoryOrderStorage, OrderStorageFactory
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler


# --- InMemoryOrderStorage ---------------------------------------------------


@pytest.fixture
def store():
    """In-memory storage seeded with three native-UUID orders.

    Storage now keys by native ``uuid.UUID`` (D-14): order/portfolio ids are stored
    as their native UUID, and ``get_order_by_id`` resolves cross-portfolio lookups
    via the flat ``_by_id`` index (PERF2). These fixtures use real ``uuid.UUID`` ids
    and assert native-UUID keys.
    """
    storage = InMemoryOrderStorage()

    pid1 = uuid.uuid4()
    pid2 = uuid.uuid4()
    oid1 = uuid.uuid4()
    oid2 = uuid.uuid4()
    oid3 = uuid.uuid4()

    order1 = Order(
        time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action="BUY", price=40000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=pid1, id=oid1,
    )
    order2 = Order(
        time=datetime.now(UTC), type=OrderType.LIMIT, status=OrderStatus.PENDING,
        ticker="ETHUSDT", action="SELL", price=3000.0, quantity=0.5,
        exchange="binance", strategy_id=1, portfolio_id=pid1, id=oid2,
    )
    order3 = Order(
        time=datetime.now(UTC), type=OrderType.STOP, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action="SELL", price=39000.0, quantity=0.1,
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


def test_get_order_by_id_uses_flat_index(store):
    """The flat ``_by_id`` index resolves a lookup with no portfolio scan."""
    store.storage.add_order(store.order1)

    assert store.oid1 in store.storage._by_id
    assert store.storage._by_id[store.oid1] == store.order1
    assert store.storage.get_order_by_id(store.oid1) == store.order1


def test_remove_order(store):
    """Test removing orders."""
    store.storage.add_order(store.order1)
    store.storage.add_order(store.order2)

    # Remove with portfolio_id specified
    assert store.storage.remove_order(store.oid1, store.pid1)

    # Check it's gone (and pruned from the flat index)
    assert store.storage.get_order_by_id(store.oid1, store.pid1) is None
    assert store.oid1 not in store.storage._by_id

    # Remove without portfolio_id
    assert store.storage.remove_order(store.oid2)
    assert store.oid2 not in store.storage._by_id

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

    # Check the update (flat index reflects the new instance)
    found_order = store.storage.get_order_by_id(store.oid1, store.pid1)
    assert found_order.price == 41000.0
    assert store.storage._by_id[store.oid1].price == 41000.0


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


def test_create_live_storage_without_db_url():
    """Test creating live storage without database URL raises error."""
    with pytest.raises(ValueError) as exc_info:
        OrderStorageFactory.create("live")
    assert "Database URL is required" in str(exc_info.value)


def test_unsupported_environment():
    """Test creating storage with unsupported environment."""
    with pytest.raises(ValueError) as exc_info:
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
    """Test OrderHandler initializes correctly with custom storage."""
    assert isinstance(handler_env.order_handler, OrderHandler)
    assert isinstance(handler_env.order_handler.order_storage, InMemoryOrderStorage)


def test_order_handler_initialization_without_storage(handler_env):
    """Test OrderHandler initializes with default storage when none provided."""
    order_handler = OrderHandler(handler_env.queue, handler_env.ptf_handler)
    assert isinstance(order_handler.order_storage, InMemoryOrderStorage)


def test_backward_compatibility_pending_orders(handler_env):
    """Test that pending_orders attribute still works for backward compatibility."""
    # Add an order through the handler (native UUID identities)
    pid = uuid.uuid4()
    oid = uuid.uuid4()
    order = Order(
        time=datetime.now(UTC), type=OrderType.MARKET, status=OrderStatus.PENDING,
        ticker="BTCUSDT", action="BUY", price=40000.0, quantity=0.1,
        exchange="binance", strategy_id=1, portfolio_id=pid, id=oid,
    )

    handler_env.order_handler.add_pending_order(order)

    # Check it's accessible through the storage (native UUID keys)
    pending_orders = handler_env.order_handler.order_storage.get_pending_orders()
    assert len(pending_orders) == 1
    assert pid in pending_orders
    assert oid in pending_orders[pid]
