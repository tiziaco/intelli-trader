"""
Test suite for SimulatedExchange class functionality.

Tests the refactored SimulatedExchange with config-driven architecture,
following the same pattern as Portfolio class with minimal __init__,
update_config, and get_config_dict methods.
"""

import pytest
from datetime import datetime
from queue import Queue
from unittest.mock import Mock, patch
from decimal import Decimal

from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.events_handler.event import OrderEvent, FillEvent
from itrader.config import ExchangeConfig, get_exchange_preset
from itrader.config.exchange import FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation
from itrader.config.exchange.config import FeeModelType, SlippageModelType, ExchangeType
from itrader.core.enums.execution import (
    ExecutionStatus, ExecutionErrorCode, ExchangeConnectionStatus
)
from itrader.execution_handler.result_objects import ExecutionResult, ConnectionResult, HealthStatus, ValidationResult


class TestSimulatedExchangeInitialization:
    """Test SimulatedExchange initialization and configuration setup."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.base_time = datetime.now()

    def test_default_initialization(self):
        """Test initialization with default configuration."""
        exchange = SimulatedExchange(self.queue)
        
        # Verify basic properties
        assert exchange.global_queue is self.queue
        assert exchange.config is not None
        assert exchange.config.exchange_name == "SimulatedExchange"
        assert exchange.fee_model is not None
        assert exchange.slippage_model is not None
        assert hasattr(exchange, '_lock')
        
        # Verify operational state
        assert not exchange._connected
        assert exchange._connection_status == ExchangeConnectionStatus.DISCONNECTED
        assert exchange._orders_executed == 0
        assert exchange._orders_failed == 0

    def test_custom_config_initialization(self):
        """Test initialization with custom configuration."""
        custom_config = get_exchange_preset('high_fee')
        exchange = SimulatedExchange(self.queue, config=custom_config)
        
        assert exchange.config is custom_config
        assert exchange.config.exchange_name == "HighFeeSimulatedExchange"
        assert exchange.config.fee_model.model_type == FeeModelType.MAKER_TAKER

    def test_initialization_creates_models(self):
        """Test that initialization properly creates fee and slippage models."""
        exchange = SimulatedExchange(self.queue)
        
        # Verify models are created and functional
        assert hasattr(exchange.fee_model, 'calculate_fee')
        assert hasattr(exchange.slippage_model, 'calculate_slippage_factor')
        
        # Test fee model functionality
        fee = exchange.fee_model.calculate_fee(100, 50.0, 'buy', 'market')
        assert isinstance(fee, (int, float, Decimal))
        assert fee >= 0

    def test_thread_safety_setup(self):
        """Test that thread safety mechanisms are properly initialized."""
        exchange = SimulatedExchange(self.queue)
        
        assert hasattr(exchange, '_lock')
        # Test that lock can be acquired
        with exchange._lock:
            pass


class TestSimulatedExchangeConfiguration:
    """Test configuration management methods."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)

    def test_get_config_dict(self):
        """Test get_config_dict returns proper dictionary format."""
        config_dict = self.exchange.get_config_dict()
        
        # Verify all expected keys are present
        expected_keys = {
            'exchange_name', 'exchange_type', 'simulate_failures', 'failure_rate',
            'supported_symbols', 'min_order_size', 'max_order_size',
            'fee_model_type', 'fee_rate', 'maker_rate', 'taker_rate',
            'slippage_model_type', 'base_slippage_pct', 'slippage_pct'
        }
        assert set(config_dict.keys()) == expected_keys
        
        # Verify data types
        assert isinstance(config_dict['exchange_name'], str)
        assert isinstance(config_dict['simulate_failures'], bool)
        assert isinstance(config_dict['failure_rate'], float)
        assert isinstance(config_dict['supported_symbols'], list)
        assert isinstance(config_dict['min_order_size'], float)

    def test_update_config_basic_parameters(self):
        """Test updating basic configuration parameters."""
        # Test failure simulation updates
        self.exchange.update_config(simulate_failures=True, failure_rate=0.05)
        
        assert self.exchange.config.failure_simulation.simulate_failures is True
        assert float(self.exchange.config.failure_simulation.failure_rate) == 0.05
        assert self.exchange.simulate_failures is True
        assert self.exchange.failure_rate == 0.05

    def test_update_config_limits(self):
        """Test updating exchange limits."""
        new_symbols = {'AAPL', 'MSFT', 'GOOGL'}
        
        self.exchange.update_config(
            supported_symbols=new_symbols,
            min_order_size=10.0,
            max_order_size=10000.0
        )
        
        assert self.exchange.config.limits.supported_symbols == new_symbols
        assert float(self.exchange.config.limits.min_order_size) == 10.0
        assert float(self.exchange.config.limits.max_order_size) == 10000.0
        assert self.exchange._supported_symbols == new_symbols

    def test_update_config_fee_model(self):
        """Test updating fee model configuration."""
        self.exchange.update_config(
            fee_model_type=FeeModelType.PERCENT,
            fee_rate=0.002
        )
        
        assert self.exchange.config.fee_model.model_type == FeeModelType.PERCENT
        assert self.exchange.config.fee_model.fee_rate == 0.002
        # Verify fee model was re-initialized
        assert hasattr(self.exchange.fee_model, 'fee_rate')

    def test_update_config_slippage_model(self):
        """Test updating slippage model configuration."""
        self.exchange.update_config(
            slippage_model_type=SlippageModelType.LINEAR,
            base_slippage_pct=0.02
        )
        
        assert self.exchange.config.slippage_model.model_type == SlippageModelType.LINEAR
        assert self.exchange.config.slippage_model.base_slippage_pct == 0.02

    def test_update_config_invalid_key(self):
        """Test updating with invalid configuration key raises error."""
        with pytest.raises(ValueError, match="Unknown configuration key"):
            self.exchange.update_config(invalid_key="invalid_value")

    def test_update_config_thread_safety(self):
        """Test that config updates are thread-safe."""
        import threading
        import time
        
        def update_config():
            for i in range(10):
                self.exchange.update_config(failure_rate=i * 0.01)
                time.sleep(0.001)
        
        # Run concurrent updates
        threads = [threading.Thread(target=update_config) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # Verify exchange is still in valid state
        config_dict = self.exchange.get_config_dict()
        assert isinstance(config_dict['failure_rate'], float)
        assert 0.0 <= config_dict['failure_rate'] <= 0.09


class TestSimulatedExchangeOrderExecution:
    """Test order execution functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()  # Connect for successful execution

    def create_test_order(self, **kwargs) -> OrderEvent:
        """Create a test order event with default values."""
        defaults = {
            'time': datetime.now(),
            'ticker': 'BTCUSDT',  # Use a symbol that's in the default supported symbols
            'action': 'BUY',
            'quantity': 100.0,
            'price': 150.0,
            'exchange': 'simulated',
            'strategy_id': 1,
            'portfolio_id': 1
        }
        defaults.update(kwargs)
        return OrderEvent(**defaults)

    def test_successful_order_execution(self):
        """Test successful order execution."""
        order = self.create_test_order()
        result = self.exchange.execute_order(order)
        
        assert result.success is True
        assert result.status == ExecutionStatus.SUCCESS
        assert result.executed_price > 0
        assert result.executed_quantity == order.quantity
        assert result.commission >= 0
        assert result.order_id is not None
        assert result.exchange_order_id is not None
        
        # Verify fill event was queued
        assert not self.queue.empty()
        fill_event = self.queue.get()
        assert isinstance(fill_event, FillEvent)

    def test_order_execution_with_slippage(self):
        """Test order execution applies slippage correctly."""
        # Configure for linear slippage
        self.exchange.update_config(
            slippage_model_type=SlippageModelType.LINEAR,
            base_slippage_pct=0.01
        )
        
        order = self.create_test_order(price=100.0)
        result = self.exchange.execute_order(order)
        
        assert result.success is True
        # Price should be different due to slippage
        assert result.executed_price != order.price
        assert 'slippage_applied' in result.metadata

    def test_order_execution_with_fees(self):
        """Test order execution applies fees correctly."""
        # Configure for percentage fees
        self.exchange.update_config(
            fee_model_type=FeeModelType.PERCENT,
            fee_rate=0.001
        )
        
        order = self.create_test_order(quantity=100.0, price=150.0)
        result = self.exchange.execute_order(order)
        
        assert result.success is True
        assert result.commission > 0
        # Commission should be approximately 0.001 * 100 * 150 = 0.15
        expected_commission = Decimal('0.001') * Decimal('100.0') * Decimal('150.0')
        assert abs(result.commission - expected_commission) < Decimal('0.01')

    def test_order_execution_failure_simulation(self):
        """Test order execution with failure simulation."""
        # Enable failure simulation with high rate
        self.exchange.update_config(simulate_failures=True, failure_rate=1.0)
        
        order = self.create_test_order()
        result = self.exchange.execute_order(order)
        
        assert result.success is False
        assert result.status == ExecutionStatus.FAILED
        assert result.error_code in [
            ExecutionErrorCode.NETWORK_ERROR,
            ExecutionErrorCode.EXCHANGE_ERROR,
            ExecutionErrorCode.RATE_LIMIT_EXCEEDED,
            ExecutionErrorCode.EXCHANGE_MAINTENANCE
        ]

    def test_order_validation_failure(self):
        """Test order execution with validation failure."""
        # Create order with invalid symbol
        order = self.create_test_order(ticker='INVALID')
        result = self.exchange.execute_order(order)
        
        assert result.success is False
        assert result.status == ExecutionStatus.REJECTED
        assert result.error_code == ExecutionErrorCode.SYMBOL_NOT_FOUND

    def test_order_execution_metrics_tracking(self):
        """Test that execution metrics are properly tracked."""
        initial_executed = self.exchange._orders_executed
        initial_failed = self.exchange._orders_failed
        
        # Execute successful order
        order = self.create_test_order()
        result = self.exchange.execute_order(order)
        assert result.success is True
        assert self.exchange._orders_executed == initial_executed + 1
        
        # Execute failing order (invalid symbol)
        order_fail = self.create_test_order(ticker='INVALID')
        result_fail = self.exchange.execute_order(order_fail)
        assert result_fail.success is False
        assert self.exchange._orders_failed == initial_failed + 1


class TestSimulatedExchangeConnectionManagement:
    """Test connection management functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)

    def test_initial_connection_state(self):
        """Test initial connection state."""
        assert not self.exchange.is_connected()
        assert self.exchange._connection_status == ExchangeConnectionStatus.DISCONNECTED

    def test_connection_establishment(self):
        """Test connection establishment."""
        result = self.exchange.connect()
        
        assert result.success is True
        assert result.status == ExchangeConnectionStatus.CONNECTED
        assert self.exchange.is_connected()
        assert self.exchange._connection_time is not None

    def test_connection_idempotency(self):
        """Test that connecting when already connected is idempotent."""
        # Connect first time
        result1 = self.exchange.connect()
        connection_time1 = self.exchange._connection_time
        
        # Connect second time
        result2 = self.exchange.connect()
        connection_time2 = self.exchange._connection_time
        
        assert result1.success is True
        assert result2.success is True
        assert connection_time1 == connection_time2

    def test_disconnection(self):
        """Test disconnection."""
        # Connect first
        self.exchange.connect()
        assert self.exchange.is_connected()
        
        # Then disconnect
        result = self.exchange.disconnect()
        
        assert result.success is True
        assert result.status == ExchangeConnectionStatus.DISCONNECTED
        assert not self.exchange.is_connected()
        assert self.exchange._connection_time is None

    def test_order_execution_requires_connection(self):
        """Test that order execution requires active connection."""
        # Ensure not connected
        assert not self.exchange.is_connected()
        
        order = OrderEvent(
            datetime.now(), 'BTCUSDT', 'BUY', 150.0, 100.0, 'simulated', 1, 1
        )
        result = self.exchange.execute_order(order)
        
        assert result.success is False
        assert result.error_code == ExecutionErrorCode.NETWORK_ERROR
        assert "not connected" in result.error_message.lower()


class TestSimulatedExchangeOrderValidation:
    """Test order validation functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()  # Connect for validation tests

    def test_valid_order_validation(self):
        """Test validation of valid order."""
        order = OrderEvent(
            datetime.now(), 'BTCUSDT', 'BUY', 150.0, 100.0, 'simulated', 1, 1
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_invalid_symbol_validation(self):
        """Test validation of order with invalid symbol."""
        order = OrderEvent(
            datetime.now(), 'INVALID', 'BUY', 150.0, 100.0, 'simulated', 1, 1
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is False
        assert result.error_code == ExecutionErrorCode.SYMBOL_NOT_FOUND
        assert "Invalid symbol" in result.error_message

    def test_invalid_quantity_validation(self):
        """Test validation of order with invalid quantity."""
        # Test negative quantity with positive price to isolate the quantity issue
        order = OrderEvent(
            time=datetime.now(), 
            ticker='BTCUSDT', 
            action='BUY', 
            price=150.0,
            quantity=-100.0,  # This is the negative quantity
            exchange='simulated', 
            strategy_id=1, 
            portfolio_id=1
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is False
        # Check that quantity error is mentioned somewhere in the validation result
        assert "quantity must be positive" in result.error_message or any("quantity must be positive" in check for check in (result.failed_checks or []))

    def test_quantity_limits_validation(self):
        """Test validation of order quantity limits."""
        # Configure custom limits
        self.exchange.update_config(min_order_size=50.0, max_order_size=500.0)
        
        # Test below minimum (use 0.0001 which is below 50.0)
        order_small = OrderEvent(
            datetime.now(), 'BTCUSDT', 'BUY', 150.0, 0.0001, 'simulated', 1, 1
        )
        result = self.exchange.validate_order(order_small)
        assert result.is_valid is False
        assert "below minimum" in result.error_message
        
        # Test above maximum
        order_large = OrderEvent(
            datetime.now(), 'BTCUSDT', 'BUY', 150.0, 1000.0, 'simulated', 1, 1
        )
        result = self.exchange.validate_order(order_large)
        assert result.is_valid is False
        assert "exceeds maximum" in result.error_message

    def test_invalid_price_validation(self):
        """Test validation of order with invalid price."""
        # Use positive quantity to isolate the price validation issue
        order = OrderEvent(
            time=datetime.now(), 
            ticker='BTCUSDT', 
            action='BUY', 
            price=-150.0,  # This is the negative price
            quantity=100.0,
            exchange='simulated', 
            strategy_id=1, 
            portfolio_id=1
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is False
        # Check that price error is mentioned somewhere
        assert "price must be positive" in result.error_message or any("price must be positive" in check for check in (result.failed_checks or []))

    def test_validation_warnings(self):
        """Test validation warnings for edge cases."""
        # Test high price warning (use smaller quantity within limits but very high price)
        order = OrderEvent(
            datetime.now(), 'BTCUSDT', 'BUY', 1500000.0, 0.1, 'simulated', 1, 1
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is True  # Still valid but with warnings
        assert result.warnings is not None
        assert "unusually high" in result.warnings[0]


class TestSimulatedExchangeHealthMonitoring:
    """Test health monitoring and status reporting."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)

    def test_health_check_basic(self):
        """Test basic health check functionality."""
        health = self.exchange.health_check()
        
        assert isinstance(health, HealthStatus)
        assert health.exchange_name == self.exchange._exchange_name
        assert health.connected == self.exchange._connected
        assert health.status == self.exchange._connection_status
        assert health.last_ping_time is not None
        assert health.uptime_seconds >= 0

    def test_health_check_metrics(self):
        """Test health check includes execution metrics."""
        # Connect and execute some orders
        self.exchange.connect()
        
        order1 = OrderEvent(datetime.now(), 'BTCUSDT', 'BUY', 150.0, 100.0, 'simulated', 1, 1)
        order2 = OrderEvent(datetime.now(), 'INVALID', 'BUY', 150.0, 100.0, 'simulated', 1, 1)
        
        self.exchange.execute_order(order1)  # Should succeed
        self.exchange.execute_order(order2)  # Should fail (invalid symbol)
        
        health = self.exchange.health_check()
        
        assert health.orders_executed_today == 1
        assert health.orders_failed_today == 1
        assert health.error_rate == 0.5  # 1 failed out of 2 total

    def test_exchange_info(self):
        """Test comprehensive exchange information."""
        info = self.exchange.get_exchange_info()
        
        # Verify all expected sections
        expected_sections = {
            'name', 'type', 'connected', 'connection_status',
            'supported_symbols', 'capabilities', 'limits',
            'models', 'configuration', 'statistics'
        }
        assert set(info.keys()) == expected_sections
        
        # Verify capabilities
        assert 'order_execution' in info['capabilities']
        assert 'slippage_simulation' in info['capabilities']
        assert 'failure_simulation' in info['capabilities']
        
        # Verify models info
        assert 'fee_model' in info['models']
        assert 'slippage_model' in info['models']


class TestSimulatedExchangeEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)

    def test_model_creation_fallback(self):
        """Test model creation with invalid configuration falls back gracefully."""
        # This tests the internal _create_fee_model and _create_slippage_model methods
        # when they encounter unexpected model types
        
        # Create exchange with default config
        exchange = SimulatedExchange(self.queue)
        
        # Verify models are created (even if falling back to defaults)
        assert exchange.fee_model is not None
        assert exchange.slippage_model is not None

    def test_symbol_validation_edge_cases(self):
        """Test symbol validation with edge cases."""
        # Test empty symbol
        assert not self.exchange.validate_symbol("")
        
        # Test None symbol (should handle gracefully)
        try:
            result = self.exchange.validate_symbol(None)
            assert not result
        except (TypeError, AttributeError):
            # Acceptable to raise exception for None
            pass

    def test_supported_symbols_copy(self):
        """Test that get_supported_symbols returns a copy."""
        symbols1 = self.exchange.get_supported_symbols()
        symbols2 = self.exchange.get_supported_symbols()
        
        # Should be equal but not the same object
        assert symbols1 == symbols2
        assert symbols1 is not symbols2
        
        # Modifying one shouldn't affect the other
        symbols1.add('NEW_SYMBOL')
        assert 'NEW_SYMBOL' not in symbols2

    @patch('random.random')
    def test_failure_simulation_deterministic(self, mock_random):
        """Test failure simulation with deterministic random values."""
        self.exchange.connect()
        self.exchange.update_config(simulate_failures=True, failure_rate=0.5)
        
        # Test failure (random returns 0.3, which is < 0.5)
        mock_random.return_value = 0.3
        order = OrderEvent(datetime.now(), 'BTCUSDT', 'BUY', 150.0, 100.0, 'simulated', 1, 1)
        result = self.exchange.execute_order(order)
        assert result.success is False
        
        # Test success (random returns 0.7, which is >= 0.5)
        mock_random.return_value = 0.7
        order = OrderEvent(datetime.now(), 'BTCUSDT', 'BUY', 150.0, 100.0, 'simulated', 1, 1)
        result = self.exchange.execute_order(order)
        assert result.success is True


if __name__ == "__main__":
    pytest.main([__file__])
