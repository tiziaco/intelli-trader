import unittest
from datetime import datetime, UTC
from queue import Queue

from itrader.order_handler.base import OrderStorage
from itrader.order_handler.storage import InMemoryOrderStorage, OrderStorageFactory
from itrader.order_handler.order import Order, OrderType, OrderStatus
from itrader.order_handler.order_handler import OrderHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import SignalEvent


class TestOrderStorage(unittest.TestCase):
    """
    Test the OrderStorage interface and InMemoryOrderStorage implementation.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.storage = InMemoryOrderStorage()
        
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
            portfolio_id=1,
            id=1001
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
            portfolio_id=1,
            id=1002
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
            portfolio_id=2,  # Different portfolio
            id=1003
        )

    def test_add_order(self):
        """Test adding orders to storage."""
        # Add first order
        self.storage.add_order(self.order1)
        
        # Check it was added
        pending_orders = self.storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 1)
        self.assertIn('1', pending_orders)  # portfolio_id as string
        self.assertIn('1001', pending_orders['1'])  # order_id as string
        self.assertEqual(pending_orders['1']['1001'], self.order1)

    def test_add_multiple_orders(self):
        """Test adding multiple orders across different portfolios."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)
        self.storage.add_order(self.order3)
        
        pending_orders = self.storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 2)  # Two portfolios
        self.assertEqual(len(pending_orders['1']), 2)  # Two orders in portfolio 1
        self.assertEqual(len(pending_orders['2']), 1)  # One order in portfolio 2

    def test_get_order_by_id(self):
        """Test retrieving orders by ID."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order3)
        
        # Test with portfolio_id specified
        found_order = self.storage.get_order_by_id(1001, 1)
        self.assertEqual(found_order, self.order1)
        
        # Test without portfolio_id (search all)
        found_order = self.storage.get_order_by_id(1003)
        self.assertEqual(found_order, self.order3)
        
        # Test non-existent order
        found_order = self.storage.get_order_by_id(9999)
        self.assertIsNone(found_order)

    def test_remove_order(self):
        """Test removing orders."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)
        
        # Remove with portfolio_id specified
        removed = self.storage.remove_order(1001, 1)
        self.assertTrue(removed)
        
        # Check it's gone
        found_order = self.storage.get_order_by_id(1001, 1)
        self.assertIsNone(found_order)
        
        # Remove without portfolio_id
        removed = self.storage.remove_order(1002)
        self.assertTrue(removed)
        
        # Try to remove non-existent order
        removed = self.storage.remove_order(9999)
        self.assertFalse(removed)

    def test_remove_orders_by_ticker(self):
        """Test removing all orders for a ticker."""
        self.storage.add_order(self.order1)  # BTCUSDT
        self.storage.add_order(self.order2)  # ETHUSDT
        self.storage.add_order(self.order3)  # BTCUSDT in different portfolio
        
        # Remove BTCUSDT orders from portfolio 1
        count = self.storage.remove_orders_by_ticker('BTCUSDT', 1)
        self.assertEqual(count, 1)
        
        # Check BTCUSDT order in portfolio 2 still exists
        found_order = self.storage.get_order_by_id(1003, 2)
        self.assertEqual(found_order, self.order3)
        
        # Check ETHUSDT order still exists
        found_order = self.storage.get_order_by_id(1002, 1)
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
        btc_orders_p1 = self.storage.get_orders_by_ticker('BTCUSDT', 1)
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
        
        # Check the update
        found_order = self.storage.get_order_by_id(1001, 1)
        self.assertEqual(found_order.price, 41000.0)

    def test_clear_portfolio_orders(self):
        """Test clearing all orders for a portfolio."""
        self.storage.add_order(self.order1)
        self.storage.add_order(self.order2)
        self.storage.add_order(self.order3)
        
        # Clear portfolio 1
        count = self.storage.clear_portfolio_orders(1)
        self.assertEqual(count, 2)
        
        # Check portfolio 1 orders are gone
        pending_orders = self.storage.get_pending_orders(1)
        self.assertEqual(len(pending_orders['1']), 0)
        
        # Check portfolio 2 orders still exist
        pending_orders = self.storage.get_pending_orders(2)
        self.assertEqual(len(pending_orders['2']), 1)


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
        # Add an order through the handler
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
            portfolio_id=1,
            id=1001
        )
        
        self.order_handler.add_pending_order(order)
        
        # Check it's accessible through the storage
        pending_orders = self.order_handler.order_storage.get_pending_orders()
        self.assertEqual(len(pending_orders), 1)
        self.assertIn('1', pending_orders)
        self.assertIn('1001', pending_orders['1'])


if __name__ == '__main__':
    unittest.main()
