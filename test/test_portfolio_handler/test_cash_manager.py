"""
Test suite for CashManager class.
Tests cash operations, precision, thread safety, and validation.
"""

import unittest
import threading
import time
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock

from itrader.portfolio_handler.cash_manager import (
    CashManager, 
    CashOperationType, 
    CashOperation
)
from itrader.portfolio_handler.exceptions import (
    InvalidTransactionError,
    InsufficientFundsError
)


class MockPortfolio:
    """Mock portfolio for testing."""
    def __init__(self):
        self.portfolio_id = 12345


class TestCashManager(unittest.TestCase):
    """Comprehensive test suite for CashManager."""

    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = MockPortfolio()
        self.initial_cash = 100000.0
        self.cash_manager = CashManager(self.portfolio, self.initial_cash)

    def test_cash_manager_initialization(self):
        """Test CashManager initialization."""
        self.assertEqual(self.cash_manager.balance, Decimal('100000.00'))
        self.assertEqual(self.cash_manager.available_balance, Decimal('100000.00'))
        self.assertEqual(self.cash_manager.reserved_balance, Decimal('0.00'))
        self.assertEqual(len(self.cash_manager._cash_operations), 0)

    def test_deposit_valid_amount(self):
        """Test valid cash deposit."""
        initial_balance = self.cash_manager.balance
        deposit_amount = 5000.0
        
        result = self.cash_manager.deposit(deposit_amount, "Test deposit")
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.balance, initial_balance + Decimal('5000.00'))
        
        # Check operation was recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].operation_type, CashOperationType.DEPOSIT)
        self.assertEqual(operations[0].amount, Decimal('5000.00'))

    def test_deposit_with_reference_id(self):
        """Test deposit with reference ID."""
        reference_id = "DEPOSIT_123"
        
        result = self.cash_manager.deposit(1000.0, "Test deposit", reference_id)
        
        self.assertTrue(result)
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(operations[0].reference_id, reference_id)

    def test_deposit_exceeds_maximum_balance(self):
        """Test deposit that would exceed maximum balance."""
        # Set a low maximum balance for testing
        self.cash_manager.max_balance = Decimal('150000.00')
        
        with self.assertRaises(InvalidTransactionError) as context:
            self.cash_manager.deposit(60000.0, "Large deposit")
        
        self.assertIn("exceed maximum balance limit", str(context.exception))

    def test_deposit_invalid_amount(self):
        """Test deposit with invalid (negative) amount."""
        with self.assertRaises(InvalidTransactionError) as context:
            self.cash_manager.deposit(-1000.0, "Invalid deposit")
        
        self.assertIn("must be positive", str(context.exception))

    def test_withdrawal_valid_amount(self):
        """Test valid cash withdrawal."""
        initial_balance = self.cash_manager.balance
        withdrawal_amount = 25000.0
        
        result = self.cash_manager.withdraw(withdrawal_amount, "Test withdrawal")
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.balance, initial_balance - Decimal('25000.00'))
        
        # Check operation was recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].operation_type, CashOperationType.WITHDRAWAL)
        self.assertEqual(operations[0].amount, Decimal('25000.00'))

    def test_withdrawal_insufficient_funds(self):
        """Test withdrawal with insufficient funds."""
        with self.assertRaises(InsufficientFundsError) as context:
            self.cash_manager.withdraw(150000.0, "Large withdrawal")
        
        self.assertEqual(context.exception.required_cash, 150000.0)
        self.assertEqual(context.exception.available_cash, 100000.0)

    def test_withdrawal_invalid_amount(self):
        """Test withdrawal with invalid amount."""
        with self.assertRaises(InvalidTransactionError) as context:
            self.cash_manager.withdraw(0.0, "Invalid withdrawal")
        
        self.assertIn("must be positive", str(context.exception))

    def test_transaction_cash_flow_debit(self):
        """Test transaction cash flow debit."""
        initial_balance = self.cash_manager.balance
        transaction_amount = 5000.0
        
        result = self.cash_manager.process_transaction_cash_flow(
            transaction_amount, True, "Buy transaction", "TXN_123"
        )
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.balance, initial_balance - Decimal('5000.00'))
        
        # Check operation was recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].operation_type, CashOperationType.TRANSACTION_DEBIT)

    def test_transaction_cash_flow_credit(self):
        """Test transaction cash flow credit."""
        initial_balance = self.cash_manager.balance
        transaction_amount = 7500.0
        
        result = self.cash_manager.process_transaction_cash_flow(
            transaction_amount, False, "Sell transaction", "TXN_124"
        )
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.balance, initial_balance + Decimal('7500.00'))
        
        # Check operation was recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].operation_type, CashOperationType.TRANSACTION_CREDIT)

    def test_transaction_cash_flow_insufficient_funds(self):
        """Test transaction debit with insufficient funds."""
        with self.assertRaises(InsufficientFundsError):
            self.cash_manager.process_transaction_cash_flow(
                150000.0, True, "Large buy", "TXN_125"
            )

    def test_cash_reservation(self):
        """Test cash reservation for pending orders."""
        reservation_amount = 30000.0
        
        result = self.cash_manager.reserve_cash(
            reservation_amount, "Order reservation", "ORDER_123"
        )
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.reserved_balance, Decimal('30000.00'))
        self.assertEqual(self.cash_manager.available_balance, Decimal('70000.00'))
        self.assertEqual(self.cash_manager.balance, Decimal('100000.00'))  # Total unchanged
        
        # Check operation was recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].operation_type, CashOperationType.RESERVATION)

    def test_cash_reservation_insufficient_funds(self):
        """Test cash reservation with insufficient available funds."""
        with self.assertRaises(InsufficientFundsError):
            self.cash_manager.reserve_cash(150000.0, "Large reservation", "ORDER_124")

    def test_release_cash_reservation(self):
        """Test releasing cash reservation."""
        # First, make a reservation
        self.cash_manager.reserve_cash(20000.0, "Initial reservation", "ORDER_125")
        
        # Then release part of it
        result = self.cash_manager.release_cash_reservation(
            15000.0, "Partial release", "ORDER_125"
        )
        
        self.assertTrue(result)
        self.assertEqual(self.cash_manager.reserved_balance, Decimal('5000.00'))
        self.assertEqual(self.cash_manager.available_balance, Decimal('95000.00'))
        
        # Check operations were recorded
        operations = self.cash_manager.get_cash_operations()
        self.assertEqual(len(operations), 2)
        self.assertEqual(operations[1].operation_type, CashOperationType.RELEASE_RESERVATION)

    def test_release_more_than_reserved(self):
        """Test releasing more cash than reserved."""
        # Make small reservation
        self.cash_manager.reserve_cash(1000.0, "Small reservation", "ORDER_126")
        
        # Try to release more
        with self.assertRaises(InvalidTransactionError) as context:
            self.cash_manager.release_cash_reservation(2000.0, "Invalid release", "ORDER_126")
        
        self.assertIn("Cannot release", str(context.exception))

    def test_decimal_precision(self):
        """Test decimal precision in calculations."""
        # Test with amounts that could cause floating point issues
        deposit_amount = 33333.33
        withdrawal_amount = 11111.11
        
        self.cash_manager.deposit(deposit_amount, "Precision test deposit")
        self.cash_manager.withdraw(withdrawal_amount, "Precision test withdrawal")
        
        # Calculate expected balance
        expected_balance = Decimal('100000.00') + Decimal('33333.33') - Decimal('11111.11')
        self.assertEqual(self.cash_manager.balance, expected_balance)

    def test_precision_rounding(self):
        """Test proper rounding with small amounts."""
        # Amount with more than 2 decimal places
        deposit_amount = 1000.999  # Should round to 1001.00
        
        self.cash_manager.deposit(deposit_amount, "Rounding test")
        
        expected_balance = Decimal('100000.00') + Decimal('1001.00')
        self.assertEqual(self.cash_manager.balance, expected_balance)

    def test_get_balance_info(self):
        """Test getting comprehensive balance information."""
        # Make some operations
        self.cash_manager.deposit(5000.0, "Test deposit")
        self.cash_manager.reserve_cash(15000.0, "Test reservation", "ORDER_127")
        
        balance_info = self.cash_manager.get_balance_info()
        
        self.assertEqual(balance_info["total_balance"], 105000.0)
        self.assertEqual(balance_info["available_balance"], 90000.0)
        self.assertEqual(balance_info["reserved_balance"], 15000.0)
        self.assertIn("min_balance", balance_info)
        self.assertIn("max_balance", balance_info)

    def test_get_cash_operations_with_filter(self):
        """Test getting cash operations with type filter."""
        # Perform different types of operations
        self.cash_manager.deposit(1000.0, "Deposit 1")
        self.cash_manager.withdraw(500.0, "Withdrawal 1")
        self.cash_manager.deposit(2000.0, "Deposit 2")
        
        # Get only deposit operations
        deposit_operations = self.cash_manager.get_cash_operations(
            operation_type=CashOperationType.DEPOSIT
        )
        
        self.assertEqual(len(deposit_operations), 2)
        self.assertTrue(all(op.operation_type == CashOperationType.DEPOSIT for op in deposit_operations))

    def test_get_cash_operations_with_limit(self):
        """Test getting cash operations with limit."""
        # Perform multiple operations
        for i in range(5):
            self.cash_manager.deposit(100.0, f"Deposit {i}")
        
        # Get limited operations
        limited_operations = self.cash_manager.get_cash_operations(limit=3)
        
        self.assertEqual(len(limited_operations), 3)

    def test_balance_consistency_validation(self):
        """Test balance consistency validation."""
        # Normal state should be consistent
        self.assertTrue(self.cash_manager.validate_balance_consistency())
        
        # Test with manipulated state (simulating corruption)
        original_reserved = self.cash_manager._reserved_cash
        self.cash_manager._reserved_cash = Decimal('-100.00')  # Invalid negative reserved
        
        self.assertFalse(self.cash_manager.validate_balance_consistency())
        
        # Restore state
        self.cash_manager._reserved_cash = original_reserved

    def test_concurrent_operations(self):
        """Test thread safety with concurrent operations."""
        results = []
        errors = []
        
        def deposit_thread(thread_id):
            try:
                result = self.cash_manager.deposit(100.0, f"Concurrent deposit {thread_id}")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        def withdraw_thread(thread_id):
            try:
                result = self.cash_manager.withdraw(50.0, f"Concurrent withdrawal {thread_id}")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            dep_thread = threading.Thread(target=deposit_thread, args=(i,))
            with_thread = threading.Thread(target=withdraw_thread, args=(i,))
            threads.extend([dep_thread, with_thread])
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent operation errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        
        # Check final balance consistency
        self.assertTrue(self.cash_manager.validate_balance_consistency())
        
        # Expected balance: 100000 + (5 * 100) - (5 * 50) = 100000 + 500 - 250 = 100250
        expected_balance = Decimal('100250.00')
        self.assertEqual(self.cash_manager.balance, expected_balance)

    def test_concurrent_reservation_operations(self):
        """Test thread safety with concurrent reservation operations."""
        results = []
        errors = []
        
        def reserve_release_thread(thread_id):
            try:
                # Reserve cash
                reserve_result = self.cash_manager.reserve_cash(
                    1000.0, f"Reservation {thread_id}", f"ORDER_{thread_id}"
                )
                
                # Small delay to increase chance of race conditions
                time.sleep(0.01)
                
                # Release cash
                release_result = self.cash_manager.release_cash_reservation(
                    1000.0, f"Release {thread_id}", f"ORDER_{thread_id}"
                )
                
                results.extend([reserve_result, release_result])
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=reserve_release_thread, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Concurrent reservation errors: {errors}")
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        
        # Final state should have no reservations
        self.assertEqual(self.cash_manager.reserved_balance, Decimal('0.00'))
        self.assertEqual(self.cash_manager.available_balance, self.cash_manager.balance)

    def test_operation_id_uniqueness(self):
        """Test that operation IDs are unique."""
        operation_ids = set()
        
        for i in range(100):
            self.cash_manager.deposit(1.0, f"Test deposit {i}")
        
        operations = self.cash_manager.get_cash_operations()
        
        for operation in operations:
            self.assertNotIn(operation.operation_id, operation_ids)
            operation_ids.add(operation.operation_id)
        
        self.assertEqual(len(operation_ids), 100)


if __name__ == '__main__':
    unittest.main()
