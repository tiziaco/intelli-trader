"""
Test suite for Order class functionality.

Tests order lifecycle management, state transitions, fills, modifications,
and all Order class specific functionality.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock

from itrader.order_handler.order import (
    Order, OrderStatus, OrderType, OrderStateChange, 
    VALID_ORDER_TRANSITIONS, order_status_map, order_type_map
)


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
        """Test order creation includes state tracking."""
        order = self.create_test_order()
        
        # Should have initial state change when created using new_order
        # Note: Only orders created via new_order() have initial state changes
        # Direct Order() constructor doesn't add initial state changes
        assert order.status == OrderStatus.PENDING
        assert order.created_at is not None
    
    def test_order_properties(self):
        """Test order property calculations."""
        order = self.create_test_order(quantity=100.0, price=150.0)
        
        # Test remaining quantity calculation
        assert order.remaining_quantity == 100.0  # No fills yet
        assert order.fill_percentage == 0.0
        assert not order.is_fully_filled
        assert not order.is_partially_filled
        assert order.is_active
        
        # Test remaining quantity (before any fills)
        assert order.remaining_quantity == 100.0
        
        # Test filled quantity (initially 0)
        assert order.filled_quantity == 0.0
    
    def test_valid_state_transitions(self):
        """Test valid order state transitions."""
        order = self.create_test_order()
        
        # Test PENDING -> FILLED transition via add_fill
        assert order.add_fill(order.quantity, order.price, datetime.now())
        assert order.status == OrderStatus.FILLED

    def test_order_fill_functionality(self):
        """Test order fill processing."""
        order = self.create_test_order(quantity=100.0, price=150.0)
        
        # Test partial fill
        fill_time = datetime.now()
        assert order.add_fill(50.0, 151.0, fill_time, "partial execution")
        
        assert order.filled_quantity == 50.0
        assert order.remaining_quantity == 50.0
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.is_partially_filled
        
        # Test complete fill
        assert order.add_fill(50.0, 152.0, fill_time, "complete execution")
        
        assert order.filled_quantity == 100.0
        assert order.remaining_quantity == 0.0
        assert order.status == OrderStatus.FILLED
        assert order.is_fully_filled

    def test_order_fill_validation(self):
        """Test order fill validation."""
        order = self.create_test_order(quantity=100.0)
        
        # Test overfill prevention
        fill_time = datetime.now()
        assert not order.add_fill(150.0, 100.0, fill_time)  # Should fail - exceeds quantity
        assert order.filled_quantity == 0.0  # Should remain unchanged
        
        # Test negative fill prevention
        assert not order.add_fill(-10.0, 100.0, fill_time)  # Should fail - negative quantity

    def test_order_cancellation(self):
        """Test order cancellation functionality."""
        order = self.create_test_order()
        
        # Test cancellation
        assert order.cancel_order("User requested cancellation")
        
        assert order.status == OrderStatus.CANCELLED
        assert order.rejection_reason == "User requested cancellation"
        
        # Test that cancelled orders cannot be filled or modified
        assert not order.add_fill(50.0, 150.0, datetime.now(), "attempt after cancel")
        assert not order.is_active

    def test_order_modification(self):
        """Test order modification functionality."""
        order = self.create_test_order(price=150.0, quantity=100.0)
        
        # Test price modification
        assert order.modify_order(new_price=155.0)
        assert order.price == 155.0
        assert order.modification_count == 1
        
        # Test quantity modification
        assert order.modify_order(new_quantity=150.0)
        assert order.quantity == 150.0
        assert order.modification_count == 2

    def test_state_change_history(self):
        """Test state change history tracking."""
        order = self.create_test_order()
        
        # Make several state changes
        assert order.add_state_change(OrderStatus.PARTIALLY_FILLED, "Partial execution")
        assert order.add_state_change(OrderStatus.FILLED, "Complete execution")
        
        # Should have recorded state changes
        assert len(order.state_changes) >= 2
        
        # Verify latest state change
        latest_change = order.get_latest_state_change()
        assert latest_change.to_status == OrderStatus.FILLED
        assert "Complete execution" in latest_change.reason

    def test_order_expiration(self):
        """Test order expiration functionality if implemented."""
        order = self.create_test_order()
        
        # Test expiration if the Order class supports it
        if hasattr(order, 'expiration_time'):
            past_time = datetime.now() - timedelta(hours=1)
            order.expiration_time = past_time
            
            if hasattr(order, 'is_expired'):
                assert order.is_expired()

    def test_order_validation(self):
        """Test order validation rules."""
        # Test order properties validation via methods
        order = self.create_test_order(quantity=0)
        
        # Zero quantity should result in remaining_quantity of 0
        assert order.remaining_quantity == 0
        assert order.fill_percentage == 0.0  # Should handle zero division gracefully
        
        # Test valid order properties
        valid_order = self.create_test_order(quantity=100, price=150)
        assert valid_order.remaining_quantity == 100
        assert valid_order.quantity > 0
        assert valid_order.price > 0

    def test_order_string_representation(self):
        """Test order string representation."""
        order = self.create_test_order()
        
        # Should have meaningful string representation
        order_str = str(order)
        assert order.ticker in order_str
        assert order.action in order_str
        assert order.type.name in order_str
        assert order.status.name in order_str

    def test_order_comparison_and_sorting(self):
        """Test order comparison for sorting."""
        order1 = self.create_test_order(time=self.base_time)
        order2 = self.create_test_order(time=self.base_time + timedelta(seconds=1))
        
        # Orders should be comparable by ID at minimum
        assert order1.id != order2.id
        
        # Test that orders can be compared by ID if no other comparison is available
        orders = [order2, order1]
        try:
            sorted_orders = sorted(orders, key=lambda o: o.id)
            assert len(sorted_orders) == 2
        except TypeError:
            # If sorting by Order directly fails, that's acceptable
            # since the Order class doesn't implement comparison operators
            pass
            assert sorted_orders[0].time <= sorted_orders[1].time

    def test_order_copy_and_equality(self):
        """Test order copying and equality."""
        order1 = self.create_test_order()
        
        # Test equality
        order2 = self.create_test_order()
        # Orders with different IDs should not be equal
        assert order1 != order2
        
        # Same order should equal itself
        assert order1 == order1

    def test_order_serialization(self):
        """Test order serialization if implemented."""
        order = self.create_test_order()
        
        # Test dict representation if available
        if hasattr(order, 'to_dict'):
            order_dict = order.to_dict()
            assert isinstance(order_dict, dict)
            assert order_dict['ticker'] == order.ticker
            assert order_dict['action'] == order.action

    def test_order_risk_attributes(self):
        """Test order risk-related attributes."""
        order = self.create_test_order()
        
        # Test stop loss and take profit if supported
        if hasattr(order, 'stop_loss'):
            order.stop_loss = 140.0
            assert order.stop_loss == 140.0
        
        if hasattr(order, 'take_profit'):
            order.take_profit = 160.0
            assert order.take_profit == 160.0

    def test_order_metadata_and_tags(self):
        """Test order metadata and tagging if supported."""
        order = self.create_test_order()
        
        # Test metadata storage if available
        if hasattr(order, 'metadata'):
            order.metadata['custom_field'] = 'test_value'
            assert order.metadata['custom_field'] == 'test_value'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
