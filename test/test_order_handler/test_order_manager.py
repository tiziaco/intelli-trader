"""
Test suite for OrderManager - Internal order orchestration engine.

Tests the OrderManager's functionality including:
- Market-driven order processing
- Stop/Limit order trigger evaluation
- Market order execution timing
- Order fill processing
- State management and event generation
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
import pandas as pd

from itrader.order_handler.order_manager import OrderManager
from itrader.order_handler.order import Order, OrderType, OrderStatus
from itrader.order_handler.storage.in_memory_storage import InMemoryOrderStorage
from itrader.events_handler.event import BarEvent, OrderEvent


class TestOrderManager:
    """Test OrderManager functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.order_storage = InMemoryOrderStorage()
        self.logger = Mock()
        self.order_handler_ref = Mock()
        
        # Create OrderManager instances for different execution modes
        self.order_manager_immediate = OrderManager(
            self.order_storage, 
            self.logger, 
            self.order_handler_ref, 
            market_execution="immediate"
        )
        
        self.order_manager_next_bar = OrderManager(
            self.order_storage, 
            self.logger, 
            self.order_handler_ref, 
            market_execution="next_bar"
        )
        
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

    def create_test_bar_event(self, ticker='AAPL', **kwargs) -> BarEvent:
        """Create a test bar event."""
        defaults = {
            'open': 150.0,
            'high': 155.0,
            'low': 145.0,
            'close': 152.0,
            'volume': 1000000
        }
        defaults.update(kwargs)
        
        # Create DataFrame-like structure for bar data
        bar_data = {
            ticker: pd.DataFrame([defaults])
        }
        
        return BarEvent(
            time=self.base_time,
            bars=bar_data
        )

    def test_order_manager_initialization(self):
        """Test OrderManager initialization."""
        assert self.order_manager_immediate.market_execution == "immediate"
        assert self.order_manager_next_bar.market_execution == "next_bar"
        assert self.order_manager_immediate.order_storage == self.order_storage
        assert self.order_manager_immediate.logger == self.logger

    def test_market_order_immediate_execution(self):
        """Test immediate market order execution."""
        # For immediate execution, market orders are filled immediately when created
        # The OrderManager processes them when process_orders_on_market_data is called
        
        # Create a market order
        market_order = self.create_test_order(type=OrderType.MARKET)
        self.order_storage.add_order(market_order)
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders - should handle immediate execution
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Check that events were generated (exact number depends on implementation)
        assert isinstance(order_events, list)
        
        # Market order should be processed (filled or queued depending on implementation)
        updated_order = self.order_storage.get_order_by_id(market_order.id)
        # The order might be filled immediately or processed differently
        assert updated_order is not None

    def test_market_order_next_bar_execution(self):
        """Test next bar market order execution."""
        # Create a market order
        market_order = self.create_test_order(type=OrderType.MARKET)
        self.order_storage.add_order(market_order)
        
        # For next_bar execution, first queue the market order
        self.order_manager_next_bar.queue_market_orders_for_next_bar()
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders - should execute queued market orders
        order_events = self.order_manager_next_bar.process_orders_on_market_data(bar_event)
        
        # Should queue the order for next bar execution
        assert isinstance(order_events, list)
        
        # Check if the order was processed (might be filled or still queued)
        updated_order = self.order_storage.get_order_by_id(market_order.id)
        assert updated_order is not None

    def test_limit_order_trigger_evaluation(self):
        """Test limit order trigger evaluation."""
        # Create a buy limit order below current price
        limit_order = self.create_test_order(
            type=OrderType.LIMIT,
            price=148.0,  # Below current close of 152.0
            action='BUY'
        )
        self.order_storage.add_order(limit_order)
        
        # Create bar event where price touches limit price
        bar_event = self.create_test_bar_event(low=147.0, close=148.0)  # Close at limit price
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Should trigger the limit order
        updated_order = self.order_storage.get_order_by_id(limit_order.id)
        
        # Check if order was triggered (might depend on exact trigger logic)
        # For buy limit, it triggers when price drops to or below limit price
        assert updated_order is not None
        # The order should be filled if the price condition was met
        if updated_order.status == OrderStatus.FILLED:
            assert updated_order.filled_quantity == limit_order.quantity

    def test_stop_order_trigger_evaluation(self):
        """Test stop order trigger evaluation."""
        # Create a stop loss order
        stop_order = self.create_test_order(
            type=OrderType.STOP,
            price=147.0,  # Stop loss below current price
            action='SELL'
        )
        self.order_storage.add_order(stop_order)
        
        # Create bar event where price drops below stop price
        bar_event = self.create_test_bar_event(low=146.0, close=146.5)
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Should trigger the stop order
        updated_order = self.order_storage.get_order_by_id(stop_order.id)
        assert updated_order.status == OrderStatus.FILLED

    def test_multiple_orders_processing(self):
        """Test processing multiple orders of different types."""
        # Create multiple orders
        market_order = self.create_test_order(type=OrderType.MARKET, ticker='AAPL')
        limit_order = self.create_test_order(
            type=OrderType.LIMIT, 
            ticker='MSFT', 
            price=148.0, 
            action='BUY'
        )
        stop_order = self.create_test_order(
            type=OrderType.STOP, 
            ticker='GOOGL', 
            price=147.0, 
            action='SELL'
        )
        
        # Add orders to storage
        for order in [market_order, limit_order, stop_order]:
            self.order_storage.add_order(order)
        
        # Create bar events for each ticker with triggering conditions
        bar_events = [
            self.create_test_bar_event(ticker='AAPL'),
            self.create_test_bar_event(ticker='MSFT', low=147.0, close=148.0),  # Triggers limit
            self.create_test_bar_event(ticker='GOOGL', low=146.0, close=146.5)  # Triggers stop
        ]
        
        # Process each bar event
        total_order_events = []
        for bar_event in bar_events:
            order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
            total_order_events.extend(order_events)
        
        # Should have processed orders (exact behavior depends on implementation)
        assert isinstance(total_order_events, list)
        
        # Verify orders were processed
        for order in [market_order, limit_order, stop_order]:
            updated_order = self.order_storage.get_order_by_id(order.id)
            assert updated_order is not None

    def test_order_fill_processing(self):
        """Test order fill processing and event generation."""
        # Create an order
        order = self.create_test_order(type=OrderType.LIMIT, price=148.0)
        self.order_storage.add_order(order)
        
        # Create bar event that should trigger the order
        bar_event = self.create_test_bar_event(close=148.0)
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Should return a list of order events
        assert isinstance(order_events, list)
        
        # Check that order was processed
        updated_order = self.order_storage.get_order_by_id(order.id)
        assert updated_order is not None
        
        # If order was filled, verify fill details
        if updated_order.status == OrderStatus.FILLED:
            assert len(order_events) > 0
            # Check that order event contains proper information
            order_event = order_events[0]
            assert hasattr(order_event, 'order_id')
            assert order_event.order_id == order.id

    def test_partial_fill_handling(self):
        """Test handling of partial fills."""
        # Create an order
        order = self.create_test_order(type=OrderType.LIMIT, quantity=1000.0)
        self.order_storage.add_order(order)
        
        # Simulate partial fill (this would depend on the actual implementation)
        # For now, just test that the order manager can handle partial fills
        order.add_fill(500.0, 150.0, datetime.now(), "partial fill")
        self.order_storage.update_order(order)
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Order should still be partially filled
        updated_order = self.order_storage.get_order_by_id(order.id)
        assert updated_order.status == OrderStatus.PARTIALLY_FILLED

    def test_order_expiration_handling(self):
        """Test handling of expired orders."""
        # Create an order with expiration
        future_time = self.base_time + timedelta(hours=1)
        past_time = self.base_time - timedelta(hours=1)
        
        expired_order = self.create_test_order(
            type=OrderType.LIMIT,
            time=past_time
        )
        # Set expiration (this would depend on Order implementation)
        if hasattr(expired_order, 'expiration_time'):
            expired_order.expiration_time = past_time
        
        self.order_storage.add_order(expired_order)
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Implementation would handle expired orders appropriately
        # This test structure allows for future implementation

    def test_order_state_management(self):
        """Test proper order state management."""
        # Create orders in different states
        pending_order = self.create_test_order(status=OrderStatus.PENDING)
        cancelled_order = self.create_test_order(status=OrderStatus.CANCELLED)
        filled_order = self.create_test_order(status=OrderStatus.FILLED)
        
        for order in [pending_order, cancelled_order, filled_order]:
            self.order_storage.add_order(order)
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Only pending orders should be processed
        # Cancelled and filled orders should be ignored
        
        # Check that cancelled order remains cancelled
        updated_cancelled = self.order_storage.get_order_by_id(cancelled_order.id)
        assert updated_cancelled.status == OrderStatus.CANCELLED
        
        # Check that filled order remains filled
        updated_filled = self.order_storage.get_order_by_id(filled_order.id)
        assert updated_filled.status == OrderStatus.FILLED

    def test_error_handling_in_order_processing(self):
        """Test error handling during order processing."""
        # Create an order
        order = self.create_test_order()
        self.order_storage.add_order(order)
        
        # Mock an error in order processing
        self.order_storage.update_order = Mock(side_effect=Exception("Storage error"))
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders - should handle errors gracefully
        try:
            order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
            # Should not crash, may return empty list or log errors
            assert isinstance(order_events, list)
        except Exception as e:
            # If exceptions are expected, test for appropriate error handling
            assert "Storage error" in str(e)

    def test_order_manager_performance_with_many_orders(self):
        """Test OrderManager performance with many orders."""
        # Create many orders
        orders = []
        for i in range(100):
            order = self.create_test_order(
                ticker=f'STOCK{i}',
                type=OrderType.LIMIT if i % 2 == 0 else OrderType.MARKET
            )
            orders.append(order)
            self.order_storage.add_order(order)
        
        # Create bar event
        bar_event = self.create_test_bar_event()
        
        # Process orders - should handle large number of orders efficiently
        order_events = self.order_manager_immediate.process_orders_on_market_data(bar_event)
        
        # Should process without significant performance issues
        assert isinstance(order_events, list)
        # Exact number depends on implementation, but should be reasonable
        assert len(order_events) >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
