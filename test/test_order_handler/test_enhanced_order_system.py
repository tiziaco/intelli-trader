"""
Test suite for enhanced order management system.

Tests the new order lifecycle management, validation, state tracking,
and comprehensive order operations added to the trading system.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from itrader.order_handler.order import (
    Order, OrderStatus, OrderType, OrderStateChange, 
    VALID_ORDER_TRANSITIONS, order_status_map, order_type_map
)
from itrader.order_handler.order_validator import (
    OrderValidator, ValidationResult, ValidationMessage
)
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.order_handler.order_handler import OrderHandler
from itrader.events_handler.event import SignalEvent, BarEvent


class TestOrderLifecycle:
    """Test order lifecycle management and state transitions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.base_time = datetime.now()
        
    def create_test_order(self, **kwargs) -> Order:
        """Create a test order with default values."""
        defaults = {
            'time': self.base_time,
            'type': OrderType.MARKET,
            'status': OrderStatus.PENDING,
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'exchange': 'NYSE',
            'strategy_id': 1,
            'portfolio_id': 1
        }
        defaults.update(kwargs)
        return Order(**defaults)

    def test_order_creation_with_state_tracking(self):
        """Test that new orders are created with proper state tracking."""
        order = self.create_test_order()
        
        # Check initial state
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == 0.0
        assert order.remaining_quantity == 100.0
        assert order.is_active is True
        assert order.is_terminal is False
        assert len(order.state_changes) == 0  # Initial state, no transitions yet
        
    def test_order_properties(self):
        """Test order status properties work correctly."""
        # Test fully filled order
        order = self.create_test_order(filled_quantity=100.0)
        assert order.is_fully_filled is True
        assert order.remaining_quantity == 0.0
        assert order.fill_percentage == 100.0
        
        # Test partially filled order
        order = self.create_test_order(filled_quantity=50.0)
        assert order.is_partially_filled is True
        assert order.remaining_quantity == 50.0
        assert order.fill_percentage == 50.0

    def test_valid_state_transitions(self):
        """Test that only valid state transitions are allowed."""
        order = self.create_test_order()
        
        # Valid transitions from PENDING
        assert order.add_state_change(OrderStatus.FILLED, "market fill")
        order.status = OrderStatus.PENDING  # Reset for next test
        
        assert order.add_state_change(OrderStatus.PARTIALLY_FILLED, "partial fill")
        order.status = OrderStatus.PENDING  # Reset
        
        assert order.add_state_change(OrderStatus.CANCELLED, "user cancellation")
        order.status = OrderStatus.PENDING  # Reset
        
        # Invalid transition
        assert order.add_state_change(OrderStatus.EXPIRED, "invalid transition") is True  # This should be valid
        
        # Test terminal state - no further transitions allowed
        order.status = OrderStatus.FILLED
        assert order.add_state_change(OrderStatus.CANCELLED, "invalid") is False

    def test_order_fill_functionality(self):
        """Test order fill operations."""
        order = self.create_test_order()
        
        # Partial fill
        fill_time = datetime.now()
        success = order.add_fill(30.0, 151.0, fill_time, "partial market fill")
        
        assert success is True
        assert order.filled_quantity == 30.0
        assert order.remaining_quantity == 70.0
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert len(order.state_changes) == 1
        
        # Complete the fill
        success = order.add_fill(70.0, 152.0, fill_time, "complete fill")
        
        assert success is True
        assert order.filled_quantity == 100.0
        assert order.remaining_quantity == 0.0
        assert order.status == OrderStatus.FILLED
        assert order.is_fully_filled is True
        assert len(order.state_changes) == 2

    def test_order_fill_validation(self):
        """Test that order fills are properly validated."""
        order = self.create_test_order()
        
        # Try to fill more than remaining quantity
        success = order.add_fill(150.0, 150.0, datetime.now(), "overfill")
        assert success is False
        assert order.filled_quantity == 0.0
        
        # Try to fill with negative quantity
        success = order.add_fill(-10.0, 150.0, datetime.now(), "negative fill")
        assert success is False

    def test_order_cancellation(self):
        """Test order cancellation functionality."""
        order = self.create_test_order()
        
        # Cancel active order
        success = order.cancel_order("user requested cancellation")
        
        assert success is True
        assert order.status == OrderStatus.CANCELLED
        assert order.is_active is False
        assert order.is_terminal is True
        assert order.rejection_reason == "user requested cancellation"
        
        # Try to cancel already cancelled order
        success = order.cancel_order("double cancellation")
        assert success is False

    def test_order_modification(self):
        """Test order modification functionality."""
        order = self.create_test_order()
        
        # Modify price and quantity
        success = order.modify_order(new_price=155.0, new_quantity=120.0, reason="user modification")
        
        assert success is True
        assert order.price == 155.0
        assert order.quantity == 120.0
        assert order.modification_count == 1
        assert order.last_modification_time is not None
        
        # Try to modify with invalid quantity (less than filled)
        order.filled_quantity = 50.0
        success = order.modify_order(new_quantity=30.0, reason="invalid modification")
        assert success is False

    def test_state_change_history(self):
        """Test that state change history is properly maintained."""
        order = self.create_test_order()
        
        # Add several state changes
        order.add_state_change(OrderStatus.PARTIALLY_FILLED, "first fill")
        order.add_state_change(OrderStatus.FILLED, "complete fill")
        
        history = order.get_state_history()
        assert len(history) == 2
        assert history[0].to_status == OrderStatus.PARTIALLY_FILLED
        assert history[1].to_status == OrderStatus.FILLED
        
        latest = order.get_latest_state_change()
        assert latest.to_status == OrderStatus.FILLED


class TestOrderValidator:
    """Test order validation functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.portfolio_handler = Mock()
        self.validator = OrderValidator(self.portfolio_handler)
        
        # Mock portfolio with sufficient cash
        mock_portfolio = Mock()
        mock_portfolio.cash = 20000.0  # Increased to handle 100 shares at $150
        mock_portfolio.positions = {}
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio

    def create_test_signal(self, **kwargs) -> SignalEvent:
        """Create a test signal event."""
        defaults = {
            'time': datetime.now(),
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'order_type': 'MARKET',
            'strategy_id': 1,
            'portfolio_id': 1,
            'stop_loss': 0.0,
            'take_profit': 0.0,
            'strategy_setting': {}
        }
        defaults.update(kwargs)
        
        signal = SignalEvent(**defaults)
        return signal

    def test_valid_signal_validation(self):
        """Test validation of a valid signal."""
        signal = self.create_test_signal()
        messages = self.validator.validate_signal(signal)
        
        assert self.validator.is_valid(messages) is True
        errors = self.validator.get_errors(messages)
        assert len(errors) == 0

    def test_invalid_signal_validation(self):
        """Test validation catches invalid signals."""
        # Test basic validation (should catch essential field issues)
        
        # Invalid ticker
        signal = self.create_test_signal(ticker="")
        messages = self.validator.validate_signal_basic(signal)
        assert not self.validator.is_valid(messages)
        
        # Invalid action
        signal = self.create_test_signal(action="INVALID")
        messages = self.validator.validate_signal_basic(signal)
        assert not self.validator.is_valid(messages)
        
        # Invalid price
        signal = self.create_test_signal(price=-10.0)
        messages = self.validator.validate_signal_basic(signal)
        assert not self.validator.is_valid(messages)
        
        # Test complete validation (should catch business rule violations)
        
        # Invalid quantity in complete validation
        signal = self.create_test_signal(quantity=0.0)
        messages = self.validator.validate_signal_complete(signal)
        assert not self.validator.is_valid(messages)
        
        # Negative quantity should always fail
        signal = self.create_test_signal(quantity=-10.0)
        messages = self.validator.validate_signal_complete(signal)
        assert not self.validator.is_valid(messages)

    def test_portfolio_constraint_validation(self):
        """Test portfolio constraint validation."""
        # Insufficient cash for buy order
        mock_portfolio = Mock()
        mock_portfolio.cash = 1000.0  # Not enough for 100 * 150 = 15000
        mock_portfolio.positions = {}
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        signal = self.create_test_signal(action="BUY", price=150.0, quantity=100.0)
        messages = self.validator.validate_signal(signal)
        
        assert not self.validator.is_valid(messages)
        errors = self.validator.get_errors(messages)
        assert any("insufficient cash" in msg.message.lower() for msg in errors)

    def test_order_modification_validation(self):
        """Test order modification validation."""
        order = Order(
            time=datetime.now(),
            type=OrderType.LIMIT,
            status=OrderStatus.PARTIALLY_FILLED,
            ticker='AAPL',
            action='BUY',
            price=150.0,
            quantity=100.0,
            exchange='NYSE',
            strategy_id=1,
            portfolio_id=1,
            filled_quantity=30.0
        )
        
        # Valid modification
        messages = self.validator.validate_order_modification(order, new_quantity=120.0)
        assert self.validator.is_valid(messages)
        
        # Invalid modification - new quantity less than filled
        messages = self.validator.validate_order_modification(order, new_quantity=20.0)
        assert not self.validator.is_valid(messages)

    def test_validation_message_structure(self):
        """Test that validation messages have proper structure."""
        signal = self.create_test_signal(price=-10.0)  # Invalid price
        messages = self.validator.validate_signal(signal)
        
        error_messages = self.validator.get_errors(messages)
        assert len(error_messages) > 0
        
        error_msg = error_messages[0]
        assert error_msg.level == ValidationResult.ERROR
        assert error_msg.message is not None
        assert error_msg.field is not None
        assert error_msg.code is not None


class TestEnhancedStorage:
    """Test enhanced storage functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.storage = InMemoryOrderStorage()
        self.base_time = datetime.now()

    def create_test_order(self, **kwargs) -> Order:
        """Create a test order with default values."""
        defaults = {
            'time': self.base_time,
            'type': OrderType.MARKET,
            'status': OrderStatus.PENDING,
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'exchange': 'NYSE',
            'strategy_id': 1,
            'portfolio_id': 1
        }
        defaults.update(kwargs)
        return Order(**defaults)

    def test_active_vs_all_orders_separation(self):
        """Test that storage properly separates active and all orders."""
        # Create orders in different states
        pending_order = self.create_test_order(status=OrderStatus.PENDING)
        filled_order = self.create_test_order(status=OrderStatus.FILLED)
        
        # Add orders
        self.storage.add_order(pending_order)
        self.storage.add_order(filled_order)
        
        # Check active orders (should only include pending)
        active_orders = self.storage.get_active_orders()
        assert len(active_orders) == 1
        assert active_orders[0].status == OrderStatus.PENDING
        
        # Check all orders (should include both)
        all_orders_dict = self.storage.all_orders
        portfolio_orders = all_orders_dict.get('1', {})
        assert len(portfolio_orders) == 2

    def test_order_status_filtering(self):
        """Test filtering orders by status."""
        # Create orders with different statuses
        orders = [
            self.create_test_order(status=OrderStatus.PENDING),
            self.create_test_order(status=OrderStatus.FILLED),
            self.create_test_order(status=OrderStatus.CANCELLED),
            self.create_test_order(status=OrderStatus.PENDING)
        ]
        
        for order in orders:
            self.storage.add_order(order)
        
        # Test status filtering
        pending_orders = self.storage.get_orders_by_status(OrderStatus.PENDING)
        assert len(pending_orders) == 2
        
        filled_orders = self.storage.get_orders_by_status(OrderStatus.FILLED)
        assert len(filled_orders) == 1
        
        cancelled_orders = self.storage.get_orders_by_status(OrderStatus.CANCELLED)
        assert len(cancelled_orders) == 1

    def test_time_range_filtering(self):
        """Test filtering orders by time range."""
        now = datetime.now()
        
        # Create orders with different creation times
        old_order = self.create_test_order()
        old_order.created_at = now - timedelta(days=2)
        
        recent_order = self.create_test_order()
        recent_order.created_at = now - timedelta(hours=1)
        
        self.storage.add_order(old_order)
        self.storage.add_order(recent_order)
        
        # Filter by time range
        start_time = now - timedelta(days=1)
        end_time = now + timedelta(hours=1)
        
        recent_orders = self.storage.get_orders_by_time_range(start_time, end_time)
        assert len(recent_orders) == 1
        assert recent_orders[0].id == recent_order.id

    def test_order_search_functionality(self):
        """Test order search by criteria."""
        # Create orders with different attributes
        orders = [
            self.create_test_order(ticker='AAPL', action='BUY'),
            self.create_test_order(ticker='AAPL', action='SELL'),
            self.create_test_order(ticker='GOOGL', action='BUY'),
        ]
        
        for order in orders:
            self.storage.add_order(order)
        
        # Search by ticker
        aapl_orders = self.storage.search_orders({'ticker': 'AAPL'})
        assert len(aapl_orders) == 2
        
        # Search by ticker and action
        aapl_buy_orders = self.storage.search_orders({'ticker': 'AAPL', 'action': 'BUY'})
        assert len(aapl_buy_orders) == 1

    def test_order_archiving(self):
        """Test order archiving functionality."""
        now = datetime.now()
        
        # Create old completed order
        old_order = self.create_test_order(status=OrderStatus.FILLED)
        old_order.created_at = now - timedelta(days=35)
        
        # Create recent order
        recent_order = self.create_test_order(status=OrderStatus.PENDING)
        recent_order.created_at = now - timedelta(days=1)
        
        self.storage.add_order(old_order)
        self.storage.add_order(recent_order)
        
        # Archive orders older than 30 days
        cutoff_date = now - timedelta(days=30)
        archived_count = self.storage.archive_orders(cutoff_date)
        
        assert archived_count == 1
        assert len(self.storage.archived_orders.get('1', {})) == 1
        assert len(self.storage.all_orders.get('1', {})) == 1

    def test_orders_count_by_status(self):
        """Test getting order counts by status."""
        # Create orders with different statuses
        orders = [
            self.create_test_order(status=OrderStatus.PENDING),
            self.create_test_order(status=OrderStatus.PENDING),
            self.create_test_order(status=OrderStatus.FILLED),
            self.create_test_order(status=OrderStatus.CANCELLED),
        ]
        
        for order in orders:
            self.storage.add_order(order)
        
        status_counts = self.storage.get_orders_count_by_status()
        
        assert status_counts['PENDING'] == 2
        assert status_counts['FILLED'] == 1
        assert status_counts['CANCELLED'] == 1

    def test_order_update_state_management(self):
        """Test that order updates properly manage active/inactive states."""
        order = self.create_test_order(status=OrderStatus.PENDING)
        self.storage.add_order(order)
        
        # Initially in active orders
        active_orders = self.storage.get_active_orders()
        assert len(active_orders) == 1
        
        # Update order to filled state
        order.status = OrderStatus.FILLED
        self.storage.update_order(order)
        
        # Should no longer be in active orders
        active_orders = self.storage.get_active_orders()
        assert len(active_orders) == 0
        
        # But should still be in all orders
        all_orders_dict = self.storage.all_orders
        portfolio_orders = all_orders_dict.get('1', {})
        assert len(portfolio_orders) == 1


class TestEnhancedOrderHandler:
    """Test enhanced order handler functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.events_queue = Mock()
        self.portfolio_handler = Mock()
        
        # Mock portfolio
        mock_portfolio = Mock()
        mock_portfolio.cash = 20000.0  # Increased to handle test orders
        mock_portfolio.positions = {}
        mock_portfolio.exchange = 'NYSE'
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        self.order_handler = OrderHandler(
            self.events_queue, 
            self.portfolio_handler
        )

    def create_test_signal(self, **kwargs) -> SignalEvent:
        """Create a test signal event."""
        defaults = {
            'time': datetime.now(),
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'order_type': 'MARKET',
            'strategy_id': 1,
            'portfolio_id': 1,
            'stop_loss': 0.0,
            'take_profit': 0.0,
            'strategy_setting': {},
            'verified': True
        }
        defaults.update(kwargs)
        
        signal = SignalEvent(**defaults)
        return signal

    def test_signal_validation_integration(self):
        """Test that signal validation is integrated into order processing."""
        # Test LIMIT order - should remain active
        limit_signal = self.create_test_signal(order_type='LIMIT')
        
        # Mock the compliance, sizer, and risk manager to not interfere
        def mock_check_compliance(signal):
            signal.verified = True
        
        def mock_size_order(signal):
            pass  # Keep signal verified
        
        def mock_refine_orders(signal):
            pass  # Keep signal verified
        
        self.order_handler.compliance.check_compliance = mock_check_compliance
        self.order_handler.position_sizer.size_order = mock_size_order
        self.order_handler.risk_manager.refine_orders = mock_refine_orders
        
        self.order_handler.on_signal(limit_signal)
        
        # Should have created an active order (LIMIT orders remain active)
        active_orders = self.order_handler.get_active_orders()
        assert len(active_orders) > 0
        assert active_orders[0].type.name == 'LIMIT'
        assert active_orders[0].status.name == 'PENDING'
        
        # Test MARKET order - should be filled immediately
        market_signal = self.create_test_signal(order_type='MARKET', ticker='MSFT')
        self.order_handler.on_signal(market_signal)
        
        # Market orders should be filled immediately
        all_orders = list(self.order_handler.order_storage.all_orders.values())
        market_order = next((order_dict for order_dict in all_orders 
                           if any(order.ticker == 'MSFT' and order.type.name == 'MARKET' 
                                 for order in order_dict.values())), None)
        
        assert market_order is not None
        msft_order = next(order for order in market_order.values() if order.ticker == 'MSFT')
        assert msft_order.status.name == 'FILLED'

    def test_order_modification_through_handler(self):
        """Test order modification through the order handler."""
        # Create and add an order - use LIMIT order to keep it active
        signal = self.create_test_signal(order_type='LIMIT')
        
        # Mock dependencies to ensure signal gets verified
        def mock_check_compliance(signal):
            signal.verified = True
        
        def mock_size_order(signal):
            pass  # Keep signal verified
        
        def mock_refine_orders(signal):
            pass  # Keep signal verified
        
        self.order_handler.compliance.check_compliance = mock_check_compliance
        self.order_handler.position_sizer.size_order = mock_size_order
        self.order_handler.risk_manager.refine_orders = mock_refine_orders
        
        self.order_handler.on_signal(signal)
        
        # Get the created order
        active_orders = self.order_handler.get_active_orders()
        assert len(active_orders) > 0
        
        order = active_orders[0]
        original_price = order.price
        
        # Modify the order
        success = self.order_handler.modify_order(
            order.id, 
            new_price=155.0, 
            portfolio_id=order.portfolio_id
        )
        
        assert success is True
        
        # Verify modification
        modified_order = self.order_handler.get_order_by_id(order.id)
        assert modified_order.price == 155.0
        assert modified_order.modification_count == 1

    def test_order_cancellation_through_handler(self):
        """Test order cancellation through the order handler."""
        # Create and add an order - use LIMIT order to keep it active
        signal = self.create_test_signal(order_type='LIMIT')
        
        # Mock dependencies to ensure signal gets verified
        def mock_check_compliance(signal):
            signal.verified = True
        
        def mock_size_order(signal):
            pass  # Keep signal verified
        
        def mock_refine_orders(signal):
            pass  # Keep signal verified
        
        self.order_handler.compliance.check_compliance = mock_check_compliance
        self.order_handler.position_sizer.size_order = mock_size_order
        self.order_handler.risk_manager.refine_orders = mock_refine_orders
        
        self.order_handler.on_signal(signal)
        
        # Get the created order
        active_orders = self.order_handler.get_active_orders()
        order = active_orders[0]
        
        # Cancel the order
        success = self.order_handler.cancel_order(
            order.id, 
            portfolio_id=order.portfolio_id,
            reason="test cancellation"
        )
        
        assert success is True
        
        # Verify cancellation
        cancelled_order = self.order_handler.get_order_by_id(order.id)
        assert cancelled_order.status == OrderStatus.CANCELLED
        assert cancelled_order.rejection_reason == "test cancellation"
        
        # Should no longer be in active orders
        active_orders_after = self.order_handler.get_active_orders()
        assert len(active_orders_after) == 0

    def test_order_queries_through_handler(self):
        """Test various order query methods through the handler."""
        # Create multiple orders - use LIMIT orders to keep them active
        signals = [
            self.create_test_signal(ticker='AAPL', action='BUY', order_type='LIMIT'),
            self.create_test_signal(ticker='AAPL', action='SELL', order_type='LIMIT'),
            self.create_test_signal(ticker='GOOGL', action='BUY', order_type='LIMIT'),
        ]
        
        # Mock dependencies to ensure signals get verified
        def mock_check_compliance(signal):
            signal.verified = True
        
        def mock_size_order(signal):
            pass  # Keep signal verified
        
        def mock_refine_orders(signal):
            pass  # Keep signal verified
        
        self.order_handler.compliance.check_compliance = mock_check_compliance
        self.order_handler.position_sizer.size_order = mock_size_order
        self.order_handler.risk_manager.refine_orders = mock_refine_orders
        
        for signal in signals:
            self.order_handler.on_signal(signal)
        
        # Test various queries
        all_active = self.order_handler.get_active_orders()
        assert len(all_active) == 3
        
        aapl_orders = self.order_handler.get_orders_by_ticker('AAPL')
        assert len(aapl_orders) == 2
        
        pending_orders = self.order_handler.get_orders_by_status(OrderStatus.PENDING)
        assert len(pending_orders) == 3
        
        # Test search
        buy_orders = self.order_handler.search_orders({'action': 'BUY'})
        assert len(buy_orders) == 2

    def test_order_summary_and_statistics(self):
        """Test order summary and statistics functionality."""
        # Create orders and fill some - use LIMIT order to keep it active initially
        signal = self.create_test_signal(order_type='LIMIT')
        
        # Mock dependencies to ensure signal gets verified
        def mock_check_compliance(signal):
            signal.verified = True
        
        def mock_size_order(signal):
            pass  # Keep signal verified
        
        def mock_refine_orders(signal):
            pass  # Keep signal verified
        
        self.order_handler.compliance.check_compliance = mock_check_compliance
        self.order_handler.position_sizer.size_order = mock_size_order
        self.order_handler.risk_manager.refine_orders = mock_refine_orders
        
        self.order_handler.on_signal(signal)
        
        # Get and fill an order
        active_orders = self.order_handler.get_active_orders()
        order = active_orders[0]
        
        # Simulate partial fill
        order.add_fill(50.0, 151.0, datetime.now(), "partial fill")
        self.order_handler.order_storage.update_order(order)
        
        # Get summary
        summary = self.order_handler.get_orders_summary()
        assert 'PARTIALLY_FILLED' in summary
        assert summary['PARTIALLY_FILLED'] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
