import pytest
from datetime import datetime
from unittest.mock import Mock

from itrader.order_handler.order_validator import (
    EnhancedOrderValidator, ValidationResult, ValidationMessage, ValidationLevel
)
from itrader.order_handler.order import Order, OrderType, OrderStatus
from itrader.events_handler.event import SignalEvent


class TestEnhancedOrderValidator:
    """Test the EnhancedOrderValidator with its progressive validation pipeline."""

    def setup_method(self):
        """Set up test fixtures."""
        self.portfolio_handler = Mock()
        self.validator = EnhancedOrderValidator(self.portfolio_handler)
        
        # Mock portfolio with sufficient cash and proper attributes
        mock_portfolio = Mock()
        mock_portfolio.cash = 20000.0
        mock_portfolio.positions = {}
        mock_portfolio.exchange = "NYSE"  # Set a supported exchange
        mock_portfolio.max_positions = 50
        mock_portfolio.n_open_positions = 5  # Current open positions
        mock_portfolio.max_position_size = 10000.0
        mock_portfolio.max_portfolio_risk = 0.2
        mock_portfolio.total_equity = 50000.0  # Total portfolio value
        mock_portfolio.total_value = 50000.0   # Alternative name
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio

    def create_test_signal(self, **kwargs):
        """Create a test signal with default values."""
        defaults = {
            'time': datetime.now(),
            'order_type': 'MARKET',
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'stop_loss': 0.0,
            'take_profit': 0.0,
            'strategy_id': 1,
            'portfolio_id': 1,
            'strategy_setting': {}
        }
        defaults.update(kwargs)
        
        signal = SignalEvent(**defaults)
        return signal

    def test_valid_signal_validation_pipeline(self):
        """Test the complete validation pipeline with a valid signal."""
        signal = self.create_test_signal()
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is True
        assert len(result.errors) == 0
        assert signal.verified is True
        assert result.summary == "All validations passed"

    def test_critical_field_validation_failure(self):
        """Test that critical field validation catches essential field issues."""
        # Test empty ticker
        signal = self.create_test_signal(ticker="")
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is False
        assert len(result.errors) > 0
        assert signal.verified is False
        assert any("ticker" in msg.message.lower() for msg in result.errors)
        assert result.summary == "Critical field validation failed"

    def test_market_conditions_validation(self):
        """Test market conditions validation phase."""
        # Test invalid exchange by mocking portfolio with unsupported exchange
        mock_portfolio = Mock()
        mock_portfolio.cash = 20000.0
        mock_portfolio.positions = {}
        mock_portfolio.exchange = "INVALID_EXCHANGE"
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        signal = self.create_test_signal()
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is False
        assert any("exchange" in msg.message.lower() for msg in result.errors)
        assert result.summary == "Market validation failed"

    def test_portfolio_constraints_validation(self):
        """Test portfolio constraints validation phase."""
        # Mock insufficient cash
        mock_portfolio = Mock()
        mock_portfolio.cash = 1000.0  # Not enough for 100 * 150 = 15000
        mock_portfolio.positions = {}
        mock_portfolio.exchange = "NYSE"
        mock_portfolio.max_positions = 50
        mock_portfolio.n_open_positions = 5
        mock_portfolio.max_position_size = 10000.0
        mock_portfolio.max_portfolio_risk = 0.2
        mock_portfolio.total_equity = 50000.0
        mock_portfolio.total_value = 50000.0
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        signal = self.create_test_signal(action="BUY", price=150.0, quantity=100.0)
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is False
        assert any("cash" in msg.message.lower() for msg in result.errors)
        # Cash validation is actually in the financial risk phase
        assert result.summary == "Financial risk validation failed"

    def test_financial_risk_validation(self):
        """Test financial risk validation phase."""
        # Test order value exceeding maximum
        signal = self.create_test_signal(price=10000.0, quantity=1000.0)  # 10M order
        result = self.validator.validate_signal_pipeline(signal)
        
        # Should either fail or generate warnings depending on risk limits
        assert result.success is False or result.has_warnings

    def test_validation_with_warnings(self):
        """Test that validation can succeed with warnings."""
        # Create a signal that might generate warnings but not errors
        signal = self.create_test_signal(price=0.01, quantity=1.0)  # Very small order
        result = self.validator.validate_signal_pipeline(signal)
        
        # Should succeed but may have warnings
        if result.success:
            assert result.summary == "All validations passed"
        else:
            # If it fails, it should be due to order value being too small
            assert any("order value" in msg.message.lower() for msg in result.errors)

    def test_progressive_validation_phases(self):
        """Test that validation phases are progressive and stop at first failure."""
        # Create signal with critical field error - should stop at phase 1
        signal = self.create_test_signal(ticker="")
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is False
        assert result.summary == "Critical field validation failed"
        # Should have ticker error
        assert any("ticker" in msg.message.lower() for msg in result.errors)

    def test_validation_message_structure(self):
        """Test that validation messages have proper structure."""
        signal = self.create_test_signal(price=-10.0)  # Invalid price
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is False
        assert len(result.messages) > 0
        
        # Check message structure
        for msg in result.messages:
            assert isinstance(msg, ValidationMessage)
            assert hasattr(msg, 'level')
            assert hasattr(msg, 'message')
            assert msg.level in [ValidationLevel.ERROR, ValidationLevel.WARNING, ValidationLevel.VALID]
            assert isinstance(msg.message, str)
            assert len(msg.message) > 0

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
        assert len([msg for msg in messages if msg.level == ValidationLevel.ERROR]) == 0
        
        # Invalid modification - new quantity less than filled
        messages = self.validator.validate_order_modification(order, new_quantity=20.0)
        errors = [msg for msg in messages if msg.level == ValidationLevel.ERROR]
        assert len(errors) > 0
        assert any("filled quantity" in msg.message.lower() for msg in errors)

    def test_validation_without_portfolio_handler(self):
        """Test validation when no portfolio handler is provided."""
        validator = EnhancedOrderValidator(portfolio_handler=None)
        signal = self.create_test_signal()
        
        result = validator.validate_signal_pipeline(signal)
        # Should still validate critical fields and market conditions
        # May skip portfolio-specific validations
        assert isinstance(result, ValidationResult)

    def test_sell_signal_validation(self):
        """Test validation for sell signals."""
        # Mock a position to sell
        mock_portfolio = Mock()
        mock_portfolio.cash = 10000.0
        mock_portfolio.positions = {'AAPL': Mock(quantity=200.0)}
        mock_portfolio.exchange = "NYSE"  # Add exchange attribute
        mock_portfolio.max_positions = 50
        mock_portfolio.n_open_positions = 5
        mock_portfolio.max_position_size = 10000.0
        mock_portfolio.max_portfolio_risk = 0.2
        mock_portfolio.total_equity = 50000.0
        mock_portfolio.total_value = 50000.0
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        signal = self.create_test_signal(action="SELL", quantity=100.0)
        result = self.validator.validate_signal_pipeline(signal)
        
        assert result.success is True or len(result.errors) == 0

    def test_zero_quantity_signal(self):
        """Test validation of signal with zero quantity."""
        signal = self.create_test_signal(quantity=0.0)
        result = self.validator.validate_signal_pipeline(signal)
        
        # Zero quantity should typically fail validation
        assert result.success is False
        assert any("quantity" in msg.message.lower() for msg in result.errors)

    def test_edge_case_validations(self):
        """Test various edge cases."""
        # Test very high prices
        signal = self.create_test_signal(price=999999.0)
        result = self.validator.validate_signal_pipeline(signal)
        # Should either fail or warn about high price
        
        # Test very small quantities
        signal = self.create_test_signal(quantity=0.001)
        result = self.validator.validate_signal_pipeline(signal)
        # Should handle small quantities appropriately
        
        # Test different order types
        signal = self.create_test_signal(order_type="LIMIT")
        result = self.validator.validate_signal_pipeline(signal)
        assert isinstance(result, ValidationResult)

    def test_validation_result_properties(self):
        """Test ValidationResult properties."""
        signal = self.create_test_signal(price=-10.0)  # Will generate errors
        result = self.validator.validate_signal_pipeline(signal)
        
        # Test properties
        assert hasattr(result, 'success')
        assert hasattr(result, 'messages')
        assert hasattr(result, 'summary')
        assert hasattr(result, 'has_warnings')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'warnings')
        
        # Test that errors property returns only error messages
        assert all(msg.level == ValidationLevel.ERROR for msg in result.errors)
        
        # Test that warnings property returns only warning messages
        assert all(msg.level == ValidationLevel.WARNING for msg in result.warnings)
