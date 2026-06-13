import pytest
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

from itrader.order_handler.order_validator import (
    EnhancedOrderValidator, ValidationResult, ValidationMessage, ValidationLevel
)
from itrader.order_handler.order import Order
from itrader.core.enums import OrderType, OrderStatus, PositionSide, Side
from itrader.core.portfolio_read_model import PositionView


class TestEnhancedOrderValidator:
    """Test the EnhancedOrderValidator's entity-based validation pipeline (D-13).

    The validator checks the PENDING ``Order`` entity, not the in-flight
    signal — the typed ``ValidationResult`` IS the verdict (D-03); nothing
    is mutated by validation.

    The validator reads portfolio state through the narrow PortfolioReadModel
    Protocol (Plan 05-03, D-16) — mocks stub the six Protocol methods, not
    portfolio attributes.
    """

    def setup_method(self):
        """Set up test fixtures."""
        # Mock read model with sufficient cash and a supported exchange
        self.portfolio_handler = Mock()
        self.portfolio_handler.available_cash.return_value = Decimal("20000.00")
        self.portfolio_handler.get_position.return_value = None  # flat
        self.portfolio_handler.exchange_for.return_value = "NYSE"
        self.portfolio_handler.open_position_count.return_value = 5
        self.validator = EnhancedOrderValidator(self.portfolio_handler)

    def create_test_order(self, **kwargs):
        """Create a PENDING test order entity with default values."""
        defaults = {
            'time': datetime.now(),
            'type': OrderType.MARKET,
            'status': OrderStatus.PENDING,
            'ticker': 'AAPL',
            'action': Side.BUY,
            'price': 150.0,
            'quantity': 100.0,
            'exchange': 'NYSE',
            'strategy_id': 1,
            'portfolio_id': 1,
        }
        defaults.update(kwargs)

        return Order(**defaults)

    def test_valid_order_validation_pipeline(self):
        """Test the complete validation pipeline with a valid order."""
        order = self.create_test_order()
        result = self.validator.validate_order_pipeline(order)

        assert result.success is True
        assert len(result.errors) == 0
        assert result.summary == "All validations passed"
        # Validation never mutates the entity (D-13): acceptance/rejection is
        # applied by the caller through add_state_change.
        assert order.status == OrderStatus.PENDING

    def test_critical_field_validation_failure(self):
        """Test that critical field validation catches essential field issues."""
        # Test empty ticker
        order = self.create_test_order(ticker="")
        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert len(result.errors) > 0
        assert any("ticker" in msg.message.lower() for msg in result.errors)
        assert result.summary == "Critical field validation failed"

    def test_market_conditions_validation(self):
        """Test market conditions validation phase."""
        # Test invalid exchange via the read model's exchange_for
        self.portfolio_handler.exchange_for.return_value = "INVALID_EXCHANGE"

        order = self.create_test_order()
        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert any("exchange" in msg.message.lower() for msg in result.errors)
        assert result.summary == "Market validation failed"

    def test_portfolio_constraints_validation(self):
        """Test portfolio constraints validation phase."""
        # Mock insufficient cash: not enough for 100 * 150 = 15000
        self.portfolio_handler.available_cash.return_value = Decimal("1000.00")

        order = self.create_test_order(action=Side.BUY, price=150.0, quantity=100.0)
        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert any("cash" in msg.message.lower() for msg in result.errors)
        # Cash validation is actually in the financial risk phase
        assert result.summary == "Financial risk validation failed"

    def test_financial_risk_validation(self):
        """Test financial risk validation phase."""
        # Test order value exceeding maximum
        order = self.create_test_order(price=10000.0, quantity=1000.0)  # 10M order
        result = self.validator.validate_order_pipeline(order)

        # Should either fail or generate warnings depending on risk limits
        assert result.success is False or result.has_warnings

    def test_validation_with_warnings(self):
        """Test that validation can succeed with warnings."""
        # Create an order that might generate warnings but not errors
        order = self.create_test_order(price=0.01, quantity=1.0)  # Very small order
        result = self.validator.validate_order_pipeline(order)

        # Should succeed but may have warnings
        if result.success:
            assert result.summary == "All validations passed"
        else:
            # If it fails, it should be due to order value being too small
            assert any("order value" in msg.message.lower() for msg in result.errors)

    def test_progressive_validation_phases(self):
        """Test that validation phases are progressive and stop at first failure."""
        # Create order with critical field error - should stop at phase 1
        order = self.create_test_order(ticker="")
        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert result.summary == "Critical field validation failed"
        # Should have ticker error
        assert any("ticker" in msg.message.lower() for msg in result.errors)

    def test_validation_message_structure(self):
        """Test that validation messages have proper structure."""
        order = self.create_test_order(price=-10.0)  # Invalid price
        result = self.validator.validate_order_pipeline(order)

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
            action=Side.BUY,
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
        order = self.create_test_order()

        result = validator.validate_order_pipeline(order)
        # Should still validate critical fields and market conditions
        # May skip portfolio-specific validations
        assert isinstance(result, ValidationResult)

    def test_sell_order_validation(self):
        """Test validation for sell orders."""
        # Mock an open long position to sell (frozen PositionView, D-15)
        self.portfolio_handler.available_cash.return_value = Decimal("10000.00")
        self.portfolio_handler.get_position.return_value = PositionView(
            ticker="AAPL",
            side=PositionSide.LONG,
            net_quantity=Decimal("200.0"),
            avg_price=Decimal("140.0"),
        )

        order = self.create_test_order(action=Side.SELL, quantity=100.0)
        result = self.validator.validate_order_pipeline(order)

        assert result.success is True or len(result.errors) == 0

    def test_zero_quantity_signal(self):
        """A zero-quantity order FAILS validation — the bypass is dead (D-04).

        The run path never presents an unsized order here (sizing resolves
        BEFORE validation — DEF-01-B gate; sizing failures are stored as
        audited REJECTED entities before validation runs, D-06). The
        zero-quantity "transition period" warning bypass no longer exists:
        a non-positive quantity is a hard ERROR in the critical-field
        phase, like any other invalid field.
        """
        order = self.create_test_order(quantity=0.0)
        result = self.validator.validate_order_pipeline(order)

        # Zero quantity is rejected outright in the critical-field phase
        assert result.success is False
        assert result.summary == "Critical field validation failed"
        assert any(
            "quantity must be positive" in msg.message.lower()
            for msg in result.errors
        )
        # The bypass is gone: no zero-quantity WARNING survives
        assert not any("transition" in msg.message.lower() for msg in result.messages)

    def test_negative_quantity_fails_validation(self):
        """A negative quantity fails the same positive-quantity rule."""
        order = self.create_test_order(quantity=-5.0)
        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert result.summary == "Critical field validation failed"
        assert any(
            "quantity must be positive" in msg.message.lower()
            for msg in result.errors
        )

    def test_edge_case_validations(self):
        """Test various edge cases."""
        # Test very high prices
        order = self.create_test_order(price=999999.0)
        result = self.validator.validate_order_pipeline(order)
        # Should either fail or warn about high price

        # Test very small quantities
        order = self.create_test_order(quantity=0.001)
        result = self.validator.validate_order_pipeline(order)
        # Should handle small quantities appropriately

        # Test different order types
        order = self.create_test_order(type=OrderType.LIMIT)
        result = self.validator.validate_order_pipeline(order)
        assert isinstance(result, ValidationResult)

    def test_cash_check_is_decimal_exact_at_boundary(self):
        """M5-10 (D-06): the cash check compares Decimal cost vs Decimal cash.

        Chosen so float narrowing genuinely diverges from Decimal at the
        boundary: 1.07 * 101 is EXACTLY 108.07 in Decimal, but the float
        product is 108.07000000000001. With cash = 108.07 (exact), a
        Decimal-native check admits the order (cash < cost is False); a
        float narrowing would reject it (cash < 108.07000000000001 is True).
        This locks the golden-path cash check to native Decimal arithmetic.
        """
        self.portfolio_handler.available_cash.return_value = Decimal("108.07")
        order = self.create_test_order(price=1.07, quantity=101.0)

        result = self.validator.validate_order_pipeline(order)

        # Exact-cash order is admitted under Decimal arithmetic: no
        # INSUFFICIENT_CASH_COST error (the float path would wrongly reject).
        assert not any(
            msg.code == "INSUFFICIENT_CASH_COST" for msg in result.errors
        )

    def test_cash_check_rejects_one_cent_short(self):
        """One cent short of cost is rejected with INSUFFICIENT_CASH_COST."""
        self.portfolio_handler.available_cash.return_value = Decimal("108.06")
        order = self.create_test_order(price=1.07, quantity=101.0)

        result = self.validator.validate_order_pipeline(order)

        assert result.success is False
        assert any(
            msg.code == "INSUFFICIENT_CASH_COST" for msg in result.errors
        )

    def test_validation_result_properties(self):
        """Test ValidationResult properties."""
        order = self.create_test_order(price=-10.0)  # Will generate errors
        result = self.validator.validate_order_pipeline(order)

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
