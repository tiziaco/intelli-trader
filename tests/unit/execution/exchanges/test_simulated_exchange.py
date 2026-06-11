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
from itrader.events_handler.events import OrderEvent, FillEvent
from itrader.config import ExchangeConfig, get_exchange_preset
from itrader.config.exchange import (
    FeeModelConfig, SlippageModelConfig, ExchangeLimits, FailureSimulation,
    FeeModelType, SlippageModelType,
)
from itrader.core.enums.execution import (
    ExecutionErrorCode, ExchangeConnectionStatus
)
from itrader.execution_handler.result_objects import ConnectionResult, HealthStatus, OrderPreflightResult
from itrader.core.enums import OrderType, OrderCommand, FillStatus, Side


def drain_fills(queue: Queue) -> list[FillEvent]:
    """Drain and return every FillEvent currently on the queue (D-21:
    FillEvents are the only execution output, so tests assert on them)."""
    fills = []
    while not queue.empty():
        fills.append(queue.get_nowait())
    return fills


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

        # Test fee model functionality (D-12: Decimal-native contract)
        fee = exchange.fee_model.calculate_fee(
            Decimal("100"), Decimal("50.0"), 'buy', 'market')
        assert isinstance(fee, Decimal)
        assert fee >= 0

    def test_no_lock_single_writer_contract(self):
        """D-19: the config lock is gone — single-writer contract.

        Regression-locks the lock deletion: configuration updates happen on
        the engine thread; queue.Queue is the thread boundary.
        """
        exchange = SimulatedExchange(self.queue)

        assert not hasattr(exchange, '_lock')


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
        assert self.exchange.get_supported_symbols() == new_symbols

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

    def test_update_config_sequential_single_writer(self):
        """D-19: config updates run on the engine thread (single-writer).

        The former concurrent-update test exercised the deleted config lock;
        sequential updates are the sanctioned pattern now.
        """
        for i in range(10):
            self.exchange.update_config(failure_rate=i * 0.01)

        # Verify exchange is still in valid state
        config_dict = self.exchange.get_config_dict()
        assert isinstance(config_dict['failure_rate'], float)
        assert config_dict['failure_rate'] == pytest.approx(0.09)


class TestSimulatedExchangeOrderExecution:
    """Next-bar-open execution (D-01/D-13): NEW orders rest, fills come from bars."""

    def setup_method(self):
        """Set up test fixtures."""
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()  # Connect for successful execution

    def create_test_order(self, **kwargs) -> OrderEvent:
        """Create a test order event with default values."""
        defaults = {
            'time': datetime(2024, 1, 1),
            'ticker': 'BTCUSDT',  # Use a symbol that's in the default supported symbols
            'action': Side.BUY,
            'quantity': 100.0,
            'price': 150.0,
            'exchange': 'simulated',
            'strategy_id': 1,
            'portfolio_id': 1,
            'order_type': OrderType.MARKET,
            'order_id': 1,  # D-12: required linkage id
        }
        defaults.update(kwargs)
        return OrderEvent(**defaults)

    def test_market_order_rests_then_fills_at_next_bar_open(self, make_bar):
        """A market order decided at T rests in the book and fills at the
        NEXT bar's open, with FillEvent.time == the bar's event time
        (D-01/D-13 — Decimal equality, no same-drain fill)."""
        order = self.create_test_order()
        assert self.exchange.on_order(order) is None    # D-21: no sync result

        # No fill on the same drain — the order rests in the book.
        assert drain_fills(self.queue) == []
        assert self.exchange.matching_engine.has_order(order.order_id)

        bar = make_bar(open_=152.5, high=155, low=149, close=154,
                       time=datetime(2024, 1, 2))
        self.exchange.on_market_data(bar)

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        fill = fills[0]
        assert isinstance(fill, FillEvent)
        assert fill.status is FillStatus.EXECUTED
        assert fill.price == Decimal("152.5")           # next bar's open, exact
        assert fill.time == bar.time                    # stamped T+1tf
        assert fill.quantity == order.quantity
        assert fill.commission >= 0
        # D-12 linkage: fill_id/order_id audit chain
        assert fill.fill_id is not None
        assert fill.order_id == order.order_id

    def test_order_decided_on_last_bar_never_fills(self):
        """Last-bar edge (bar-timing contract rule 7): no next bar ever
        arrives, so the order produces NO fill and stays in the book."""
        order = self.create_test_order()
        self.exchange.on_order(order)
        # dataset exhausted — on_market_data is never called again
        assert drain_fills(self.queue) == []
        assert self.exchange.matching_engine.has_order(order.order_id)

    def test_order_execution_with_slippage(self, make_bar):
        """Slippage applies to the next-bar-open fill price."""
        # Configure a COMPLETE linear slippage model. The default preset leaves
        # max_slippage_pct=Decimal("0") (an unused knob while model_type=NONE); a
        # 0 cap clamps ALL slippage to zero, so flipping only the model type +
        # base_slippage_pct yields NO slippage. Set the cap (and size-impact) too.
        # base_slippage_pct=0 zeros the RNG noise term (uniform(-0,0)=0), leaving a
        # deterministic, hand-derivable size-impact slippage (mirrors COST-04).
        self.exchange.config.slippage_model.size_impact_factor = Decimal("0.0001")
        self.exchange.config.slippage_model.max_slippage_pct = Decimal("50")
        self.exchange.update_config(
            slippage_model_type=SlippageModelType.LINEAR,
            base_slippage_pct=Decimal("0"),
        )

        order = self.create_test_order(price=100.0)
        self.exchange.on_order(order)
        self.exchange.on_market_data(make_bar(open_=100, high=102, low=99, close=101))

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        assert fills[0].status is FillStatus.EXECUTED
        # Price should be different from the bar open due to slippage
        assert fills[0].price != Decimal("100")

    def test_order_execution_with_fees(self, make_bar):
        """The next-bar-open fill carries fees computed on the fill price."""
        # Configure for percentage fees
        self.exchange.update_config(
            fee_model_type=FeeModelType.PERCENT,
            fee_rate=0.001
        )

        order = self.create_test_order(quantity=100.0, price=150.0)
        self.exchange.on_order(order)
        self.exchange.on_market_data(make_bar(open_=150, high=152, low=149, close=151))

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.status is FillStatus.EXECUTED
        # Commission should be 0.001 * 100 * 150 (open) = 15.0
        assert fill.commission == pytest.approx(float(
            Decimal('0.001') * Decimal('100.0') * Decimal('150.0')))

    def test_order_admission_failure_simulation(self):
        """Failure simulation fires at admission time and emits REFUSED."""
        # Enable failure simulation with high rate
        self.exchange.update_config(simulate_failures=True, failure_rate=1.0)

        order = self.create_test_order()
        self.exchange.on_order(order)

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        assert fills[0].status is FillStatus.REFUSED
        assert fills[0].order_id == order.order_id
        # Failure scenario recorded for monitoring
        assert self.exchange._last_error is not None
        # The rejected order never rests in the book.
        assert not self.exchange.matching_engine.has_order(order.order_id)

    def test_order_validation_failure(self):
        """Validation failure at admission time emits REFUSED."""
        # Create order with invalid symbol
        order = self.create_test_order(ticker='INVALID')
        self.exchange.on_order(order)

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        assert fills[0].status is FillStatus.REFUSED
        assert "Invalid symbol" in self.exchange._last_error

    def test_order_execution_metrics_tracking(self, make_bar):
        """Execution metrics: executed counts at fill time, failed at admission."""
        initial_executed = self.exchange._orders_executed
        initial_failed = self.exchange._orders_failed

        # Admit a market order; it fills on the next bar.
        order = self.create_test_order()
        self.exchange.on_order(order)
        self.exchange.on_market_data(make_bar(open_=150, high=152, low=149, close=151))
        assert drain_fills(self.queue)[0].status is FillStatus.EXECUTED
        assert self.exchange._orders_executed == initial_executed + 1

        # Failing order (invalid symbol) is rejected at admission.
        order_fail = self.create_test_order(ticker='INVALID', order_id=2)
        self.exchange.on_order(order_fail)
        assert drain_fills(self.queue)[0].status is FillStatus.REFUSED
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

    def test_order_admission_requires_connection(self):
        """Order admission requires an active connection — REFUSED otherwise."""
        # Ensure not connected
        assert not self.exchange.is_connected()

        order = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=150.0, quantity=100.0, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        self.exchange.on_order(order)

        fills = drain_fills(self.queue)
        assert len(fills) == 1
        assert fills[0].status is FillStatus.REFUSED
        assert "not connected" in self.exchange._last_error.lower()
        assert not self.exchange.matching_engine.has_order(order.order_id)


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
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=150.0, quantity=100.0, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        result = self.exchange.validate_order(order)

        # OQ3 rename: the execution-domain preflight DTO, distinct from
        # the order-domain order_validator.ValidationResult.
        assert isinstance(result, OrderPreflightResult)
        assert result.is_valid is True
        assert result.error_code is None
        assert result.error_message is None

    def test_preflight_result_is_frozen(self):
        """T-05-09: surviving DTOs are frozen — no post-init mutation."""
        import dataclasses
        order = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=150.0, quantity=100.0, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        result = self.exchange.validate_order(order)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.is_valid = False

        health = self.exchange.health_check()
        with pytest.raises(dataclasses.FrozenInstanceError):
            health.connected = False

        conn = self.exchange.connect()
        with pytest.raises(dataclasses.FrozenInstanceError):
            conn.success = False

    def test_invalid_symbol_validation(self):
        """Test validation of order with invalid symbol."""
        order = OrderEvent(
            time=datetime.now(), ticker='INVALID', action=Side.BUY,
            price=150.0, quantity=100.0, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
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
            action=Side.BUY,
            price=150.0,
            quantity=-100.0,  # This is the negative quantity
            exchange='simulated',
            strategy_id=1,
            portfolio_id=1,
            order_type=OrderType.MARKET,
            order_id=1,
        )
        result = self.exchange.validate_order(order)

        assert result.is_valid is False
        # Check that quantity error is mentioned somewhere in the validation result
        assert "quantity must be positive" in result.error_message or any("quantity must be positive" in check for check in (result.failed_checks or []))
        # WR-06: a non-positive quantity is an INVALID_ORDER, not a size bound.
        assert result.error_code == ExecutionErrorCode.INVALID_ORDER

    def test_non_positive_quantity_classified_invalid_order(self):
        """WR-06: quantity <= 0 maps to INVALID_ORDER, not ORDER_SIZE_TOO_LARGE.

        Pins the structured error_code for the most basic quantity-failure case.
        Before the WR-06 fix, `_classify` fell through to ORDER_SIZE_TOO_LARGE for
        any "quantity" check lacking "below minimum" — so a zero/negative quantity
        ("must be positive") was reported as too-large, which is semantically
        backwards. Covers both zero and negative quantities.
        """
        for bad_qty in (0.0, -100.0):
            order = OrderEvent(
                time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
                price=150.0, quantity=bad_qty, exchange='simulated',
                strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
            )
            result = self.exchange.validate_order(order)
            assert result.is_valid is False
            assert result.error_code == ExecutionErrorCode.INVALID_ORDER, (
                f"quantity={bad_qty} should classify as INVALID_ORDER, "
                f"got {result.error_code}"
            )

    def test_quantity_limits_validation(self):
        """Test validation of order quantity limits."""
        # Configure custom limits
        self.exchange.update_config(min_order_size=50.0, max_order_size=500.0)
        
        # Test below minimum (use 0.0001 which is below 50.0)
        order_small = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=150.0, quantity=0.0001, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        result = self.exchange.validate_order(order_small)
        assert result.is_valid is False
        assert "below minimum" in result.error_message

        # Test above maximum
        order_large = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=150.0, quantity=1000.0, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        result = self.exchange.validate_order(order_large)
        assert result.is_valid is False
        assert "exceeds maximum" in result.error_message

    def test_below_minimum_quantity_refused_decimal(self):
        """D-08: below-minimum REFUSED branch as genuine Decimal-vs-Decimal.

        Closes the symmetric `event.quantity < _min_order_size` branch that no
        E2E leaf exercises today (release_refused covers only the > _max branch).

        This asserts CORRECT REFUSED behavior on the < _min branch — NOT that a
        TypeError is gone (per D-07 there was none: Decimal-vs-float COMPARISON
        works in Py3; only arithmetic raises, and there is none on these fields).

        Limits are configured with Decimal LITERALS, not floats: ExchangeLimits
        has extra="forbid" but NO validate_assignment=True, so update_config's
        setattr BYPASSES the field validator — a float literal would be stored AS
        a float and the re-derived _min_order_size would carry that float, breaking
        the DEC-02 Decimal-carry assertion below. Decimal literals keep the field
        genuinely Decimal AND make the comparison Decimal-vs-Decimal.
        """
        self.exchange.update_config(
            min_order_size=Decimal("50"), max_order_size=Decimal("500")
        )

        # DEC-02 regression lock: _min_order_size is carried as Decimal end-to-end.
        # Would have FAILED under the old float() wraps; would also fail if limits
        # were updated with float literals (setattr-bypass). With Task 1's fix +
        # the Decimal-literal update above, it passes.
        assert isinstance(self.exchange._min_order_size, Decimal)

        # Decimal below-minimum quantity: Decimal("0.0001") < Decimal("50") -> True
        # (Decimal-vs-Decimal) -> REFUSED.
        order = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=Decimal("150"), quantity=Decimal("0.0001"), exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
        )
        result = self.exchange.validate_order(order)
        assert result.is_valid is False
        assert "below minimum" in result.error_message

    def test_invalid_price_validation(self):
        """Test validation of order with invalid price."""
        # Use positive quantity to isolate the price validation issue
        order = OrderEvent(
            time=datetime.now(),
            ticker='BTCUSDT',
            action=Side.BUY,
            price=-150.0,  # This is the negative price
            quantity=100.0,
            exchange='simulated',
            strategy_id=1,
            portfolio_id=1,
            order_type=OrderType.MARKET,
            order_id=1,
        )
        result = self.exchange.validate_order(order)
        
        assert result.is_valid is False
        # Check that price error is mentioned somewhere
        assert "price must be positive" in result.error_message or any("price must be positive" in check for check in (result.failed_checks or []))

    def test_validation_warnings(self):
        """Test validation warnings for edge cases."""
        # Test high price warning (use smaller quantity within limits but very high price)
        order = OrderEvent(
            time=datetime.now(), ticker='BTCUSDT', action=Side.BUY,
            price=1500000.0, quantity=0.1, exchange='simulated',
            strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1,
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

    def test_health_check_metrics(self, make_bar):
        """Test health check includes execution metrics."""
        # Connect, admit a market order (fills on the next bar) and reject one.
        self.exchange.connect()

        order1 = OrderEvent(time=datetime(2024, 1, 1), ticker='BTCUSDT', action=Side.BUY, price=150.0, quantity=100.0, exchange='simulated', strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1)
        order2 = OrderEvent(time=datetime(2024, 1, 1), ticker='INVALID', action=Side.BUY, price=150.0, quantity=100.0, exchange='simulated', strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=2)

        self.exchange.on_order(order1)   # rests, fills on the next bar
        self.exchange.on_market_data(make_bar(open_=150, high=152, low=149, close=151))
        self.exchange.on_order(order2)   # fails admission (invalid symbol)

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

    def test_failure_simulation_deterministic(self):
        """Test failure simulation with deterministic random values.

        D-11: the exchange now draws from an injected ``random.Random`` instance
        (``self._rng``), not the global ``random`` module, so patch the instance's
        bound ``random`` method to control the draw. The simulation fires at
        ADMISSION time (on_order) — a failed draw emits REFUSED, a passing
        draw lets the order rest in the book (D-13: no immediate fill).
        """
        self.exchange.connect()
        self.exchange.update_config(simulate_failures=True, failure_rate=0.5)

        # Test failure (random returns 0.3, which is < 0.5)
        with patch.object(self.exchange._rng, 'random', return_value=0.3):
            order = OrderEvent(time=datetime(2024, 1, 1), ticker='BTCUSDT', action=Side.BUY, price=150.0, quantity=100.0, exchange='simulated', strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=1)
            self.exchange.on_order(order)
            fills = drain_fills(self.queue)
            assert len(fills) == 1
            assert fills[0].status is FillStatus.REFUSED
            assert not self.exchange.matching_engine.has_order(1)

        # Test success (random returns 0.7, which is >= 0.5): the order is
        # admitted and RESTS — no fill until a bar arrives.
        with patch.object(self.exchange._rng, 'random', return_value=0.7):
            order = OrderEvent(time=datetime(2024, 1, 1), ticker='BTCUSDT', action=Side.BUY, price=150.0, quantity=100.0, exchange='simulated', strategy_id=1, portfolio_id=1, order_type=OrderType.MARKET, order_id=2)
            self.exchange.on_order(order)
            assert drain_fills(self.queue) == []
            assert self.exchange.matching_engine.has_order(2)


class TestDecimalFillBoundary:
    """D-12: the fill path is Decimal end-to-end — no float boundary remains."""

    def setup_method(self):
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()
        self.exchange.update_config(supported_symbols={"BTCUSDT"})

    def _order(self, **kwargs) -> OrderEvent:
        defaults = {
            'time': datetime(2024, 1, 1), 'ticker': 'BTCUSDT', 'action': Side.BUY,
            'quantity': Decimal("100.0"), 'price': Decimal("150.0"),
            'exchange': 'simulated', 'strategy_id': 1, 'portfolio_id': 1,
            'order_type': OrderType.MARKET, 'order_id': 1,
        }
        defaults.update(kwargs)
        return OrderEvent(**defaults)

    def test_resting_stop_with_decimal_price_fills_without_type_error(self):
        """A Decimal-priced resting stop triggers and fills — no Decimal x float
        TypeError on the hot fill path (T-05-19); FillEvent.price is Decimal."""
        from itrader.core.money import to_money
        from itrader.core.bar import Bar
        from itrader.events_handler.events import BarEvent
        stop = self._order(order_type=OrderType.STOP, action=Side.SELL,
                           price=Decimal("30.0"), order_id=5)
        self.exchange.on_order(stop)
        t = datetime(2024, 1, 1)
        bars = {"BTCUSDT": Bar(
            time=t, open=Decimal("35.0"), high=Decimal("36.0"),
            low=Decimal("20.0"), close=Decimal("25.0"), volume=Decimal("1"))}
        self.exchange.on_market_data(BarEvent(time=t, bars=bars))
        fills = drain_fills(self.queue)
        assert len(fills) == 1
        assert fills[0].status is FillStatus.EXECUTED
        assert isinstance(fills[0].price, Decimal)
        # zero slippage on the default preset: fill at the stop, via to_money
        assert fills[0].price == to_money(30.0)
        assert isinstance(fills[0].quantity, Decimal)

    def test_slippage_fill_price_is_pure_decimal_product(self, make_bar):
        """D-12: slippage math is Decimal end-to-end — executed_price is the
        exact Decimal product fill_price * slippage_factor (no float leg).
        The fill price is the NEXT bar's open (D-01/D-13)."""
        with patch.object(self.exchange.slippage_model, 'calculate_slippage_factor',
                          return_value=Decimal("1.005")):
            self.exchange.on_order(self._order(price=Decimal("100.0")))
            self.exchange.on_market_data(
                make_bar(open_=100, high=102, low=99, close=101))
        fills = drain_fills(self.queue)
        assert len(fills) == 1
        fill = fills[0]
        assert fill.status is FillStatus.EXECUTED
        assert isinstance(fill.price, Decimal)
        assert fill.price == Decimal("100") * Decimal("1.005")

    def test_executed_fill_commission_is_decimal(self, make_bar):
        self.exchange.update_config(fee_model_type=FeeModelType.PERCENT, fee_rate=0.001)
        self.exchange.on_order(self._order())
        self.exchange.on_market_data(make_bar(open_=150, high=152, low=149, close=151))
        fills = drain_fills(self.queue)
        assert isinstance(fills[0].commission, Decimal)
        assert fills[0].commission == Decimal('0.001') * Decimal('100.0') * Decimal('150')

    def test_refused_fill_carries_decimal_zero_commission(self):
        order = self._order(ticker='INVALID')
        self.exchange.on_order(order)
        fills = drain_fills(self.queue)
        assert fills[0].status is FillStatus.REFUSED
        assert isinstance(fills[0].commission, Decimal)
        assert fills[0].commission == Decimal("0")
        # REFUSED carries the order's own (Decimal) price/quantity untouched.
        assert fills[0].price == order.price
        assert fills[0].quantity == order.quantity


class _RoutingHarness:
    """Connected SimulatedExchange restricted to BTCUSDT, with event factories."""

    def __init__(self):
        self.queue = Queue()
        self.exchange = SimulatedExchange(self.queue)
        self.exchange.connect()
        # Ensure the symbol validates on the default preset used by tests.
        self.exchange.update_config(supported_symbols={"BTCUSDT"})

    def oe(self, order_type, action="BUY", price=40.0, order_id=1, command=None, parent_order_id=None):
        # D-12: order events carry Decimal money — enter via Decimal(str(x)).
        return OrderEvent(
            time=datetime(2024, 1, 1), ticker="BTCUSDT",
            action=Side(action), price=Decimal(str(price)), quantity=Decimal("1.0"),
            exchange="default",
            strategy_id=1, portfolio_id=1, order_type=order_type, order_id=order_id,
            parent_order_id=parent_order_id,
            command=command or OrderCommand.NEW,
        )

    def bar(self, open_, high, low, close):
        from itrader.core.bar import Bar
        from itrader.events_handler.events import BarEvent
        t = datetime(2024, 1, 1)
        bars = {
            "BTCUSDT": Bar(
                time=t, open=Decimal(str(open_)), high=Decimal(str(high)),
                low=Decimal(str(low)), close=Decimal(str(close)), volume=Decimal("1"),
            )
        }
        return BarEvent(time=t, bars=bars)


@pytest.fixture
def routing():
    h = _RoutingHarness()
    yield h
    while not h.queue.empty():
        h.queue.get_nowait()


def test_new_market_order_rests_then_fills_at_next_open(routing):
    """D-01/D-13: a NEW market order rests — the fill comes from the next
    bar at the bar's open, stamped with the bar's event time."""
    routing.exchange.on_order(routing.oe(OrderType.MARKET, order_id=1))
    assert routing.queue.qsize() == 0                  # no same-drain fill
    assert routing.exchange.matching_engine.has_order(1)

    bar = routing.bar(open_=41.5, high=45, low=40, close=44)
    routing.exchange.on_market_data(bar)
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.EXECUTED
    assert fills[0].price == Decimal("41.5")           # the bar's open, exact
    assert fills[0].time == bar.time                   # T+1tf fill stamp


def test_same_bar_parent_market_fill_and_child_stop_oco(routing):
    """Same-bar bracket rule (Open Question 1): parent market fills at the
    open, the SL child triggers against the SAME bar's low, the TP sibling
    is OCO-cancelled — all stamped with the bar's event time."""
    parent = routing.oe(OrderType.MARKET, action="BUY", price=100.0, order_id=1)
    sl = routing.oe(OrderType.STOP, action="SELL", price=95.0, order_id=2,
                    parent_order_id=1)
    tp = routing.oe(OrderType.LIMIT, action="SELL", price=110.0, order_id=3,
                    parent_order_id=1)
    for order in (parent, sl, tp):
        routing.exchange.on_order(order)
    assert routing.queue.qsize() == 0                  # everything rests

    bar = routing.bar(open_=100, high=105, low=94, close=96)
    routing.exchange.on_market_data(bar)
    events = [routing.queue.get() for _ in range(routing.queue.qsize())]
    by_id = {e.order_id: e for e in events}
    assert by_id[1].status is FillStatus.EXECUTED      # parent entry at open
    assert by_id[1].price == Decimal("100")
    assert by_id[2].status is FillStatus.EXECUTED      # SL vs same bar's low
    assert by_id[2].price == Decimal("95")
    assert by_id[3].status is FillStatus.CANCELLED     # TP OCO-cancelled
    # Parent fill is emitted BEFORE the child fill within the bar.
    executed_ids = [e.order_id for e in events if e.status is FillStatus.EXECUTED]
    assert executed_ids == [1, 2]
    assert all(e.time == bar.time for e in events)


def test_new_stop_order_rests_no_fill(routing):
    routing.exchange.on_order(routing.oe(OrderType.STOP, action="SELL", price=30.0, order_id=2))
    assert routing.queue.qsize() == 0
    assert routing.exchange.matching_engine.has_order(2)


def test_cancel_command_removes_and_emits_cancelled(routing):
    routing.exchange.on_order(routing.oe(OrderType.STOP, action="SELL", price=30.0, order_id=3))
    routing.exchange.on_order(
        routing.oe(OrderType.STOP, action="SELL", price=30.0, order_id=3, command=OrderCommand.CANCEL)
    )
    assert not routing.exchange.matching_engine.has_order(3)
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.CANCELLED
    assert fills[0].order_id == 3


def test_on_market_data_fills_resting_stop(routing):
    routing.exchange.on_order(routing.oe(OrderType.STOP, action="SELL", price=30.0, order_id=5))
    routing.exchange.on_market_data(routing.bar(open_=35, high=36, low=20, close=25))
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.EXECUTED
    assert fills[0].order_id == 5


def test_on_market_data_emits_oco_cancel(routing):
    routing.exchange.on_order(routing.oe(OrderType.STOP, "SELL", 30.0, order_id=6, parent_order_id=100))
    routing.exchange.on_order(routing.oe(OrderType.LIMIT, "SELL", 55.0, order_id=7, parent_order_id=100))
    routing.exchange.on_market_data(routing.bar(open_=50, high=60, low=40, close=58))  # TP fills
    events = [routing.queue.get() for _ in range(routing.queue.qsize())]
    statuses = {e.order_id: e.status for e in events}
    assert statuses[7] is FillStatus.EXECUTED
    assert statuses[6] is FillStatus.CANCELLED


def test_rejected_market_order_emits_refused_fill(routing):
    # 'ETHUSDT' is not in supported_symbols (only BTCUSDT) -> validation reject.
    # sanity: a BTCUSDT market order is admitted and rests (no fill event).
    routing.exchange.on_order(routing.oe(OrderType.MARKET, order_id=99, command=OrderCommand.NEW))
    assert routing.queue.qsize() == 0
    assert routing.exchange.matching_engine.has_order(99)
    # now send an unsupported-symbol order directly.
    bad = OrderEvent(
        time=datetime(2024, 1, 1), ticker="ETHUSDT",
        action=Side.BUY, price=40.0, quantity=1.0, exchange="default", strategy_id=1,
        portfolio_id=1, order_type=OrderType.MARKET, order_id=100,
        command=OrderCommand.NEW,
    )
    routing.exchange.on_order(bad)
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].status is FillStatus.REFUSED
    assert fills[0].order_id == 100
    assert not routing.exchange.matching_engine.has_order(100)


# --- D-03 slippage gating + D-11 real order context --------------------------


class _FixedFactorSlippage:
    """Stub slippage model returning a constant non-neutral Decimal factor."""

    def __init__(self, factor=Decimal("1.01")):
        self.factor = factor
        self.calls = []

    def calculate_slippage_factor(self, quantity, price, side="buy", order_type="market"):
        self.calls.append({"quantity": quantity, "price": price,
                           "side": side, "order_type": order_type})
        return self.factor

    def get_slippage_info(self):
        return {"model_type": "stub"}


class _CapturingFeeModel:
    """Stub fee model capturing the real order context handed by _emit_fill."""

    def __init__(self):
        self.calls = []

    def calculate_fee(self, quantity, price, side="buy", order_type="market",
                      is_maker=None):
        self.calls.append({"quantity": quantity, "price": price, "side": side,
                           "order_type": order_type, "is_maker": is_maker})
        return Decimal("0")

    def get_fee_info(self):
        return {"type": "stub"}


def test_limit_fill_carries_no_slippage_market_fill_does(routing):
    """D-03: slippage applies ONLY to MARKET/STOP fills — a resting limit
    fill takes its limit-or-better price unmodified."""
    stub = _FixedFactorSlippage(Decimal("1.01"))
    routing.exchange.slippage_model = stub

    # Resting SELL limit at 55: bar high 60 touches -> fill at 55, NO slippage.
    routing.exchange.on_order(
        routing.oe(OrderType.LIMIT, action="SELL", price=Decimal("55.0"), order_id=21))
    routing.exchange.on_market_data(routing.bar(open_=50, high=60, low=45, close=58))
    limit_fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(limit_fills) == 1
    assert limit_fills[0].status is FillStatus.EXECUTED
    assert limit_fills[0].price == Decimal("55.0")        # unmodified
    assert stub.calls == []                               # slippage never consulted

    # Market fill through the same exchange DOES take the slippage factor —
    # applied to the next bar's open (D-01/D-13).
    routing.exchange.on_order(
        routing.oe(OrderType.MARKET, action="BUY", price=Decimal("50.0"), order_id=22))
    routing.exchange.on_market_data(routing.bar(open_=50, high=52, low=49, close=51))
    market_fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(market_fills) == 1
    assert market_fills[0].price == Decimal("50") * Decimal("1.01")
    assert len(stub.calls) == 1


def test_stop_fill_takes_slippage(routing):
    """D-03: a triggered STOP is a taker fill — slippage applies."""
    stub = _FixedFactorSlippage(Decimal("1.01"))
    routing.exchange.slippage_model = stub
    routing.exchange.on_order(
        routing.oe(OrderType.STOP, action="SELL", price=Decimal("30.0"), order_id=23))
    routing.exchange.on_market_data(routing.bar(open_=35, high=36, low=20, close=25))
    fills = [routing.queue.get() for _ in range(routing.queue.qsize())]
    assert len(fills) == 1
    assert fills[0].price == Decimal("30.0") * Decimal("1.01")
    assert len(stub.calls) == 1
    assert stub.calls[0]["order_type"] == "STOP"


def test_fee_model_receives_real_order_context(routing):
    """D-11: _emit_fill passes the real order context — no hardcoded
    order_type='market'. A resting limit fill is classified maker."""
    fee_stub = _CapturingFeeModel()
    routing.exchange.fee_model = fee_stub

    # Resting SELL limit fill -> is_maker=True, order_type LIMIT.
    routing.exchange.on_order(
        routing.oe(OrderType.LIMIT, action="SELL", price=Decimal("55.0"), order_id=31))
    routing.exchange.on_market_data(routing.bar(open_=50, high=60, low=45, close=58))
    assert len(fee_stub.calls) == 1
    assert fee_stub.calls[0]["is_maker"] is True
    assert fee_stub.calls[0]["order_type"] == "LIMIT"
    while not routing.queue.empty():
        routing.queue.get()

    # Next-bar MARKET fill -> is_maker=False, order_type MARKET (taker).
    routing.exchange.on_order(
        routing.oe(OrderType.MARKET, action="BUY", price=Decimal("50.0"), order_id=32))
    routing.exchange.on_market_data(routing.bar(open_=50, high=52, low=49, close=51))
    assert len(fee_stub.calls) == 2
    assert fee_stub.calls[1]["is_maker"] is False
    assert fee_stub.calls[1]["order_type"] == "MARKET"

    # Triggered STOP fill -> is_maker=False (taker), order_type STOP.
    while not routing.queue.empty():
        routing.queue.get()
    routing.exchange.on_order(
        routing.oe(OrderType.STOP, action="SELL", price=Decimal("30.0"), order_id=33))
    routing.exchange.on_market_data(routing.bar(open_=35, high=36, low=20, close=25))
    assert len(fee_stub.calls) == 3
    assert fee_stub.calls[2]["is_maker"] is False
    assert fee_stub.calls[2]["order_type"] == "STOP"
