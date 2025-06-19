"""
Test suite for PositionManager class.
Tests position lifecycle, calculations, risk management, and thread safety.
"""

import unittest
import threading
import time
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import Mock

from itrader.portfolio_handler.position_manager import (
    PositionManager,
    PositionEvent,
    PositionMetrics
)
from itrader.portfolio_handler.position import Position, PositionSide
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.exceptions import (
    InvalidTransactionError,
    PositionCalculationError
)
from itrader import idgen


class MockPortfolio:
    """Mock portfolio for testing."""
    def __init__(self):
        self.portfolio_id = idgen.generate_portfolio_id()


class TestPositionManager(unittest.TestCase):
    """Comprehensive test suite for PositionManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = MockPortfolio()
        self.position_manager = PositionManager(self.portfolio)
        
        # Sample transactions
        self.buy_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=1.0,
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        self.sell_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="BTCUSDT",
            price=52000.0,
            quantity=0.5,
            commission=13.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )

    def test_position_manager_initialization(self):
        """Test PositionManager initialization."""
        self.assertEqual(len(self.position_manager._positions), 0)
        self.assertEqual(len(self.position_manager._closed_positions), 0)
        self.assertEqual(self.position_manager.max_total_positions, 100)
        self.assertEqual(self.position_manager.max_position_value, Decimal('1000000.00'))

    def test_create_new_position_buy(self):
        """Test creating a new position with BUY transaction."""
        position = self.position_manager.process_position_update(self.buy_transaction)
        
        self.assertIsNotNone(position)
        self.assertEqual(position.ticker, "BTCUSDT")
        self.assertEqual(position.side, PositionSide.LONG)
        self.assertEqual(position.net_quantity, 1.0)
        self.assertEqual(position.avg_price, 50025.0)  # Price + commission per unit
        
        # Check position is stored
        self.assertEqual(len(self.position_manager._positions), 1)
        self.assertIn("BTCUSDT", self.position_manager._positions)

    def test_create_new_position_sell(self):
        """Test creating a new position with SELL transaction."""
        sell_first_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="ETHUSDT",
            price=3000.0,
            quantity=2.0,
            commission=15.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        position = self.position_manager.process_position_update(sell_first_transaction)
        
        self.assertIsNotNone(position)
        self.assertEqual(position.ticker, "ETHUSDT")
        self.assertEqual(position.side, PositionSide.SHORT)
        self.assertEqual(position.net_quantity, 2.0)

    def test_update_existing_position(self):
        """Test updating an existing position."""
        # Create initial position
        initial_position = self.position_manager.process_position_update(self.buy_transaction)
        initial_quantity = initial_position.net_quantity
        
        # Update with another buy
        buy_more_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=51000.0,
            quantity=0.5,
            commission=12.5,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        updated_position = self.position_manager.process_position_update(buy_more_transaction)
        
        # Should be the same position object
        self.assertEqual(initial_position.id, updated_position.id)
        self.assertEqual(updated_position.net_quantity, initial_quantity + 0.5)
        
        # Still only one position in manager
        self.assertEqual(len(self.position_manager._positions), 1)

    def test_close_position_exact_match(self):
        """Test closing a position with exact quantity match."""
        # Create position with BUY
        self.position_manager.process_position_update(self.buy_transaction)
        
        # Close with exact SELL
        close_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="BTCUSDT",
            price=52000.0,
            quantity=1.0,  # Exact match
            commission=26.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        position = self.position_manager.process_position_update(close_transaction)
        
        # Position should be closed and moved
        self.assertFalse(position.is_open)
        self.assertEqual(len(self.position_manager._positions), 0)
        self.assertEqual(len(self.position_manager._closed_positions), 1)

    def test_partial_position_close(self):
        """Test partial position closing."""
        # Create position
        self.position_manager.process_position_update(self.buy_transaction)
        
        # Partial sell
        position = self.position_manager.process_position_update(self.sell_transaction)
        
        # Position should still be open with reduced quantity
        self.assertTrue(position.is_open)
        self.assertEqual(position.net_quantity, 0.5)  # 1.0 - 0.5
        self.assertEqual(len(self.position_manager._positions), 1)
        self.assertEqual(len(self.position_manager._closed_positions), 0)

    def test_position_value_limits(self):
        """Test position value limits validation."""
        # Test minimum position value
        small_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="SMALLCOIN",
            price=1.0,
            quantity=5.0,  # Value = 5.0, below minimum of 10.0
            commission=0.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.position_manager.process_position_update(small_transaction)
        
        self.assertIn("below minimum", str(context.exception))

    def test_maximum_positions_limit(self):
        """Test maximum positions limit."""
        # Set low limit for testing
        self.position_manager.max_total_positions = 2
        
        # Create maximum positions
        for i in range(2):
            transaction = Transaction(
                time=datetime.now(),
                type=TransactionType.BUY,
                ticker=f"COIN{i}USDT",
                price=1000.0,
                quantity=1.0,
                commission=5.0,
                portfolio_id=self.portfolio.portfolio_id,
                id=idgen.generate_transaction_id()
            )
            self.position_manager.process_position_update(transaction)
        
        # Try to create one more (should fail)
        excess_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="COIN3USDT",
            price=1000.0,
            quantity=1.0,
            commission=5.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.position_manager.process_position_update(excess_transaction)
        
        self.assertIn("Maximum", str(context.exception))

    def test_update_market_values(self):
        """Test updating position market values."""
        # Create position
        position = self.position_manager.process_position_update(self.buy_transaction)
        initial_price = position.current_price
        
        # Update market values
        new_prices = {"BTCUSDT": 55000.0}
        timestamp = datetime.now()
        
        self.position_manager.update_position_market_values(new_prices, timestamp)
        
        # Check price was updated
        updated_position = self.position_manager.get_position("BTCUSDT")
        self.assertEqual(updated_position.current_price, 55000.0)
        self.assertEqual(updated_position.current_time, timestamp)

    def test_get_position_methods(self):
        """Test various position retrieval methods."""
        # Create some positions
        self.position_manager.process_position_update(self.buy_transaction)
        
        eth_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="ETHUSDT",
            price=3000.0,
            quantity=2.0,
            commission=15.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        self.position_manager.process_position_update(eth_transaction)
        
        # Test get_position
        btc_position = self.position_manager.get_position("BTCUSDT")
        self.assertIsNotNone(btc_position)
        self.assertEqual(btc_position.ticker, "BTCUSDT")
        
        # Test get_all_positions
        all_positions = self.position_manager.get_all_positions()
        self.assertEqual(len(all_positions), 2)
        self.assertIn("BTCUSDT", all_positions)
        self.assertIn("ETHUSDT", all_positions)
        
        # Test get_position_count
        self.assertEqual(self.position_manager.get_position_count(), 2)

    def test_total_calculations(self):
        """Test total market value and P&L calculations."""
        # Create positions
        self.position_manager.process_position_update(self.buy_transaction)
        
        # Update market price to create P&L
        new_prices = {"BTCUSDT": 52000.0}
        self.position_manager.update_position_market_values(new_prices, datetime.now())
        
        # Test calculations
        total_market_value = self.position_manager.get_total_market_value()
        total_unrealized_pnl = self.position_manager.get_total_unrealized_pnl()
        
        self.assertGreater(total_market_value, 0)
        self.assertGreater(total_unrealized_pnl, 0)  # Price increased

    def test_position_metrics_calculation(self):
        """Test position metrics calculation."""
        # Create and close a position
        position = self.position_manager.process_position_update(self.buy_transaction)
        position_id = position.id
        
        # Close the position
        close_transaction = Transaction(
            time=datetime.now() + timedelta(days=1),
            type=TransactionType.SELL,
            ticker="BTCUSDT",
            price=52000.0,
            quantity=1.0,
            commission=26.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        self.position_manager.process_position_update(close_transaction)
        
        # Calculate metrics
        metrics = self.position_manager.calculate_position_metrics(position_id)
        
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.position_id, position_id)
        self.assertEqual(metrics.ticker, "BTCUSDT")
        self.assertEqual(metrics.holding_period_days, 1)
        self.assertGreater(metrics.total_pnl, 0)  # Should be profitable

    def test_portfolio_concentration(self):
        """Test portfolio concentration calculation."""
        # Create positions with different values
        btc_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=1.0,  # Value: 50,000
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        eth_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="ETHUSDT",
            price=3000.0,
            quantity=5.0,  # Value: 15,000
            commission=15.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        self.position_manager.process_position_update(btc_transaction)
        self.position_manager.process_position_update(eth_transaction)
        
        # Calculate concentration
        concentration = self.position_manager.get_portfolio_concentration()
        
        self.assertEqual(len(concentration), 2)
        self.assertIn("BTCUSDT", concentration)
        self.assertIn("ETHUSDT", concentration)
        
        # BTC should have higher concentration
        self.assertGreater(concentration["BTCUSDT"], concentration["ETHUSDT"])

    def test_position_limits_validation(self):
        """Test position limits validation."""
        # Test valid transaction
        valid = self.position_manager.validate_position_limits(self.buy_transaction)
        self.assertTrue(valid)
        
        # Test transaction that would exceed value limit
        large_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=100000.0,
            quantity=15.0,  # Value: 1,500,000 > 1,000,000 limit
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        valid = self.position_manager.validate_position_limits(large_transaction)
        self.assertFalse(valid)

    def test_positions_summary(self):
        """Test comprehensive positions summary."""
        # Create some positions
        self.position_manager.process_position_update(self.buy_transaction)
        
        # Create and close another position
        short_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="ETHUSDT",
            price=3000.0,
            quantity=1.0,
            commission=15.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        position = self.position_manager.process_position_update(short_transaction)
        
        # Close the short position
        close_short = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="ETHUSDT",
            price=2900.0,
            quantity=1.0,
            commission=14.5,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        self.position_manager.process_position_update(close_short)
        
        # Get summary
        summary = self.position_manager.get_positions_summary()
        
        self.assertEqual(summary["active_positions"], 1)
        self.assertEqual(summary["closed_positions"], 1)
        self.assertIn("total_market_value", summary)
        self.assertIn("concentration", summary)
        self.assertIn("positions_by_side", summary)

    def test_close_all_positions(self):
        """Test emergency close all positions."""
        # Create multiple positions
        positions_data = [
            ("BTCUSDT", 50000.0, 1.0),
            ("ETHUSDT", 3000.0, 2.0),
            ("ADAUSDT", 1.0, 1000.0)
        ]
        
        for ticker, price, quantity in positions_data:
            transaction = Transaction(
                time=datetime.now(),
                type=TransactionType.BUY,
                ticker=ticker,
                price=price,
                quantity=quantity,
                commission=10.0,
                portfolio_id=self.portfolio.portfolio_id,
                id=idgen.generate_transaction_id()
            )
            self.position_manager.process_position_update(transaction)
        
        self.assertEqual(len(self.position_manager._positions), 3)
        
        # Close all positions
        current_prices = {
            "BTCUSDT": 52000.0,
            "ETHUSDT": 3200.0,
            "ADAUSDT": 1.1
        }
        
        closed_positions = self.position_manager.close_all_positions(current_prices, datetime.now())
        
        self.assertEqual(len(closed_positions), 3)
        self.assertEqual(len(self.position_manager._positions), 0)
        self.assertEqual(len(self.position_manager._closed_positions), 3)

    def test_concurrent_position_updates(self):
        """Test thread safety with concurrent position updates."""
        results = []
        errors = []
        
        def update_position_thread(thread_id):
            try:
                # Each thread creates a different ticker
                transaction = Transaction(
                    time=datetime.now(),
                    type=TransactionType.BUY,
                    ticker=f"COIN{thread_id}USDT",
                    price=1000.0,
                    quantity=1.0,
                    commission=5.0,
                    portfolio_id=self.portfolio.portfolio_id,
                    id=idgen.generate_transaction_id()
                )
                
                position = self.position_manager.process_position_update(transaction)
                results.append(position)
                
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=update_position_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent update errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertEqual(len(self.position_manager._positions), 10)

    def test_concurrent_same_ticker_updates(self):
        """Test thread safety with concurrent updates to same ticker."""
        results = []
        errors = []
        
        def update_same_ticker_thread(thread_id):
            try:
                transaction = Transaction(
                    time=datetime.now(),
                    type=TransactionType.BUY,
                    ticker="TESTTICKER",
                    price=1000.0 + thread_id,  # Slightly different prices
                    quantity=0.1,
                    commission=1.0,
                    portfolio_id=self.portfolio.portfolio_id,
                    id=idgen.generate_transaction_id()
                )
                
                position = self.position_manager.process_position_update(transaction)
                results.append(position)
                
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads updating same ticker
        threads = []
        for i in range(5):
            thread = threading.Thread(target=update_same_ticker_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent same ticker errors: {errors}")
        self.assertEqual(len(results), 5)
        
        # Should have only one position for the ticker
        self.assertEqual(len(self.position_manager._positions), 1)
        
        # Position should have accumulated quantity
        position = self.position_manager.get_position("TESTTICKER")
        self.assertEqual(position.net_quantity, 0.5)  # 5 * 0.1

    def test_precision_calculations(self):
        """Test high precision calculations."""
        # Transaction with values that could cause precision issues
        precise_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="PRECISIONTEST",
            price=33333.33333333,
            quantity=0.33333333,
            commission=5.55555555,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        position = self.position_manager.process_position_update(precise_transaction)
        
        # Check that position was created successfully
        self.assertIsNotNone(position)
        self.assertEqual(position.ticker, "PRECISIONTEST")
        
        # Values should be calculated with proper precision
        self.assertGreater(position.avg_price, 0)
        self.assertGreater(position.net_quantity, 0)


if __name__ == '__main__':
    unittest.main()
