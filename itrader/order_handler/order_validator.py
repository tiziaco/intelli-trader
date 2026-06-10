from datetime import datetime, time
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from .order import Order
from ..core.enums import OrderType, OrderStatus, Side
from ..core.ids import PortfolioId
from ..core.portfolio_read_model import PortfolioReadModel


def _portfolio_id(order: Order) -> PortfolioId:
    """Return the order's PortfolioId for Protocol reads.

    FL-02: the Order entity now declares ``portfolio_id`` as ``PortfolioId``
    (#10 carry-forward complete), so this is a direct pass-through — the
    former bridging cast is no longer needed.
    """
    return order.portfolio_id


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
    
    def __init__(self, portfolio_handler: Optional[PortfolioReadModel] = None) -> None:
        """
        Initialize the enhanced order validator.

        Parameters
        ----------
        portfolio_handler : PortfolioReadModel, optional
            Narrow portfolio read boundary for balance and position checks
            (D-16: the concrete PortfolioHandler conforms structurally)
        """
        self.portfolio_handler = portfolio_handler
        
        # Default validation settings
        self.min_order_value = 1.0
        self.max_order_value = 1000000.0
        self.min_price = 0.01
        # Crypto prices exceed the stock-tuned $100k ceiling (the golden BTCUSD feed reaches
        # ~$116k in 2024-2026), which would otherwise reject every late-window trade and make
        # a complete oracle impossible. Raise the ceiling for the offline backtest run
        # (DEF-01-B class, Plan 01-04).
        self.max_price = 10000000.0
        self.min_quantity = 0.001
        self.max_quantity = 1000000.0
        self.min_cash_required = 30.0
        
        # Market hours (can be expanded per exchange)
        self.market_hours = {
            "NYSE": {"open": time(9, 30), "close": time(16, 0)},
            "NASDAQ": {"open": time(9, 30), "close": time(16, 0)},
            "default": {"open": time(0, 0), "close": time(23, 59)}  # 24/7 for crypto
        }
        
        # Supported exchanges. "csv" is the offline golden-feed venue used by the backtest
        # path: portfolios are created with exchange="csv", so signals carry that venue and
        # the validator must admit it for the offline run (DEF-01-B class, Plan 01-04).
        self.supported_exchanges = {"NYSE", "NASDAQ", "BINANCE", "OANDA", "default", "simulated", "csv"}
    
    def validate_order_pipeline(self, order: Order) -> ValidationResult:
        """
        Complete order validation pipeline with progressive validation phases.

        D-13 (entity-as-state): the pipeline checks the PENDING ``Order``
        entity, not the in-flight signal. The values validated (quantity,
        price, action, ticker) are the same values the signal pipeline
        validated before the entity-based cutover, so verdicts are identical.
        M5-10 (D-06): golden-path money comparisons are now native Decimal —
        the entity's Decimal price/quantity are compared against Decimal-wrapped
        thresholds, no float narrowing at the property boundary.

        Phases:
        1. Critical Fields - Essential fields validation
        2. Market Conditions - Exchange rules, market hours
        3. Portfolio Constraints - Portfolio-level limits
        4. Financial Risk - Cash availability, risk limits

        Each phase builds on the previous without redundant re-validation.

        Parameters
        ----------
        order : Order
            The PENDING order entity to validate

        Returns
        -------
        ValidationResult
            SUCCESS, WARNING, or ERROR with detailed messages
        """
        all_messages = []

        # PHASE 1: Critical Field Validation
        critical_messages = self._validate_critical_fields(order)
        all_messages.extend(critical_messages)
        if self._has_critical_errors(critical_messages):
            return ValidationResult(False, all_messages, "Critical field validation failed")

        # PHASE 2: Market & Exchange Validation
        market_messages = self._validate_market_conditions(order)
        all_messages.extend(market_messages)
        if self._has_critical_errors(market_messages):
            return ValidationResult(False, all_messages, "Market validation failed")

        # PHASE 3: Portfolio Constraints Validation
        portfolio_messages = self._validate_portfolio_constraints(order)
        all_messages.extend(portfolio_messages)
        if self._has_critical_errors(portfolio_messages):
            return ValidationResult(False, all_messages, "Portfolio validation failed")

        # PHASE 4: Financial Risk Validation
        risk_messages = self._validate_financial_risk(order)
        all_messages.extend(risk_messages)
        if self._has_critical_errors(risk_messages):
            return ValidationResult(False, all_messages, "Financial risk validation failed")

        # All phases passed. The typed ValidationResult IS the verdict (D-03):
        # nothing is mutated — acceptance/rejection is applied to the entity
        # by the caller through the audited add_state_change path.
        has_warnings = any(msg.level == ValidationLevel.WARNING for msg in all_messages)
        return ValidationResult(True, all_messages, "All validations passed", has_warnings)
    
    def _has_critical_errors(self, messages: List[ValidationMessage]) -> bool:
        """Check if any messages are critical errors."""
        return any(msg.level == ValidationLevel.ERROR for msg in messages)
    
    # ===== PHASE 1: CRITICAL FIELDS VALIDATION =====
    
    def _validate_critical_fields(self, order: Order) -> List[ValidationMessage]:
        """
        Essential fields that must be present for order processing.
        No business logic - just essential field presence and format validation.
        """
        messages: List[ValidationMessage] = []

        # Ticker validation
        if not order.ticker or not order.ticker.strip():
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Ticker symbol is required",
                "ticker",
                "MISSING_TICKER"
            ))

        # Action validation
        if order.action not in ["BUY", "SELL"]:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Invalid action: {order.action}. Must be BUY or SELL",
                "action",
                "INVALID_ACTION"
            ))

        # Price validation (M5-10: native Decimal comparison; Decimal vs int 0)
        if order.price <= 0:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Price must be positive",
                "price",
                "INVALID_PRICE"
            ))

        # Quantity validation. Sizing precedes validation on the run path and
        # rejected-at-admission entities are stored REJECTED before validation
        # ever runs (D-06), so nothing legitimate presents a non-positive
        # quantity here — it fails like any other invalid field (D-04: the
        # zero-quantity "transition period" is over).
        if order.quantity <= 0:  # M5-10: native Decimal comparison
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Quantity must be positive",
                "quantity",
                "INVALID_QUANTITY"
            ))

        # Order type is an OrderType enum on the entity by construction —
        # an unsupported type fails before the entity exists (D-13), so the
        # legacy string order-type check is structurally impossible here.

        # Portfolio ID validation
        if not order.portfolio_id:
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                "Portfolio ID is required",
                "portfolio_id",
                "MISSING_PORTFOLIO_ID"
            ))

        return messages
    
    # ===== PHASE 2: MARKET CONDITIONS VALIDATION =====
    
    def _validate_market_conditions(self, order: Order) -> List[ValidationMessage]:
        """
        Market and exchange-specific validation.
        Checks market hours, exchange rules, and instrument availability.
        """
        messages: List[ValidationMessage] = []

        # Exchange validation
        messages.extend(self._validate_exchange_support(order))

        # Market hours validation
        messages.extend(self._validate_market_hours(order))

        # Price range validation
        messages.extend(self._validate_price_ranges(order))

        # Quantity range validation
        messages.extend(self._validate_quantity_ranges(order))

        return messages

    def _validate_exchange_support(self, order: Order) -> List[ValidationMessage]:
        """Validate exchange is supported (Protocol read, OQ1 admission metadata)."""
        messages: List[ValidationMessage] = []

        # Get exchange from the read model or default
        if self.portfolio_handler:
            exchange = self.portfolio_handler.exchange_for(_portfolio_id(order))
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

    def _validate_market_hours(self, order: Order) -> List[ValidationMessage]:
        """Validate trading during market hours."""
        messages: List[ValidationMessage] = []

        # Get exchange for market hours (Protocol read)
        if self.portfolio_handler:
            exchange = self.portfolio_handler.exchange_for(_portfolio_id(order))
        else:
            exchange = 'default'

        # Check market hours for non-crypto exchanges
        if exchange in ["NYSE", "NASDAQ"]:
            current_time = order.time.time()
            market_hours = self.market_hours.get(exchange, self.market_hours["default"])

            if not (market_hours["open"] <= current_time <= market_hours["close"]):
                messages.append(ValidationMessage(
                    ValidationLevel.WARNING,
                    f"Trading outside market hours for {exchange}",
                    "market_hours",
                    "OUTSIDE_MARKET_HOURS"
                ))

        return messages

    def _validate_price_ranges(self, order: Order) -> List[ValidationMessage]:
        """Validate price is within acceptable ranges (M5-10: native Decimal).

        The float thresholds are wrapped via Decimal(str(...)) at the comparison
        site — never Decimal(float) (core/money.py:17). f-string formatting works
        unchanged on Decimal.
        """
        messages: List[ValidationMessage] = []

        price = order.price
        if price < Decimal(str(self.min_price)):
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Price {price} below minimum {self.min_price}",
                "price",
                "PRICE_TOO_LOW"
            ))
        elif price > Decimal(str(self.max_price)):
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Price {price} above maximum {self.max_price}",
                "price",
                "PRICE_TOO_HIGH"
            ))

        return messages

    def _validate_quantity_ranges(self, order: Order) -> List[ValidationMessage]:
        """Validate quantity is within acceptable ranges (M5-10: native Decimal).

        Float thresholds wrapped via Decimal(str(...)) at the comparison site.
        """
        messages: List[ValidationMessage] = []

        quantity = order.quantity
        if quantity < Decimal(str(self.min_quantity)):
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Quantity {quantity} below minimum {self.min_quantity}",
                "quantity",
                "QUANTITY_TOO_LOW"
            ))
        elif quantity > Decimal(str(self.max_quantity)):
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Quantity {quantity} above maximum {self.max_quantity}",
                "quantity",
                "QUANTITY_TOO_HIGH"
            ))

        return messages
    
    # ===== PHASE 3: PORTFOLIO CONSTRAINTS VALIDATION =====
    
    def _validate_portfolio_constraints(self, order: Order) -> List[ValidationMessage]:
        """
        Portfolio-wide constraints validation.
        Checks portfolio-level limits, not strategy-specific rules.
        """
        messages: List[ValidationMessage] = []

        if not self.portfolio_handler:
            return messages

        # Portfolio position limits
        messages.extend(self._check_portfolio_position_limits(order))

        # NOTE (D-14, OQ1 resolution): the former equity-based exposure check
        # (_check_portfolio_exposure_limits) is DELETED. Equity is excluded
        # from the order-domain surface — available_cash is the single
        # trading-decision figure. The check was WARNING-level only (it warned
        # on every golden BUY at 95% sizing) and never affected a verdict, so
        # deleting it is behavior-preserving-for-verdicts.

        return messages

    def _check_portfolio_position_limits(self, order: Order) -> List[ValidationMessage]:
        """Check portfolio-wide position limits (not strategy-specific)."""
        messages: List[ValidationMessage] = []
        assert self.portfolio_handler is not None  # guarded by caller

        # Portfolio-level position cap. The old getattr(portfolio,
        # 'max_positions', 50) always resolved to the default on the run path
        # (the real Portfolio exposes the limit under config.limits, never as
        # a flat attribute) — the constant preserves every verdict; a
        # per-portfolio cap on the Protocol surface is out of OQ1 scope.
        max_portfolio_positions = 50
        current_positions = self.portfolio_handler.open_position_count(_portfolio_id(order))

        if current_positions >= max_portfolio_positions:
            position = self.portfolio_handler.get_position(_portfolio_id(order), order.ticker)
            if not position or not self._is_closing_position(order, position):
                messages.append(ValidationMessage(
                    ValidationLevel.ERROR,
                    f"Portfolio max positions ({max_portfolio_positions}) reached",
                    "portfolio_limits",
                    "PORTFOLIO_MAX_POSITIONS"
                ))

        return messages

    def _is_closing_position(self, order: Order, position: Any) -> bool:
        """Check if the order is closing an existing position."""
        if not position:
            return False

        # The Order ENTITY stores a str action until M4 (D-05 boundary rule) —
        # compare against the Side member's value, never a bare string literal.
        return ((position.side.name == 'LONG' and order.action == Side.SELL.value) or
                (position.side.name == 'SHORT' and order.action == Side.BUY.value))
    
    # ===== PHASE 4: FINANCIAL RISK VALIDATION =====
    
    def _validate_financial_risk(self, order: Order) -> List[ValidationMessage]:
        """
        Financial capacity and risk constraints validation.
        Checks cash availability, margin requirements, risk limits.
        """
        messages: List[ValidationMessage] = []

        if not self.portfolio_handler:
            return messages

        # Cash availability validation
        messages.extend(self._check_cash_availability(order))

        # Risk limits validation
        messages.extend(self._check_risk_limits(order))

        return messages

    def _check_cash_availability(self, order: Order) -> List[ValidationMessage]:
        """Check if portfolio has sufficient cash for the trade (M5-10: native Decimal).

        cost = quantity * price is Decimal*Decimal; cash (available_cash) is
        already Decimal; thresholds wrapped via Decimal(str(...)). The
        ${cash:.2f} / ${cost:.2f} format specs work unchanged on Decimal.
        """
        messages: List[ValidationMessage] = []
        assert self.portfolio_handler is not None  # guarded by caller

        quantity = order.quantity
        price = order.price
        cost = quantity * price

        # Only check cash for new positions (not closing existing positions).
        # Per-ticker membership composes from get_position (OQ1); the cash
        # figure is available_cash — the single trading-decision figure
        # (D-14; available == total until plan 05-06 wires reservations).
        if self.portfolio_handler.get_position(_portfolio_id(order), order.ticker) is None:
            cash = self.portfolio_handler.available_cash(_portfolio_id(order))

            # Minimum cash requirement
            if cash < Decimal(str(self.min_cash_required)):
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

    def _check_risk_limits(self, order: Order) -> List[ValidationMessage]:
        """Check various risk limits (M5-10: native Decimal).

        Reads only order fields — the former portfolio lookup was an unused
        not-found guard (the read model raises typed PortfolioNotFoundError
        upstream), removed with the Protocol retype (D-16). order_value is
        Decimal*Decimal; thresholds wrapped via Decimal(str(...)).
        """
        messages: List[ValidationMessage] = []

        # Order value limits
        order_value = order.quantity * order.price

        if order_value < Decimal(str(self.min_order_value)):
            messages.append(ValidationMessage(
                ValidationLevel.WARNING,
                f"Order value ${order_value:.2f} below minimum ${self.min_order_value}",
                "order_value",
                "ORDER_VALUE_TOO_LOW"
            ))
        elif order_value > Decimal(str(self.max_order_value)):
            messages.append(ValidationMessage(
                ValidationLevel.ERROR,
                f"Order value ${order_value:.2f} exceeds maximum ${self.max_order_value}",
                "order_value",
                "ORDER_VALUE_TOO_HIGH"
            ))

        return messages
    
    # ===== ORDER MODIFICATION / RESULT HELPERS =====

    def validate_order_modification(self, order: Order, **modifications: Any) -> List[ValidationMessage]:
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
        messages: List[ValidationMessage] = []

        # Check new quantity vs filled quantity.
        # CR-01: callers (OrderManager.modify_order) always pass both kwargs,
        # including None for the unchanged one — a None value means "no change"
        # and must be skipped, never compared (TypeError otherwise).
        if 'new_quantity' in modifications and modifications['new_quantity'] is not None:
            new_quantity = modifications['new_quantity']
            if hasattr(order, 'filled_quantity') and order.filled_quantity:
                if new_quantity < order.filled_quantity:
                    messages.append(ValidationMessage(
                        level=ValidationLevel.ERROR,
                        message=f"New quantity {new_quantity} cannot be less than filled quantity {order.filled_quantity}",
                        field="new_quantity",
                        code="INVALID_MODIFICATION"
                    ))
        
        # Check new price is valid (None means "no change" — skip, CR-01)
        if 'new_price' in modifications and modifications['new_price'] is not None:
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
