from datetime import datetime, time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from .order import Order, OrderType, OrderStatus
from ..events_handler.event import SignalEvent


class ValidationLevel(Enum):
    """Result of order validation."""
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationMessage:
    """A validation message with severity and details."""
    level: ValidationLevel
    message: str
    field: Optional[str] = None
    code: Optional[str] = None
    suggested_fix: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of complete signal validation pipeline."""
    success: bool
    messages: List[ValidationMessage]
    summary: str
    has_warnings: bool = False
    
    @property
    def errors(self) -> List[ValidationMessage]:
        return [msg for msg in self.messages if msg.level == ValidationLevel.ERROR]
    
    @property 
    def warnings(self) -> List[ValidationMessage]:
        return [msg for msg in self.messages if msg.level == ValidationLevel.WARNING]


class EnhancedOrderValidator:
    """
    Unified order validation pipeline consolidating all validation logic.
    
    Replaces the separate ComplianceManager, RiskManager, and scattered validation.
    Provides a progressive validation pipeline with no redundant checks.
    
    Validation Phases:
    1. Critical Fields - Essential fields that must be present
    2. Market Conditions - Exchange rules, market hours, instrument availability  
    3. Portfolio Constraints - Portfolio-level limits and constraints
    4. Financial Risk - Cash availability, margin requirements, risk limits
    """
    
    def __init__(self, portfolio_handler=None):
        """
        Initialize the enhanced order validator.
        
        Parameters
        ----------
        portfolio_handler : PortfolioHandler, optional
            Portfolio handler for balance and position checks
        """
        self.portfolio_handler = portfolio_handler
        
        # Default validation settings
        self.min_order_value = 1.0
        self.max_order_value = 1000000.0
        self.min_price = 0.01
        self.max_price = 100000.0
        self.min_quantity = 0.001
        self.max_quantity = 1000000.0
        self.min_cash_required = 30.0
        
        # Market hours (can be expanded per exchange)
        self.market_hours = {
            "NYSE": {"open": time(9, 30), "close": time(16, 0)},
            "NASDAQ": {"open": time(9, 30), "close": time(16, 0)},
            "default": {"open": time(0, 0), "close": time(23, 59)}  # 24/7 for crypto
        }
        
        # Supported exchanges
        self.supported_exchanges = {"NYSE", "NASDAQ", "BINANCE", "OANDA", "default"}
    
    def validate_signal_pipeline(self, signal: SignalEvent) -> ValidationResult:
        """
        Complete signal validation pipeline with progressive validation phases.
        
        Phases:
        1. Critical Fields - Essential fields validation
        2. Market Conditions - Exchange rules, market hours 
        3. Portfolio Constraints - Portfolio-level limits
        4. Financial Risk - Cash availability, risk limits
        
        Each phase builds on the previous without redundant re-validation.
        
        Parameters
        ----------
        signal : SignalEvent
            The signal to validate
            
        Returns
        -------
        ValidationResult
            SUCCESS, WARNING, or ERROR with detailed messages
        """
        all_messages = []
        
        # PHASE 1: Critical Field Validation
        critical_messages = self._validate_critical_fields(signal)
        all_messages.extend(critical_messages)
        if self._has_critical_errors(critical_messages):
            signal.verified = False
            return ValidationResult(False, all_messages, "Critical field validation failed")
        
        # PHASE 2: Market & Exchange Validation  
        market_messages = self._validate_market_conditions(signal)
        all_messages.extend(market_messages)
        if self._has_critical_errors(market_messages):
            signal.verified = False
            return ValidationResult(False, all_messages, "Market validation failed")
        
        # PHASE 3: Portfolio Constraints Validation
        portfolio_messages = self._validate_portfolio_constraints(signal)
        all_messages.extend(portfolio_messages)
        if self._has_critical_errors(portfolio_messages):
            signal.verified = False
            return ValidationResult(False, all_messages, "Portfolio validation failed")
        
        # PHASE 4: Financial Risk Validation
        risk_messages = self._validate_financial_risk(signal)
        all_messages.extend(risk_messages)
        if self._has_critical_errors(risk_messages):
            signal.verified = False
            return ValidationResult(False, all_messages, "Financial risk validation failed")
        
        # All phases passed
        signal.verified = True
        has_warnings = any(msg.level == ValidationLevel.WARNING for msg in all_messages)
        return ValidationResult(True, all_messages, "All validations passed", has_warnings)
    
    def _has_critical_errors(self, messages: List[ValidationMessage]) -> bool:
        """Check if any messages are critical errors."""
        return any(msg.level == ValidationLevel.ERROR for msg in messages)
    
    # ===== PHASE 1: CRITICAL FIELDS VALIDATION =====
    
    def _validate_critical_fields(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Essential fields that must be present for signal processing.
        No business logic - just essential field presence and format validation.
        """
        messages = []
        
        # Ticker validation
        if not signal.ticker or not signal.ticker.strip():
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Ticker symbol is required",
                "ticker",
                "MISSING_TICKER"
            ))
        
        # Action validation
        if signal.action not in ["BUY", "SELL"]:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Invalid action: {signal.action}. Must be BUY or SELL",
                "action",
                "INVALID_ACTION"
            ))
        
        # Price validation
        if signal.price <= 0:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Price must be positive",
                "price",
                "INVALID_PRICE"
            ))
        
        # Quantity validation (signal should come pre-sized from strategy)
        # TEMPORARY: Allow quantity=0 during transition period before position sizer is moved to strategy
        if signal.quantity < 0:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Quantity cannot be negative",
                "quantity",
                "NEGATIVE_QUANTITY"
            ))
        elif signal.quantity == 0:
            messages.append(ValidationMessage(
                ValidationLevel.WARNING,
                "Quantity is zero - signal needs position sizing (transition period)",
                "quantity",
                "ZERO_QUANTITY_TRANSITION"
            ))
        
        # Order type validation
        if hasattr(signal, 'order_type') and signal.order_type:
            if signal.order_type.upper() not in ["MARKET", "STOP", "LIMIT"]:
                messages.append(ValidationMessage(
                    ValidationLevel.ERROR,
                    f"Invalid order type: {signal.order_type}",
                    "order_type",
                    "INVALID_ORDER_TYPE"
                ))
        
        # Portfolio ID validation
        if not signal.portfolio_id:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Portfolio ID is required",
                "portfolio_id",
                "MISSING_PORTFOLIO_ID"
            ))
        
        return messages
    
    # ===== PHASE 2: MARKET CONDITIONS VALIDATION =====
    
    def _validate_market_conditions(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Market and exchange-specific validation.
        Checks market hours, exchange rules, and instrument availability.
        """
        messages = []
        
        # Exchange validation
        messages.extend(self._validate_exchange_support(signal))
        
        # Market hours validation
        messages.extend(self._validate_market_hours(signal))
        
        # Price range validation
        messages.extend(self._validate_price_ranges(signal))
        
        # Quantity range validation  
        messages.extend(self._validate_quantity_ranges(signal))
        
        return messages
    
    def _validate_exchange_support(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate exchange is supported."""
        messages = []
        
        # Get exchange from portfolio or default
        if self.portfolio_handler:
            portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
            exchange = getattr(portfolio, 'exchange', 'default') if portfolio else 'default'
        else:
            exchange = 'default'
        
        if exchange not in self.supported_exchanges:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Unsupported exchange: {exchange}",
                "exchange",
                "UNSUPPORTED_EXCHANGE"
            ))
        
        return messages
    
    def _validate_market_hours(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate trading during market hours."""
        messages = []
        
        # Get exchange for market hours
        if self.portfolio_handler:
            portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
            exchange = getattr(portfolio, 'exchange', 'default') if portfolio else 'default'
        else:
            exchange = 'default'
        
        # Check market hours for non-crypto exchanges
        if exchange in ["NYSE", "NASDAQ"]:
            current_time = signal.time.time()
            market_hours = self.market_hours.get(exchange, self.market_hours["default"])
            
            if not (market_hours["open"] <= current_time <= market_hours["close"]):
                messages.append(ValidationMessage(
                    ValidationLevel.WARNING,
                    f"Trading outside market hours for {exchange}",
                    "market_hours",
                    "OUTSIDE_MARKET_HOURS"
                ))
        
        return messages
    
    def _validate_price_ranges(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate price is within acceptable ranges."""
        messages = []
        
        if signal.price < self.min_price:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Price {signal.price} below minimum {self.min_price}",
                "price",
                "PRICE_TOO_LOW"
            ))
        elif signal.price > self.max_price:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Price {signal.price} above maximum {self.max_price}",
                "price", 
                "PRICE_TOO_HIGH"
            ))
        
        return messages
    
    def _validate_quantity_ranges(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate quantity is within acceptable ranges."""
        messages = []
        
        if signal.quantity < self.min_quantity:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Quantity {signal.quantity} below minimum {self.min_quantity}",
                "quantity",
                "QUANTITY_TOO_LOW"
            ))
        elif signal.quantity > self.max_quantity:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Quantity {signal.quantity} above maximum {self.max_quantity}",
                "quantity",
                "QUANTITY_TOO_HIGH"
            ))
        
        return messages
    
    # ===== PHASE 3: PORTFOLIO CONSTRAINTS VALIDATION =====
    
    def _validate_portfolio_constraints(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Portfolio-wide constraints validation.
        Checks portfolio-level limits, not strategy-specific rules.
        """
        messages = []
        
        if not self.portfolio_handler:
            return messages
        
        # Portfolio position limits
        messages.extend(self._check_portfolio_position_limits(signal))
        
        # Portfolio exposure limits
        messages.extend(self._check_portfolio_exposure_limits(signal))
        
        return messages
    
    def _check_portfolio_position_limits(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Check portfolio-wide position limits (not strategy-specific)."""
        messages = []
        
        portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
        if not portfolio:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Portfolio {signal.portfolio_id} not found",
                "portfolio_id",
                "PORTFOLIO_NOT_FOUND"
            ))
            return messages
        
        # Portfolio-level limits (configurable per portfolio, not per strategy)
        max_portfolio_positions = getattr(portfolio, 'max_positions', 50)  # Portfolio setting
        current_positions = portfolio.n_open_positions
        
        if current_positions >= max_portfolio_positions:
            position = portfolio.positions.get(signal.ticker)
            if not position or not self._is_closing_position(signal, position):
                messages.append(ValidationMessage(
                    ValidationLevel.ERROR,
                    f"Portfolio max positions ({max_portfolio_positions}) reached",
                    "portfolio_limits",
                    "PORTFOLIO_MAX_POSITIONS"
                ))
        
        return messages
    
    def _check_portfolio_exposure_limits(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Check portfolio exposure limits."""
        messages = []
        
        portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
        if not portfolio:
            return messages
        
        # Calculate position value
        position_value = signal.quantity * signal.price
        
        # Check against portfolio total equity
        total_equity = portfolio.total_equity
        if total_equity > 0:
            exposure_percentage = position_value / total_equity
            max_single_position_exposure = 0.20  # 20% max per position
            
            if exposure_percentage > max_single_position_exposure:
                messages.append(ValidationMessage(
                    ValidationLevel.WARNING,
                    f"Position exposure {exposure_percentage:.1%} exceeds recommended {max_single_position_exposure:.1%}",
                    "exposure",
                    "HIGH_POSITION_EXPOSURE"
                ))
        
        return messages
    
    def _is_closing_position(self, signal: SignalEvent, position) -> bool:
        """Check if signal is closing an existing position."""
        if not position:
            return False
        
        return ((position.side.name == 'LONG' and signal.action == 'SELL') or 
                (position.side.name == 'SHORT' and signal.action == 'BUY'))
    
    # ===== PHASE 4: FINANCIAL RISK VALIDATION =====
    
    def _validate_financial_risk(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Financial capacity and risk constraints validation.
        Checks cash availability, margin requirements, risk limits.
        """
        messages = []
        
        if not self.portfolio_handler:
            return messages
        
        # Cash availability validation
        messages.extend(self._check_cash_availability(signal))
        
        # Risk limits validation
        messages.extend(self._check_risk_limits(signal))
        
        return messages
    
    def _check_cash_availability(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Check if portfolio has sufficient cash for the trade."""
        messages = []
        
        portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
        if not portfolio:
            return messages
        
        quantity = signal.quantity
        price = signal.price
        cost = quantity * price
        
        # Only check cash for new positions (not closing existing positions)
        if signal.ticker not in portfolio.positions:
            cash = portfolio.cash
            
            # Minimum cash requirement
            if cash < self.min_cash_required:
                messages.append(ValidationMessage(
                    ValidationLevel.ERROR,
                    f"Insufficient cash: ${cash:.2f} below minimum ${self.min_cash_required}",
                    "cash",
                    "INSUFFICIENT_CASH_MINIMUM"
                ))
            # Cost requirement
            elif cash < cost:
                messages.append(ValidationMessage(
                    ValidationLevel.ERROR,
                    f"Insufficient cash: ${cash:.2f} < ${cost:.2f} required",
                    "cash", 
                    "INSUFFICIENT_CASH_COST"
                ))
        
        return messages
    
    def _check_risk_limits(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Check various risk limits."""
        messages = []
        
        portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
        if not portfolio:
            return messages
        
        # Order value limits
        order_value = signal.quantity * signal.price
        
        if order_value < self.min_order_value:
            messages.append(ValidationMessage(
                ValidationLevel.WARNING,
                f"Order value ${order_value:.2f} below minimum ${self.min_order_value}",
                "order_value",
                "ORDER_VALUE_TOO_LOW"
            ))
        elif order_value > self.max_order_value:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Order value ${order_value:.2f} exceeds maximum ${self.max_order_value}",
                "order_value",
                "ORDER_VALUE_TOO_HIGH"
            ))
        
        return messages
    
    # ===== BACKWARD COMPATIBILITY METHODS FOR TESTS =====
    
    def validate_signal(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Backward compatibility method for tests.
        Uses the new pipeline and returns just the messages.
        """
        result = self.validate_signal_pipeline(signal)
        return result.messages
    
    def validate_signal_basic(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Backward compatibility method for basic validation only.
        """
        return self._validate_critical_fields(signal)
    
    def validate_signal_complete(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Backward compatibility method for complete validation.
        """
        result = self.validate_signal_pipeline(signal)
        return result.messages
    
    def validate_order_modification(self, order: Order, **modifications) -> List[ValidationMessage]:
        """
        Validate order modification parameters.
        
        Parameters
        ----------
        order : Order
            The existing order
        **modifications
            Modification parameters (new_quantity, new_price, etc.)
        
        Returns
        -------
        List[ValidationMessage]
            Validation messages
        """
        messages = []
        
        # Check new quantity vs filled quantity
        if 'new_quantity' in modifications:
            new_quantity = modifications['new_quantity']
            if hasattr(order, 'filled_quantity') and order.filled_quantity:
                if new_quantity < order.filled_quantity:
                    messages.append(ValidationMessage(
                        level=ValidationLevel.ERROR,
                        message=f"New quantity {new_quantity} cannot be less than filled quantity {order.filled_quantity}",
                        field="new_quantity",
                        code="INVALID_MODIFICATION"
                    ))
        
        # Check new price is valid
        if 'new_price' in modifications:
            new_price = modifications['new_price']
            if new_price <= 0:
                messages.append(ValidationMessage(
                    level=ValidationLevel.ERROR,
                    message=f"New price must be positive, got: {new_price}",
                    field="new_price",
                    code="INVALID_PRICE"
                ))
        
        return messages
    
    def is_valid(self, messages: List[ValidationMessage]) -> bool:
        """Check if validation messages indicate success (no errors)."""
        return not any(msg.level == ValidationLevel.ERROR for msg in messages)
    
    def get_errors(self, messages: List[ValidationMessage]) -> List[ValidationMessage]:
        """Get only error messages from validation results."""
        return [msg for msg in messages if msg.level == ValidationLevel.ERROR]
    
    def get_warnings(self, messages: List[ValidationMessage]) -> List[ValidationMessage]:
        """Get only warning messages from validation results."""
        return [msg for msg in messages if msg.level == ValidationLevel.WARNING]

    # ===== END BACKWARD COMPATIBILITY METHODS =====
