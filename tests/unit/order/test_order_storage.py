import unittest
import uuid
from datetime import datetime, UTC
from queue import Queue

from itrader.order_handler.base import OrderStorage
from itrader.order_handler.storage import InMemoryOrderStorage, OrderStorageFactory
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import SignalEvent


class TestOrderStorage(unittest.TestCase):
    """
    Test the OrderStorage interface and InMemoryOrderStorage implementation.

    Storage now keys by native ``uuid.UUID`` (D-14): order/portfolio ids are
    stored as their native UUID, and ``get_order_by_id`` resolves cross-portfolio
    lookups via the flat ``_by_id`` index (PERF2). These fixtures use real
    ``uuid.UUID`` ids and assert native-UUID keys.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.storage = InMemoryOrderStorage()

        # Native UUID identities for the fixture orders / portfolios
        self.pid1 = uuid.uuid4()  # portfolio 1
        self.pid2 = uuid.uuid4()  # portfolio 2
        self.oid1 = uuid.uuid4()
        self.oid2 = uuid.uuid4()
        self.oid3 = uuid.uuid4()

        # Create test orders
        self.order1 = Order(
            time=datetime.now(UTC),
            type=OrderType.MARKET,
            status=OrderStatus.PENDING,
            ticker='BTCUSDT',
            action='BUY',
            price=40000.0,
            quantity=0.1,
            exchange='binance',
            strategy_id=1,
            portfolio_id=self.pid1,
            id=self.oid1
        )

        self.order2 = Order(
            time=datetime.now(UTC),
            type=OrderType.LIMIT,
            status=OrderStatus.PENDING,
            ticker='ETHUSDT',
            action='SELL',
            price=3000.0,
            quantity=0.5,
            exchange='binance',
            strategy_id=1,
            portfolio_id=self.pid1,
            id=self.oid2
        )

        self.order3 = Order(
            time=datetime.now(UTC),
            type=OrderType.STOP,
            status=OrderStatus.PENDING,
            ticker='BTCUSDT',
            action='SELL',
            price=39000.0,
            quantity=0.1,
            exchange='binance',
            strategy_id=1,
            portfolio_id=self.pid2,  # Different portfolio
            id=self.oid3
        )

    def test_add_order(self):
        """Test adding orders to storage."""
        # Add first order
        self.storage.add_order(self.order1)

        # Check it was added (native UUID keys)
        pending_orders = self.storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 1)
        self.assertIn(self.pid1, pending_orders)  # portfolio_id as native UUID
        self.assertIn(self.oid1, pending_orders[self.pid1])  # order_id as native UUID
        self.assertEqual(pending_orders[self.pid1][self.oid1], self.order1)

    def test_add_multiple_orders(self):
        """Test adding multiple orders across different portfolios."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)
        self.storage.add_order(self.order3)

        pending_orders = self.storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 2)  # Two portfolios
        self.assertEqual(len(pending_orders[self.pid1]), 2)  # Two orders in portfolio 1
        self.assertEqual(len(pending_orders[self.pid2]), 1)  # One order in portfolio 2

    def test_get_order_by_id(self):
        """Test retrieving orders by ID."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order3)

        # Test with portfolio_id specified
        found_order = self.storage.get_order_by_id(self.oid1, self.pid1)
        self.assertEqual(found_order, self.order1)

        # Test without portfolio_id (flat-index cross-portfolio lookup)
        found_order = self.storage.get_order_by_id(self.oid3)
        self.assertEqual(found_order, self.order3)

        # Test non-existent order
        found_order = self.storage.get_order_by_id(uuid.uuid4())
        self.assertIsNone(found_order)

    def test_get_order_by_id_uses_flat_index(self):
        """The flat ``_by_id`` index resolves a lookup with no portfolio scan."""
        self.storage.add_order(self.order1)

        # The order is reachable directly from the flat global index
        self.assertIn(self.oid1, self.storage._by_id)
        self.assertEqual(self.storage._by_id[self.oid1], self.order1)

        # And the public lookup (no portfolio_id) returns it via that index
        self.assertEqual(self.storage.get_order_by_id(self.oid1), self.order1)

    def test_remove_order(self):
        """Test removing orders."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)

        # Remove with portfolio_id specified
        removed = self.storage.remove_order(self.oid1, self.pid1)
        self.assertTrue(removed)

        # Check it's gone (and pruned from the flat index)
        found_order = self.storage.get_order_by_id(self.oid1, self.pid1)
        self.assertIsNone(found_order)
        self.assertNotIn(self.oid1, self.storage._by_id)

        # Remove without portfolio_id
        removed = self.storage.remove_order(self.oid2)
        self.assertTrue(removed)
        self.assertNotIn(self.oid2, self.storage._by_id)

        # Try to remove non-existent order
        removed = self.storage.remove_order(uuid.uuid4())
        self.assertFalse(removed)

    def test_remove_orders_by_ticker(self):
        """Test removing all orders for a ticker."""
        self.storage.add_order(self.order1)  # BTCUSDT
        self.storage.add_order(self.order2)  # ETHUSDT
        self.storage.add_order(self.order3)  # BTCUSDT in different portfolio

        # Remove BTCUSDT orders from portfolio 1
        count = self.storage.remove_orders_by_ticker('BTCUSDT', self.pid1)
        self.assertEqual(count, 1)

        # Check BTCUSDT order in portfolio 2 still exists
        found_order = self.storage.get_order_by_id(self.oid3, self.pid2)
        self.assertEqual(found_order, self.order3)

        # Check ETHUSDT order still exists
        found_order = self.storage.get_order_by_id(self.oid2, self.pid1)
        self.assertEqual(found_order, self.order2)

    def test_get_orders_by_ticker(self):
        """Test getting orders by ticker."""
        self.storage.add_order(self.order1)  # BTCUSDT
        self.storage.add_order(self.order2)  # ETHUSDT
        self.storage.add_order(self.order3)  # BTCUSDT

        # Get all BTCUSDT orders
        btc_orders = self.storage.get_orders_by_ticker('BTCUSDT')
        self.assertEqual(len(btc_orders), 2)

        # Get BTCUSDT orders from specific portfolio
        btc_orders_p1 = self.storage.get_orders_by_ticker('BTCUSDT', self.pid1)
        self.assertEqual(len(btc_orders_p1), 1)
        self.assertEqual(btc_orders_p1[0], self.order1)

    def test_update_order(self):
        """Test updating an existing order."""
        self.storage.add_order(self.order1)

        # Update the price
        updated_order = Order(
            time=self.order1.time,
            type=self.order1.type,
            status=self.order1.status,
            ticker=self.order1.ticker,
            action=self.order1.action,
            price=41000.0,  # New price
            quantity=self.order1.quantity,
            exchange=self.order1.exchange,
            strategy_id=self.order1.strategy_id,
            portfolio_id=self.order1.portfolio_id,
            id=self.order1.id
        )

        # Update the order
        updated = self.storage.update_order(updated_order)
        self.assertTrue(updated)

        # Check the update (flat index reflects the new instance)
        found_order = self.storage.get_order_by_id(self.oid1, self.pid1)
        self.assertEqual(found_order.price, 41000.0)
        self.assertEqual(self.storage._by_id[self.oid1].price, 41000.0)

    def test_clear_portfolio_orders(self):
        """Test clearing all orders for a portfolio."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)
        self.storage.add_order(self.order3)

        # Clear portfolio 1
        count = self.storage.clear_portfolio_orders(self.pid1)
        self.assertEqual(count, 2)

        # Check portfolio 1 orders are gone
        pending_orders = self.storage.get_pending_orders(self.pid1)
        self.assertEqual(len(pending_orders[self.pid1]), 0)

        # Check portfolio 2 orders still exist
        pending_orders = self.storage.get_pending_orders(self.pid2)
        self.assertEqual(len(pending_orders[self.pid2]), 1)


class TestOrderStorageFactory(unittest.TestCase):
    """
    Test the OrderStorageFactory.
    """

    def test_create_backtest_storage(self):
        """Test creating a backtest storage."""
        storage = OrderStorageFactory.create('backtest')
        self.assertIsInstance(storage, InMemoryOrderStorage)

    def test_create_test_storage(self):
        """Test creating a test storage."""
        storage = OrderStorageFactory.create('test')
        self.assertIsInstance(storage, InMemoryOrderStorage)

    def test_create_in_memory_directly(self):
        """Test creating in-memory storage directly."""
        storage = OrderStorageFactory.create_in_memory()
        self.assertIsInstance(storage, InMemoryOrderStorage)

    def test_create_live_storage_without_db_url(self):
        """Test creating live storage without database URL raises error."""
        with self.assertRaises(ValueError) as context:
            OrderStorageFactory.create('live')
        
        self.assertIn("Database URL is required", str(context.exception))

    def test_unsupported_environment(self):
        """Test creating storage with unsupported environment."""
        with self.assertRaises(ValueError) as context:
            OrderStorageFactory.create('unknown')
        
        self.assertIn("Unknown environment: unknown", str(context.exception))


class TestOrderHandlerWithStorage(unittest.TestCase):
    """
    Test OrderHandler integration with the storage pattern.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test data for all test methods."""
        cls.user_id = 1
        cls.portfolio_name = 'test_ptf'
        cls.exchange = 'simulated'
        cls.strategy_id = 1
        cls.portfolio_id = 1
        cls.cash = 1000
        cls.queue = Queue()
        cls.ptf_handler = PortfolioHandler(cls.queue)
        cls.ptf_handler.add_portfolio(cls.user_id, cls.portfolio_name, cls.exchange, cls.cash)

    def setUp(self):
        """Set up for each test."""
        # Create OrderHandler with custom storage
        self.storage = InMemoryOrderStorage()
        self.order_handler = OrderHandler(self.queue, self.ptf_handler, self.storage)

    def test_order_handler_initialization_with_storage(self):
        """Test OrderHandler initializes correctly with custom storage."""
        self.assertIsInstance(self.order_handler, OrderHandler)
        self.assertIsInstance(self.order_handler.order_storage, InMemoryOrderStorage)

    def test_order_handler_initialization_without_storage(self):
        """Test OrderHandler initializes with default storage when none provided."""
        order_handler = OrderHandler(self.queue, self.ptf_handler)
        self.assertIsInstance(order_handler.order_storage, InMemoryOrderStorage)

    def test_backward_compatibility_pending_orders(self):
        """Test that pending_orders attribute still works for backward compatibility."""
        # Add an order through the handler (native UUID identities)
        pid = uuid.uuid4()
        oid = uuid.uuid4()
        order = Order(
            time=datetime.now(UTC),
            type=OrderType.MARKET,
            status=OrderStatus.PENDING,
            ticker='BTCUSDT',
            action='BUY',
            price=40000.0,
            quantity=0.1,
            exchange='binance',
            strategy_id=1,
            portfolio_id=pid,
            id=oid
        )

        self.order_handler.add_pending_order(order)

        # Check it's accessible through the storage (native UUID keys)
        pending_orders = self.order_handler.order_storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 1)
        self.assertIn(pid, pending_orders)
        self.assertIn(oid, pending_orders[pid])


if __name__ == '__main__':
    unittest.main()
