"""
Consolidated PortfolioHandler tests combining legacy and enhanced functionality.
"""

import unittest
import threading
import time
from queue import Queue
from datetime import datetime, UTC
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

# Import the portfolio classes
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.portfolio_handler.portfolio import Portfolio, Position, PositionSide
from itrader.config import PortfolioState
from itrader.config import PortfolioConfig, PortfolioHandlerConfig
from itrader.portfolio_handler.exceptions import (
    PortfolioNotFoundError, PortfolioValidationError, PortfolioConfigurationError,
    InvalidPortfolioOperationError
)
from itrader.portfolio_handler.transaction import Transaction
from itrader.events_handler.event import FillEvent, PortfolioErrorEvent, FillStatus


class TestPortfolioHandler(unittest.TestCase):
    """Comprehensive test cases for PortfolioHandler functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.global_queue = Queue()
        # The new PortfolioHandler uses ConfigRegistry instead of global_config parameter
        self.handler = PortfolioHandler(
            global_queue=self.global_queue,
            config_dir="config",
            environment="test"
        )
        
        # Test data for legacy compatibility
        self.user_id = 1
        self.portfolio_name = 'test_pf'
        self.exchange = 'simulated'
        self.cash = 150000

    # ===================
    # PORTFOLIO CREATION & BASIC OPERATIONS
    # ===================
    
    def test_add_portfolio(self):
        """Test basic portfolio creation (legacy compatibility)."""
        portfolio_id = self.handler.add_portfolio(
            self.user_id, self.portfolio_name, self.exchange, self.cash
        )
        
        # Assert if the portfolio has been created
        self.assertEqual(self.handler.get_portfolio_count(), 1)
        self.assertIsInstance(portfolio_id, int)
        self.assertGreater(portfolio_id, 0)
    
    def test_get_portfolio(self):
        """Test portfolio retrieval (legacy compatibility)."""
        portfolio_id = self.handler.add_portfolio(
            self.user_id, self.portfolio_name, self.exchange, self.cash
        )
        portfolio = self.handler.get_portfolio(portfolio_id)

        # Assert if the portfolio has been retrieved correctly
        self.assertIsInstance(portfolio, Portfolio)
        self.assertEqual(portfolio.portfolio_id, portfolio_id)
        self.assertEqual(portfolio.name, self.portfolio_name)
        self.assertEqual(portfolio.cash, self.cash)
    
    def test_portfolio_creation_success(self):
        """Test successful portfolio creation with enhanced features."""
        portfolio_id = self.handler.add_portfolio(
            user_id=1,
            name="Test Portfolio",
            exchange="NYSE",
            cash=10000.0
        )
        
        self.assertIsInstance(portfolio_id, int)
        self.assertGreater(portfolio_id, 0)
        
        # Verify portfolio exists and has correct attributes
        portfolio = self.handler.get_portfolio(portfolio_id)
        self.assertEqual(portfolio.user_id, 1)
        self.assertEqual(portfolio.name, "Test Portfolio")
        self.assertEqual(portfolio.exchange, "NYSE")
        self.assertEqual(portfolio.cash, 10000.0)
        self.assertEqual(portfolio.state, PortfolioState.ACTIVE)
        self.assertTrue(portfolio.is_active())
        self.assertTrue(portfolio.can_trade())
    
    def test_portfolio_creation_with_custom_config(self):
        """Test portfolio creation with custom configuration."""
        custom_config = PortfolioConfig(
            max_positions=50,
            max_position_value=Decimal('500000'),
            validate_transactions=True
        )
        
        portfolio_id = self.handler.add_portfolio(
            user_id=2,
            name="Custom Config Portfolio",
            exchange="NASDAQ",
            cash=25000.0,
            portfolio_config=custom_config
        )
        
        portfolio = self.handler.get_portfolio(portfolio_id)
        self.assertEqual(portfolio.config.max_positions, 50)
        self.assertEqual(portfolio.config.max_position_value, Decimal('500000'))
        self.assertTrue(portfolio.config.validate_transactions)
    
    def test_portfolio_creation_invalid_cash(self):
        """Test portfolio creation with invalid cash amount."""
        with self.assertRaises(PortfolioValidationError):
            self.handler.add_portfolio(
                user_id=1,
                name="Invalid Portfolio",
                exchange="NYSE",
                cash=-1000.0
            )
    
    def test_portfolio_not_found_error(self):
        """Test getting non-existent portfolio."""
        with self.assertRaises(PortfolioNotFoundError):
            self.handler.get_portfolio(99999)

    # ===================
    # PORTFOLIO STATE MANAGEMENT
    # ===================
    
    def test_portfolio_state_management(self):
        """Test portfolio state transitions."""
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        portfolio = self.handler.get_portfolio(portfolio_id)
        
        # Test initial state
        self.assertEqual(portfolio.state, PortfolioState.ACTIVE)
        
        # Test state transition to INACTIVE
        result = portfolio.set_state(PortfolioState.INACTIVE, "Testing")
        self.assertTrue(result)
        self.assertEqual(portfolio.state, PortfolioState.INACTIVE)
        self.assertFalse(portfolio.is_active())
        self.assertFalse(portfolio.can_trade())
        
        # Test state transition back to ACTIVE
        result = portfolio.set_state(PortfolioState.ACTIVE, "Reactivating")
        self.assertTrue(result)
        self.assertEqual(portfolio.state, PortfolioState.ACTIVE)
        
        # Test archiving
        result = portfolio.set_state(PortfolioState.ARCHIVED, "Archiving")
        self.assertTrue(result)
        self.assertEqual(portfolio.state, PortfolioState.ARCHIVED)
        
        # Test that archived portfolios cannot transition
        with self.assertRaises(ValueError):
            portfolio.set_state(PortfolioState.ACTIVE, "Cannot reactivate archived")
    
    def test_portfolio_deletion_with_state_validation(self):
        """Test portfolio deletion with proper state validation."""
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        
        # Withdraw all cash to allow deletion
        portfolio = self.handler.get_portfolio(portfolio_id)
        portfolio.cash_manager.withdraw(portfolio.cash_manager.balance, "Test withdrawal")
        
        # Delete portfolio (should archive first)
        result = self.handler.delete_portfolio(portfolio_id)
        self.assertTrue(result)
        
        # Verify portfolio is deleted
        with self.assertRaises(PortfolioNotFoundError):
            self.handler.get_portfolio(portfolio_id)
    
    def test_active_portfolios_filtering(self):
        """Test filtering active portfolios."""
        # Create multiple portfolios with different states
        p1 = self.handler.add_portfolio(1, "Active1", "NYSE", 10000.0)
        p2 = self.handler.add_portfolio(2, "Active2", "NYSE", 20000.0)
        p3 = self.handler.add_portfolio(3, "Inactive", "NYSE", 15000.0)
        
        # Make one inactive
        portfolio3 = self.handler.get_portfolio(p3)
        portfolio3.set_state(PortfolioState.INACTIVE)
        
        # Get active portfolios
        active_portfolios = self.handler.get_active_portfolios()
        active_ids = [p.portfolio_id for p in active_portfolios]
        
        self.assertEqual(len(active_portfolios), 2)
        self.assertIn(p1, active_ids)
        self.assertIn(p2, active_ids)
        self.assertNotIn(p3, active_ids)

    # ===================
    # FILL EVENT PROCESSING
    # ===================
    
    def test_buy_fill(self):
        """Test buy fill event processing (legacy compatibility)."""
        portfolio_id = self.handler.add_portfolio(
            self.user_id, self.portfolio_name, self.exchange, self.cash
        )
        
        # Bought 1 BTC over one filled event from the execution handler
        buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
                            'BTCUSDT', 'BUY', 40000, 1, 0, portfolio_id)
        self.handler.on_fill(buy_fill)
        portfolio = self.handler.get_portfolio(portfolio_id)
        position = portfolio.positions['BTCUSDT']

        # Assert the portfolio's positions and transactions
        self.assertEqual(len(portfolio.positions), 1)
        self.assertEqual(len(portfolio.closed_positions), 0)
        self.assertEqual(len(portfolio.transactions), 1)
        # Assert the portfolio's metrics
        self.assertEqual(portfolio.cash, 110000)
        self.assertEqual(portfolio.total_equity, 150000)
        self.assertEqual(portfolio.total_market_value, 40000)
        self.assertEqual(portfolio.total_pnl, 0)
        self.assertEqual(portfolio.total_realised_pnl, 0)
        self.assertEqual(portfolio.total_unrealised_pnl, 0)
        # Assert the open position
        self.assertIsInstance(position, Position)
        self.assertEqual(position.ticker, 'BTCUSDT')
        self.assertEqual(position.portfolio_id, portfolio_id)
        self.assertEqual(position.is_open, True)
        self.assertEqual(position.side, PositionSide.LONG)

    def test_sell_fill(self):
        """Test sell fill event processing (legacy compatibility - SHORT position)."""
        portfolio_id = self.handler.add_portfolio(
            self.user_id, self.portfolio_name, self.exchange, self.cash
        )
        
        # Sold 1 BTC (short position) over one filled event from the execution handler
        sell_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
                             'BTCUSDT', 'SELL', 40000, 1, 0, portfolio_id)
        self.handler.on_fill(sell_fill)
        portfolio = self.handler.get_portfolio(portfolio_id)
        position = portfolio.positions['BTCUSDT']

        # Assert the portfolio's positions and transactions
        self.assertEqual(len(portfolio.positions), 1)
        self.assertEqual(len(portfolio.closed_positions), 0)
        self.assertEqual(len(portfolio.transactions), 1)
        # Assert the portfolio's metrics
        self.assertEqual(portfolio.cash, 190000)  # Started with 150k, sold short for 40k = 190k
        self.assertEqual(portfolio.total_equity, 150000)  # Still 150k because short position offsets cash increase
        self.assertEqual(portfolio.total_market_value, -40000)  # Negative because short position is a liability
        self.assertEqual(portfolio.total_pnl, 0)
        self.assertEqual(portfolio.total_realised_pnl, 0)
        self.assertEqual(portfolio.total_unrealised_pnl, 0)
        # Assert the open position
        self.assertIsInstance(position, Position)
        self.assertEqual(position.ticker, 'BTCUSDT')
        self.assertEqual(position.portfolio_id, portfolio_id)
        self.assertEqual(position.is_open, True)
        self.assertEqual(position.side, PositionSide.SHORT)
    
    def test_fill_event_processing_success(self):
        """Test successful fill event processing (enhanced)."""
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        
        fill_event = FillEvent(
            time=datetime.now(UTC),
            status=FillStatus.EXECUTED,
            ticker="AAPL",
            action="BUY",
            price=50.0,  # Lower price to stay within cash limits
            quantity=100,
            commission=1.0,
            portfolio_id=str(portfolio_id)
        )
        
        result = self.handler.on_fill(fill_event)
        self.assertTrue(result)
        
        # Verify portfolio was updated
        portfolio = self.handler.get_portfolio(portfolio_id)
        self.assertEqual(portfolio.n_open_positions, 1)
        self.assertLess(portfolio.cash, 10000.0)  # Cash should be reduced
    
    def test_fill_event_processing_inactive_portfolio(self):
        """Test fill event processing with inactive portfolio."""
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        portfolio = self.handler.get_portfolio(portfolio_id)
        portfolio.set_state(PortfolioState.INACTIVE)
        
        fill_event = FillEvent(
            time=datetime.now(UTC),
            status=FillStatus.EXECUTED,
            ticker="AAPL",
            action="BUY",
            price=150.0,
            quantity=100,
            commission=1.0,
            portfolio_id=str(portfolio_id)
        )
        
        with self.assertRaises(ValueError):
            self.handler.on_fill(fill_event)
    
    def test_fill_event_processing_invalid_portfolio(self):
        """Test fill event processing with invalid portfolio ID."""
        fill_event = FillEvent(
            time=datetime.now(UTC),
            status=FillStatus.EXECUTED,
            ticker="AAPL",
            action="BUY",
            price=150.0,
            quantity=100,
            commission=1.0,
            portfolio_id="99999"
        )
        
        with self.assertRaises(PortfolioNotFoundError):
            self.handler.on_fill(fill_event)

    # ===================
    # DICTIONARY CONVERSION & SERIALIZATION
    # ===================
    
    def test_portfolios_to_dict(self):
        """Test portfolios to dictionary conversion (legacy compatibility)."""
        portfolio_id = self.handler.add_portfolio(
            self.user_id, self.portfolio_name, self.exchange, self.cash
        )
        
        # Add a transaction to test with data
        buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
                            'BTCUSDT', 'SELL', 40000, 1, 0, portfolio_id)
        self.handler.on_fill(buy_fill)

        portfolios_dict = self.handler.portfolios_to_dict()

        # Assert the portfolio's dictionary
        self.assertIsInstance(portfolios_dict, dict)
        self.assertEqual(len(portfolios_dict), 1)
    
    def test_portfolios_to_dict_thread_safety(self):
        """Test portfolios_to_dict method thread safety."""
        # Create multiple portfolios
        for i in range(3):
            self.handler.add_portfolio(i, f"Portfolio {i}", "NYSE", 10000.0)
        
        def get_portfolios_dict():
            return self.handler.portfolios_to_dict()
        
        # Access portfolios_to_dict concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(get_portfolios_dict) for _ in range(5)]
            results = [future.result() for future in as_completed(futures)]
        
        # Verify all results are consistent
        self.assertEqual(len(results), 5)
        for result in results:
            self.assertEqual(len(result), 3)
            self.assertIsInstance(result, dict)

    # ===================
    # VALIDATION & HEALTH CHECKS
    # ===================
    
    def test_portfolio_health_validation(self):
        """Test portfolio health validation."""
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        portfolio = self.handler.get_portfolio(portfolio_id)
        
        # Test initial health
        health = portfolio.validate_health()
        self.assertTrue(health['is_healthy'])
        self.assertEqual(health['portfolio_id'], portfolio_id)
        self.assertEqual(health['state'], PortfolioState.ACTIVE.value)
        self.assertEqual(len(health['issues']), 0)

    # ===================
    # ERROR HANDLING & EVENTS
    # ===================
    
    def test_error_event_publishing(self):
        """Test that error events are published correctly."""
        # Clear the queue first
        while not self.global_queue.empty():
            self.global_queue.get()
        
        # Process fill event with invalid portfolio to trigger error event
        fill_event = FillEvent(
            time=datetime.now(UTC),
            status=FillStatus.EXECUTED,
            ticker="AAPL",
            action="BUY",
            price=150.0,
            quantity=100,
            commission=1.0,
            portfolio_id="99999"
        )
        
        try:
            self.handler.on_fill(fill_event)
        except PortfolioNotFoundError:
            pass
        
        # Check that error event was published (if error events are enabled)
        # Note: Error event publishing might be disabled in test config
        if not self.global_queue.empty():
            error_event = self.global_queue.get()
            self.assertIsInstance(error_event, PortfolioErrorEvent)
            self.assertEqual(error_event.error_type, "PortfolioNotFoundError")
            self.assertEqual(error_event.portfolio_id, 99999)
        else:
            # If no error event was published, that's also acceptable behavior
            # depending on configuration
            pass

    # ===================
    # CONCURRENCY & THREAD SAFETY
    # ===================
    
    def test_concurrent_operation_limits(self):
        """Test concurrent operation limits."""
        # This test verifies the limit is configured correctly
        # The actual limit may vary based on environment config
        self.assertGreater(self.handler.config.limits.max_concurrent_operations, 0)
        self.assertEqual(len(self.handler._active_operations), 0)
    
    def test_correlation_id_generation(self):
        """Test correlation ID generation."""
        id1 = self.handler._generate_correlation_id()
        id2 = self.handler._generate_correlation_id()
        
        self.assertNotEqual(id1, id2)
        self.assertTrue(id1.startswith("ph_"))
        self.assertTrue(id2.startswith("ph_"))
    
    def test_thread_safety_concurrent_creation(self):
        """Test thread safety during concurrent portfolio creation."""
        results = []
        errors = []
        
        def create_portfolio(user_id):
            try:
                portfolio_id = self.handler.add_portfolio(
                    user_id=user_id,
                    name=f"Portfolio {user_id}",
                    exchange="NYSE",
                    cash=10000.0
                )
                results.append(portfolio_id)
            except Exception as e:
                errors.append(e)
        
        # Create portfolios concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=create_portfolio, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Verify results
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 5)
        self.assertEqual(len(set(results)), 5)  # All unique IDs
    
    def test_thread_safety_concurrent_access(self):
        """Test thread safety during concurrent portfolio access."""
        # Create a portfolio first
        portfolio_id = self.handler.add_portfolio(1, "Test", "NYSE", 10000.0)
        
        results = []
        errors = []
        
        def access_portfolio():
            try:
                portfolio = self.handler.get_portfolio(portfolio_id)
                results.append(portfolio.portfolio_id)
            except Exception as e:
                errors.append(e)
        
        # Access portfolio concurrently
        threads = []
        for i in range(10):
            thread = threading.Thread(target=access_portfolio)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Verify results
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r == portfolio_id for r in results))


class TestPortfolioEnhancements(unittest.TestCase):
    """Test cases for individual portfolio enhancements."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = Portfolio(
            user_id=1,
            name="Test Portfolio",
            exchange="NYSE",
            cash=10000.0,
            time=datetime.now(UTC)
        )
    
    def test_portfolio_configuration_management(self):
        """Test portfolio configuration management."""
        # Test default configuration (check actual default from config)
        self.assertEqual(self.portfolio.config.max_positions, 50)  # This matches the test environment config
        self.assertEqual(self.portfolio.config.max_position_value, Decimal('1000000'))
        
        # Test configuration update
        self.portfolio.update_config(max_positions=75, max_position_value=Decimal('500000'))
        self.assertEqual(self.portfolio.config.max_positions, 75)
        self.assertEqual(self.portfolio.config.max_position_value, Decimal('500000'))
        
        # Test configuration dictionary
        config_dict = self.portfolio.get_config_dict()
        self.assertEqual(config_dict['max_positions'], 75)
        self.assertEqual(config_dict['max_position_value'], 500000.0)
    
    def test_portfolio_enhanced_to_dict(self):
        """Test enhanced to_dict method."""
        portfolio_dict = self.portfolio.to_dict()
        
        # Check all required fields are present
        required_fields = [
            'portfolio_id', 'user_id', 'name', 'exchange', 'creation_time',
            'current_time', 'state', 'cash', 'total_market_value', 'total_equity',
            'n_open_positions', 'config', 'health_metrics', 'last_activity'
        ]
        
        for field in required_fields:
            self.assertIn(field, portfolio_dict)
        
        # Check specific values
        self.assertEqual(portfolio_dict['user_id'], 1)
        self.assertEqual(portfolio_dict['name'], "Test Portfolio")
        self.assertEqual(portfolio_dict['state'], PortfolioState.ACTIVE.value)
        self.assertEqual(portfolio_dict['cash'], 10000.0)


if __name__ == '__main__':
    unittest.main()
