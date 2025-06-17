"""
Shared pytest configuration and fixtures for the trading system tests.
"""

import pytest
from datetime import datetime
from itrader.events_handler.event import EventType, FillStatus
from itrader.order_handler.order import OrderType, OrderStatus
from itrader.events_handler.event import PingEvent, BarEvent, SignalEvent, OrderEvent, FillEvent


@pytest.fixture(scope="session")
def base_test_data():
    """
    Provides common test data that can be reused across test modules.
    Session scope means this fixture is created once per test session.
    """
    return {
        'time': datetime.now(),
        'ticker': 'BTCUSDT',
        'side': 'LONG',
        'action': 'BUY',
        'price': 42350.72,
        'quantity': 1,
        'commission': 1.5,
        'stop_loss': 42000,
        'take_profit': 45000,
        'strategy_id': 'test_strategy',
        'portfolio_id': 'portfolio_id',
        'order_type': 'MARKET'
    }


@pytest.fixture
def ping_event(base_test_data):
    """Create a PingEvent for testing."""
    return PingEvent(base_test_data['time'])


@pytest.fixture
def bar_event(base_test_data):
    """Create a BarEvent for testing."""
    return BarEvent(base_test_data['time'], {})


@pytest.fixture  
def signal_event(base_test_data):
    """Create a SignalEvent for testing."""
    return SignalEvent(
        base_test_data['time'],
        base_test_data['order_type'],
        base_test_data['ticker'], 
        base_test_data['side'],
        base_test_data['action'],
        base_test_data['price'],
        base_test_data['quantity'],
        base_test_data['stop_loss'],
        base_test_data['take_profit'],
        base_test_data['strategy_id'],
        base_test_data['portfolio_id']
    )


@pytest.fixture
def market_order_event(signal_event):
    """Create a market OrderEvent for testing."""
    return OrderEvent.new_order(signal_event)


@pytest.fixture
def fill_event(market_order_event, base_test_data):
    """Create a FillEvent for testing."""
    return FillEvent.new_fill('EXECUTED', base_test_data['commission'], market_order_event)


# Pytest marks for categorizing tests
pytestmark = pytest.mark.unit
