"""
Test suite for TransactionManager class.
Tests transaction validation, processing, error handling, and thread safety.
"""

import unittest
import threading
import time
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch

from itrader.portfolio_handler.transaction_manager import (
    TransactionManager, 
    TransactionState, 
    TransactionContext
)
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.portfolio_handler.exceptions import (
    InvalidTransactionError,
    InsufficientFundsError,
    ConcurrencyError
)
from itrader import idgen


class MockPortfolio:
    """Mock portfolio for testing."""
    def __init__(self, initial_cash=100000.0):
        self.cash = initial_cash
        self.portfolio_id = idgen.generate_portfolio_id()


class TestTransactionManager(unittest.TestCase):
    """Comprehensive test suite for TransactionManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = MockPortfolio(initial_cash=100000.0)
        self.transaction_manager = TransactionManager(self.portfolio)
        
        # Sample valid transaction
        self.valid_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=1.0,
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )

    def test_transaction_manager_initialization(self):
        """Test TransactionManager initialization."""
        self.assertIsNotNone(self.transaction_manager.portfolio)
        self.assertEqual(len(self.transaction_manager._pending_transactions), 0)
        self.assertEqual(len(self.transaction_manager._transaction_history), 0)
        self.assertEqual(self.transaction_manager.min_transaction_amount, Decimal('0.01'))

    def test_valid_buy_transaction_processing(self):
        """Test processing a valid BUY transaction."""
        initial_cash = self.portfolio.cash
        
        result = self.transaction_manager.process_transaction(self.valid_transaction)
        
        self.assertTrue(result)
        self.assertEqual(len(self.transaction_manager._transaction_history), 1)
        
        # Check cash was debited
        expected_cash = initial_cash - (self.valid_transaction.price * self.valid_transaction.quantity + self.valid_transaction.commission)
        self.assertEqual(self.portfolio.cash, expected_cash)

    def test_valid_sell_transaction_processing(self):
        """Test processing a valid SELL transaction."""
        sell_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="BTCUSDT",
            price=52000.0,
            quantity=1.0,
            commission=26.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        initial_cash = self.portfolio.cash
        
        result = self.transaction_manager.process_transaction(sell_transaction)
        
        self.assertTrue(result)
        
        # Check cash was credited
        expected_cash = initial_cash + (sell_transaction.price * sell_transaction.quantity - sell_transaction.commission)
        self.assertEqual(self.portfolio.cash, expected_cash)

    def test_invalid_price_validation(self):
        """Test validation fails for negative or zero price."""
        invalid_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=-1000.0,  # Invalid negative price
            quantity=1.0,
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(invalid_transaction)
        
        self.assertIn("price must be positive", str(context.exception))

    def test_invalid_quantity_validation(self):
        """Test validation fails for negative or zero quantity."""
        invalid_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=0.0,  # Invalid zero quantity
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(invalid_transaction)
        
        self.assertIn("quantity must be positive", str(context.exception))

    def test_negative_commission_validation(self):
        """Test validation fails for negative commission."""
        invalid_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=1.0,
            commission=-25.0,  # Invalid negative commission
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(invalid_transaction)
        
        self.assertIn("Commission cannot be negative", str(context.exception))

    def test_insufficient_funds_error(self):
        """Test insufficient funds error for BUY transaction."""
        # Set portfolio cash to low amount
        self.portfolio.cash = 1000.0
        
        large_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=50000.0,
            quantity=1.0,  # Requires 50,025 but only have 1,000
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InsufficientFundsError) as context:
            self.transaction_manager.process_transaction(large_transaction)
        
        self.assertEqual(context.exception.available_cash, 1000.0)
        self.assertEqual(context.exception.required_cash, 50025.0)

    def test_transaction_value_limits(self):
        """Test transaction value minimum and maximum limits."""
        # Test minimum transaction value
        tiny_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=0.001,  # Very small transaction
            quantity=1.0,
            commission=0.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(tiny_transaction)
        
        self.assertIn("below minimum", str(context.exception))

    def test_high_commission_rate_validation(self):
        """Test validation fails for unreasonably high commission rates."""
        high_commission_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=100.0,
            quantity=1.0,
            commission=60.0,  # 60% commission rate (> 50% limit)
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(high_commission_transaction)
        
        self.assertIn("Commission rate", str(context.exception))

    def test_invalid_ticker_validation(self):
        """Test validation fails for invalid ticker."""
        invalid_ticker_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BT",  # Too short ticker
            price=50000.0,
            quantity=1.0,
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.transaction_manager.process_transaction(invalid_ticker_transaction)
        
        self.assertIn("Invalid ticker format", str(context.exception))

    def test_transaction_cost_calculation_buy(self):
        """Test transaction cost calculation for BUY orders."""
        cost = self.transaction_manager._calculate_transaction_cost(self.valid_transaction)
        expected_cost = Decimal('-50025.0')  # -(50000 * 1 + 25)
        self.assertEqual(cost, expected_cost)

    def test_transaction_cost_calculation_sell(self):
        """Test transaction cost calculation for SELL orders."""
        sell_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="BTCUSDT",
            price=52000.0,
            quantity=1.0,
            commission=26.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        cost = self.transaction_manager._calculate_transaction_cost(sell_transaction)
        expected_cost = Decimal('51974.0')  # 52000 * 1 - 26
        self.assertEqual(cost, expected_cost)

    def test_transaction_history_tracking(self):
        """Test transaction history is properly tracked."""
        # Process multiple transactions
        transaction1 = self.valid_transaction
        transaction2 = Transaction(
            time=datetime.now(),
            type=TransactionType.SELL,
            ticker="ETHUSDT",
            price=3000.0,
            quantity=2.0,
            commission=15.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        self.transaction_manager.process_transaction(transaction1)
        self.transaction_manager.process_transaction(transaction2)
        
        history = self.transaction_manager.get_transaction_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].id, transaction1.id)
        self.assertEqual(history[1].id, transaction2.id)

    def test_transaction_history_limit(self):
        """Test transaction history with limit."""
        # Process multiple transactions
        for i in range(5):
            transaction = Transaction(
                time=datetime.now(),
                type=TransactionType.SELL,
                ticker=f"TEST{i}USDT",
                price=1000.0,
                quantity=1.0,
                commission=5.0,
                portfolio_id=self.portfolio.portfolio_id,
                id=idgen.generate_transaction_id()
            )
            self.transaction_manager.process_transaction(transaction)
        
        # Get limited history
        recent_history = self.transaction_manager.get_transaction_history(limit=3)
        self.assertEqual(len(recent_history), 3)

    def test_concurrent_transaction_processing(self):
        """Test thread safety with concurrent transaction processing."""
        results = []
        errors = []
        
        def process_transaction_thread(transaction_id):
            try:
                transaction = Transaction(
                    time=datetime.now(),
                    type=TransactionType.SELL,
                    ticker=f"TEST{transaction_id}USDT",
                    price=1000.0,
                    quantity=1.0,
                    commission=5.0,
                    portfolio_id=self.portfolio.portfolio_id,
                    id=idgen.generate_transaction_id()
                )
                result = self.transaction_manager.process_transaction(transaction)
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=process_transaction_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent processing errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        
        # Check history integrity
        history = self.transaction_manager.get_transaction_history()
        self.assertEqual(len(history), 10)

    def test_failed_transaction_cleanup(self):
        """Test that failed transactions are properly cleaned up."""
        # Create transaction that will fail validation
        invalid_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=-1000.0,  # Invalid price
            quantity=1.0,
            commission=25.0,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        with self.assertRaises(InvalidTransactionError):
            self.transaction_manager.process_transaction(invalid_transaction)
        
        # Check that pending transactions is cleaned up
        pending = self.transaction_manager.get_pending_transactions()
        self.assertEqual(len(pending), 0)
        
        # Check that failed transaction is not in history
        history = self.transaction_manager.get_transaction_history()
        self.assertEqual(len(history), 0)

    def test_precision_decimal_calculations(self):
        """Test that calculations use proper decimal precision."""
        # Transaction with values that could cause floating point issues
        precise_transaction = Transaction(
            time=datetime.now(),
            type=TransactionType.BUY,
            ticker="BTCUSDT",
            price=33333.33,
            quantity=0.3,
            commission=5.55,
            portfolio_id=self.portfolio.portfolio_id,
            id=idgen.generate_transaction_id()
        )
        
        initial_cash = self.portfolio.cash
        result = self.transaction_manager.process_transaction(precise_transaction)
        
        self.assertTrue(result)
        
        # Calculate expected result with proper precision
        expected_cost = Decimal('33333.33') * Decimal('0.3') + Decimal('5.55')
        expected_cash = initial_cash - float(expected_cost)
        
        self.assertAlmostEqual(self.portfolio.cash, expected_cash, places=2)


if __name__ == '__main__':
    unittest.main()
