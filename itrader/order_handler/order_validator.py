from datetime import datetime, time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from .order import Order, OrderType, OrderStatus
from ..events_handler.event import SignalEvent


class ValidationResult(Enum):
    """Result of order validation."""
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationMessage:
    """A validation message with severity and details."""
    level: ValidationResult
    message: str
    field: Optional[str] = None
    code: Optional[str] = None
    suggested_fix: Optional[str] = None


class OrderValidator:
    """
    Centralized order validation logic.
    
    Provides comprehensive validation for orders including:
    - Market rules validation
    - Order parameter validation  
    - Risk and compliance checks
    - Business rule validation
    """
    # TODO: Check if i have redundant methods relative to the risk manager and compliance handler.
    def __init__(self, portfolio_handler=None):
        """
        Initialize the order validator.
        
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
        
        # Market hours (can be expanded per exchange)
        self.market_hours = {
            "NYSE": {"open": time(9, 30), "close": time(16, 0)},
            "NASDAQ": {"open": time(9, 30), "close": time(16, 0)},
            "default": {"open": time(0, 0), "close": time(23, 59)}  # 24/7 for crypto
        }
        
        # Supported exchanges
        self.supported_exchanges = {"NYSE", "NASDAQ", "BINANCE", "OANDA", "default"}
    
    def validate_signal(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Validate a signal event before order creation.
        
        Parameters
        ----------
        signal : SignalEvent
            The signal to validate
            
        Returns
        -------
        List[ValidationMessage]
            List of validation messages
        """
        messages = []
        
        # Basic signal validation
        messages.extend(self._validate_basic_signal_params(signal))
        
        # Market validation
        messages.extend(self._validate_market_conditions(signal))
        
        # Portfolio validation
        if self.portfolio_handler:
            messages.extend(self._validate_portfolio_constraints(signal))
        
        return messages
    
    def validate_order(self, order: Order) -> List[ValidationMessage]:
        """
        Validate an order object.
        
        Parameters
        ----------
        order : Order
            The order to validate
            
        Returns
        -------
        List[ValidationMessage]
            List of validation messages
        """
        messages = []
        
        # Basic order validation
        messages.extend(self._validate_basic_order_params(order))
        
        # State validation
        messages.extend(self._validate_order_state(order))
        
        # Market validation
        messages.extend(self._validate_market_conditions_for_order(order))
        
        # Portfolio validation
        if self.portfolio_handler:
            messages.extend(self._validate_portfolio_constraints_for_order(order))
        
        return messages
    
    def validate_order_modification(self, order: Order, new_price: Optional[float] = None, 
                                  new_quantity: Optional[float] = None) -> List[ValidationMessage]:
        """
        Validate order modification parameters.
        
        Parameters
        ----------
        order : Order
            The order to modify
        new_price : float, optional
            New price for the order
        new_quantity : float, optional
            New quantity for the order
            
        Returns
        -------
        List[ValidationMessage]
            List of validation messages
        """
        messages = []
        
        # Check if order can be modified
        if not order.is_active:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Cannot modify order in {order.status.name} state",
                "status",
                "ORDER_NOT_MODIFIABLE"
            ))
            return messages
        
        # Validate new parameters
        if new_price is not None:
            messages.extend(self._validate_price(new_price))
        
        if new_quantity is not None:
            messages.extend(self._validate_quantity_modification(order, new_quantity))
        
        return messages
    
    def is_valid(self, messages: List[ValidationMessage]) -> bool:
        """
        Check if validation messages contain any errors.
        
        Parameters
        ----------
        messages : List[ValidationMessage]
            Validation messages to check
            
        Returns
        -------
        bool
            True if no error-level messages, False otherwise
        """
        return not any(msg.level == ValidationResult.ERROR for msg in messages)
    
    def get_errors(self, messages: List[ValidationMessage]) -> List[ValidationMessage]:
        """Get only error-level validation messages."""
        return [msg for msg in messages if msg.level == ValidationResult.ERROR]
    
    def get_warnings(self, messages: List[ValidationMessage]) -> List[ValidationMessage]:
        """Get only warning-level validation messages."""
        return [msg for msg in messages if msg.level == ValidationResult.WARNING]
    
    def _validate_basic_signal_params(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate basic signal parameters."""
        messages = []
        
        # Validate ticker
        if not signal.ticker or not signal.ticker.strip():
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Ticker symbol is required",
                "ticker",
                "MISSING_TICKER"
            ))
        
        # Validate action
        if signal.action not in ["BUY", "SELL"]:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Invalid action: {signal.action}. Must be BUY or SELL",
                "action",
                "INVALID_ACTION"
            ))
        
        # Validate price
        messages.extend(self._validate_price(signal.price))
        
        # Validate quantity (enforce positive quantity for complete validation)
        messages.extend(self._validate_quantity(signal.quantity, allow_zero_for_unprocessed=False))
        
        # Validate order type
        if hasattr(signal, 'order_type') and signal.order_type:
            if signal.order_type.upper() not in ["MARKET", "STOP", "LIMIT"]:
                messages.append(ValidationMessage(
                    ValidationResult.ERROR,
                    f"Invalid order type: {signal.order_type}",
                    "order_type",
                    "INVALID_ORDER_TYPE"
                ))
        
        return messages
    
    def _validate_basic_order_params(self, order: Order) -> List[ValidationMessage]:
        """Validate basic order parameters."""
        messages = []
        
        # Validate ticker
        if not order.ticker or not order.ticker.strip():
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Ticker symbol is required",
                "ticker",
                "MISSING_TICKER"
            ))
        
        # Validate action
        if order.action not in ["BUY", "SELL"]:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Invalid action: {order.action}. Must be BUY or SELL",
                "action",
                "INVALID_ACTION"
            ))
        
        # Validate price
        messages.extend(self._validate_price(order.price))
        
        # Validate quantity
        messages.extend(self._validate_quantity(order.quantity))
        
        # Validate order value
        order_value = order.price * order.quantity
        if order_value < self.min_order_value:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Order value ${order_value:.2f} below minimum ${self.min_order_value}",
                "value",
                "ORDER_VALUE_TOO_LOW"
            ))
        elif order_value > self.max_order_value:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Order value ${order_value:.2f} exceeds maximum ${self.max_order_value}",
                "value",
                "ORDER_VALUE_TOO_HIGH"
            ))
        
        return messages
    
    def _validate_price(self, price: float) -> List[ValidationMessage]:
        """Validate price parameter."""
        messages = []
        
        if price <= 0:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Price must be positive",
                "price",
                "INVALID_PRICE"
            ))
        elif price < self.min_price:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Price ${price} below minimum ${self.min_price}",
                "price",
                "PRICE_TOO_LOW"
            ))
        elif price > self.max_price:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Price ${price} exceeds maximum ${self.max_price}",
                "price",
                "PRICE_TOO_HIGH"
            ))
        
        return messages
    
    def _validate_quantity(self, quantity: float, allow_zero_for_unprocessed: bool = False) -> List[ValidationMessage]:
        """Validate quantity parameter."""
        messages = []
        
        # Allow zero quantity for unprocessed signals (before position sizing)
        if quantity == 0 and allow_zero_for_unprocessed:
            return messages  # No validation error for zero quantity in unprocessed signals
        
        if quantity <= 0:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Quantity must be positive",
                "quantity",
                "INVALID_QUANTITY"
            ))
        elif quantity < self.min_quantity:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Quantity {quantity} below minimum {self.min_quantity}",
                "quantity",
                "QUANTITY_TOO_LOW"
            ))
        elif quantity > self.max_quantity:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Quantity {quantity} exceeds maximum {self.max_quantity}",
                "quantity",
                "QUANTITY_TOO_HIGH"
            ))
        
        return messages
    
    def _validate_quantity_modification(self, order: Order, new_quantity: float) -> List[ValidationMessage]:
        """Validate quantity modification for partially filled orders."""
        messages = []
        
        # Basic quantity validation
        messages.extend(self._validate_quantity(new_quantity))
        
        # Check against filled quantity
        if new_quantity < order.filled_quantity:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"New quantity {new_quantity} cannot be less than filled quantity {order.filled_quantity}",
                "quantity",
                "QUANTITY_BELOW_FILLED"
            ))
        
        return messages
    
    def _validate_order_state(self, order: Order) -> List[ValidationMessage]:
        """Validate order state and transitions."""
        messages = []
        
        # Check for expired orders
        if order.expiry_time and datetime.now() > order.expiry_time:
            messages.append(ValidationMessage(
                ValidationResult.WARNING,
                "Order has expired",
                "expiry_time",
                "ORDER_EXPIRED"
            ))
        
        # Validate filled quantity consistency
        if order.filled_quantity > order.quantity:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Filled quantity {order.filled_quantity} exceeds order quantity {order.quantity}",
                "filled_quantity",
                "OVERFILLED_ORDER"
            ))
        
        # Validate status consistency
        if order.is_fully_filled and order.status != OrderStatus.FILLED:
            messages.append(ValidationMessage(
                ValidationResult.WARNING,
                "Order appears fully filled but status is not FILLED",
                "status",
                "STATUS_INCONSISTENCY"
            ))
        
        return messages
    
    def _validate_market_conditions(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate market conditions for signal."""
        messages = []
        
        # Basic exchange validation
        if hasattr(signal, 'exchange'):
            exchange = getattr(signal, 'exchange', 'default')
            if exchange not in self.supported_exchanges:
                messages.append(ValidationMessage(
                    ValidationResult.WARNING,
                    f"Exchange {exchange} not in supported list",
                    "exchange",
                    "UNSUPPORTED_EXCHANGE"
                ))
        
        return messages
    
    def _validate_market_conditions_for_order(self, order: Order) -> List[ValidationMessage]:
        """Validate market conditions for order."""
        messages = []
        
        # Exchange validation
        if order.exchange not in self.supported_exchanges:
            messages.append(ValidationMessage(
                ValidationResult.WARNING,
                f"Exchange {order.exchange} not in supported list",
                "exchange",
                "UNSUPPORTED_EXCHANGE"
            ))
        
        return messages
    
    def _validate_portfolio_constraints(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate portfolio constraints for signal."""
        messages = []
        
        try:
            portfolio = self.portfolio_handler.get_portfolio(signal.portfolio_id)
            
            # Check available cash for buy orders
            if signal.action == "BUY":
                required_cash = signal.price * signal.quantity
                if portfolio.cash < required_cash:
                    messages.append(ValidationMessage(
                        ValidationResult.ERROR,
                        f"Insufficient cash: need ${required_cash:.2f}, have ${portfolio.cash:.2f}",
                        "cash",
                        "INSUFFICIENT_FUNDS"
                    ))
            
            # Check position for sell orders
            elif signal.action == "SELL":
                if hasattr(portfolio, 'positions') and signal.ticker in portfolio.positions:
                    available_quantity = portfolio.positions[signal.ticker].quantity
                    if available_quantity < signal.quantity:
                        messages.append(ValidationMessage(
                            ValidationResult.ERROR,
                            f"Insufficient position: need {signal.quantity}, have {available_quantity}",
                            "quantity",
                            "INSUFFICIENT_POSITION"
                        ))
        
        except Exception as e:
            messages.append(ValidationMessage(
                ValidationResult.WARNING,
                f"Could not validate portfolio constraints: {str(e)}",
                "portfolio",
                "PORTFOLIO_VALIDATION_ERROR"
            ))
        
        return messages
    
    def _validate_portfolio_constraints_for_order(self, order: Order) -> List[ValidationMessage]:
        """Validate portfolio constraints for order."""
        messages = []
        
        try:
            portfolio = self.portfolio_handler.get_portfolio(order.portfolio_id)
            
            # Check remaining order value against available cash
            if order.action == "BUY" and order.remaining_quantity > 0:
                required_cash = order.price * order.remaining_quantity
                if portfolio.cash < required_cash:
                    messages.append(ValidationMessage(
                        ValidationResult.WARNING,
                        f"May have insufficient cash for remaining quantity: need ${required_cash:.2f}, have ${portfolio.cash:.2f}",
                        "cash",
                        "POTENTIAL_INSUFFICIENT_FUNDS"
                    ))
        
        except Exception as e:
            messages.append(ValidationMessage(
                ValidationResult.WARNING,
                f"Could not validate portfolio constraints: {str(e)}",
                "portfolio",
                "PORTFOLIO_VALIDATION_ERROR"
            ))
        
        return messages
    
    def configure_limits(self, **kwargs):
        """
        Configure validation limits.
        
        Parameters
        ----------
        **kwargs
            Validation limit parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
    
    def add_supported_exchange(self, exchange: str):
        """Add a supported exchange."""
        self.supported_exchanges.add(exchange)
    
    def set_market_hours(self, exchange: str, open_time: time, close_time: time):
        """Set market hours for an exchange."""
        self.market_hours[exchange] = {"open": open_time, "close": close_time}
    
    def validate_signal_basic(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Validate only essential signal fields before processing.
        
        This validation checks only critical fields that must be present
        for the signal to be processable, but doesn't enforce business rules
        that depend on calculated values (like quantity after position sizing).
        
        Parameters
        ----------
        signal : SignalEvent
            The signal to validate
            
        Returns
        -------
        List[ValidationMessage]
            List of validation messages for critical issues only
        """
        messages = []
        
        # Validate only essential fields
        if not signal.ticker or not signal.ticker.strip():
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Ticker symbol is required",
                "ticker",
                "MISSING_TICKER"
            ))
        
        if signal.action not in ["BUY", "SELL"]:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                f"Invalid action: {signal.action}. Must be BUY or SELL",
                "action",
                "INVALID_ACTION"
            ))
        
        # Basic price validation (must be positive)
        if signal.price <= 0:
            messages.append(ValidationMessage(
                ValidationResult.ERROR,
                "Price must be positive",
                "price",
                "INVALID_PRICE"
            ))
        
        # Order type validation
        if hasattr(signal, 'order_type') and signal.order_type:
            if signal.order_type.upper() not in ["MARKET", "STOP", "LIMIT"]:
                messages.append(ValidationMessage(
                    ValidationResult.ERROR,
                    f"Invalid order type: {signal.order_type}",
                    "order_type",
                    "INVALID_ORDER_TYPE"
                ))
        
        return messages
    
    def validate_signal_complete(self, signal: SignalEvent) -> List[ValidationMessage]:
        """
        Validate a fully processed signal with all business rules.
        
        This validation should be called after the signal has been processed
        by compliance, position sizer, and risk manager to ensure all
        business rules are satisfied on the complete, final signal.
        
        Parameters
        ----------
        signal : SignalEvent
            The fully processed signal to validate
            
        Returns
        -------
        List[ValidationMessage]
            List of validation messages
        """
        messages = []
        
        # Full validation including business rules
        messages.extend(self._validate_basic_signal_params_complete(signal))
        messages.extend(self._validate_market_conditions(signal))
        
        # Portfolio validation
        if self.portfolio_handler:
            messages.extend(self._validate_portfolio_constraints(signal))
        
        return messages
    
    def _validate_basic_signal_params_complete(self, signal: SignalEvent) -> List[ValidationMessage]:
        """Validate basic signal parameters for a complete signal."""
        messages = []
        
        # Now we can validate quantity properly since position sizer has set it
        messages.extend(self._validate_quantity(signal.quantity, allow_zero_for_unprocessed=False))
        
        # Validate price with business rules
        messages.extend(self._validate_price(signal.price))
        
        # Validate order type
        if hasattr(signal, 'order_type') and signal.order_type:
            if signal.order_type.upper() not in ["MARKET", "STOP", "LIMIT"]:
                messages.append(ValidationMessage(
                    ValidationResult.ERROR,
                    f"Invalid order type: {signal.order_type}",
                    "order_type",
                    "INVALID_ORDER_TYPE"
                ))
        
        return messages
