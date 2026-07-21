"""
Portfolio-specific exceptions for the iTrader system.
"""

from decimal import Decimal
from typing import Any, Optional, Union

from .base import ITraderError, ValidationError, ConfigurationError, StateError, NotFoundError
from ..ids import PortfolioId, TransactionId

# 02-05 carry-over: portfolio_id is a PortfolioId (UUID) at the entity layer but an
# int in the event layer; these diagnostic exceptions accept either form.
PortfolioIdLike = Union[PortfolioId, int, str]


class PortfolioError(ITraderError):
    """Base exception for portfolio-related errors."""
    pass


class InsufficientFundsError(PortfolioError):
    """Raised when attempting to execute a transaction with insufficient funds.

    WR-04: money fields are stored as ``Decimal`` so callers reading
    ``required_cash``/``available_cash`` programmatically get exact money, not a
    binary-float repr artifact. ``float`` formatting happens ONLY in the message
    (a logging/serialization edge). Callers may still pass ``float``/``int`` for
    backward compatibility — values enter the Decimal domain via ``Decimal(str(x))``
    (never ``Decimal(float)``) per the money policy.
    """

    def __init__(
        self,
        required_cash: "Decimal | float | int",
        available_cash: "Decimal | float | int",
        transaction_id: "Optional[TransactionId | int]" = None,
    ):
        self.required_cash: Decimal = (
            required_cash if isinstance(required_cash, Decimal) else Decimal(str(required_cash))
        )
        self.available_cash: Decimal = (
            available_cash if isinstance(available_cash, Decimal) else Decimal(str(available_cash))
        )
        self.transaction_id = transaction_id
        super().__init__(
            f"Insufficient funds: Required ${float(self.required_cash):.2f}, "
            f"Available ${float(self.available_cash):.2f}"
        )


class InvalidTransactionError(PortfolioError):
    """Raised when transaction data is invalid."""
    
    def __init__(self, message: str, transaction_data: Optional[dict[str, Any]] = None):
        self.transaction_data = transaction_data
        super().__init__(f"Invalid transaction: {message}")


class PortfolioNotFoundError(NotFoundError):
    """Raised when trying to access a non-existent portfolio."""
    
    def __init__(self, portfolio_id: PortfolioIdLike):
        self.portfolio_id = portfolio_id
        super().__init__("Portfolio", portfolio_id)


class PositionCalculationError(PortfolioError):
    """Raised when position calculations result in inconsistent state."""
    
    def __init__(self, message: str, position_data: Optional[dict[str, Any]] = None):
        self.position_data = position_data
        super().__init__(f"Position calculation error: {message}")


# PortfolioHandler specific exceptions
class PortfolioHandlerError(PortfolioError):
    """Base exception for all portfolio handler errors."""
    pass


class InvalidPortfolioOperationError(PortfolioHandlerError):
    """Raised when attempting an invalid operation on a portfolio."""
    
    def __init__(self, operation: str, portfolio_id: Optional[PortfolioIdLike] = None, reason: Optional[str] = None):
        self.operation = operation
        self.portfolio_id = portfolio_id
        self.reason = reason
        message = f"Invalid portfolio operation: {operation}"
        if portfolio_id:
            message += f" on portfolio {portfolio_id}"
        if reason:
            message += f" - {reason}"
        super().__init__(message)


class PortfolioStateError(StateError):
    """Raised when portfolio is in invalid state for requested operation."""
    
    def __init__(self, portfolio_id: PortfolioIdLike, current_state: str, required_state: Optional[str] = None, operation: Optional[str] = None):
        super().__init__(portfolio_id, current_state, required_state, operation)
        self.portfolio_id = portfolio_id


class PortfolioConfigurationError(ConfigurationError):
    """Raised when portfolio configuration is invalid."""
    pass


class PortfolioValidationError(ValidationError):
    """Raised when portfolio validation fails."""

    def __init__(self, portfolio_id: PortfolioIdLike, validation_type: str, details: Optional[str] = None):
        self.portfolio_id = portfolio_id
        self.validation_type = validation_type
        self.details = details
        message = f"Portfolio {portfolio_id} failed {validation_type} validation"
        if details:
            message += f": {details}"
        super().__init__(validation_type, str(portfolio_id), message)


class ReconciliationError(ITraderError):
    """A venue resting-order payload is missing/uncoercible where reconciliation needs an id (CF-7/SAFE-05)."""
    pass


class DuplicateVenueAccountError(PortfolioError):
    """Two portfolios name the SAME ``(venue_name, account_id)`` account (D-14/D-15, MPORT-02).

    The composition-time half of a deliberate two-layer defense. The database carries a
    PLAIN ``UniqueConstraint('venue_name', 'account_id')`` on ``portfolios`` (plan 11-01),
    which also binds out-of-band writers; this application check runs at boot over the
    UNION of persisted rows and composition-supplied spec portfolios, and its real job is
    the SPEC half — a duplicate the database has never seen and therefore cannot reject.
    Raising here also turns what would otherwise surface as a raw integrity error into a
    message an operator can act on.

    D-15: the correct response is REFUSE TO START, before any account is minted. There is
    no safe way to choose which of the colliding portfolios is the legitimate one, and
    conflated buying power across two portfolios is a money-losing wrong answer the venue
    cannot split back out afterwards. This is deliberately NOT the per-instance quarantine
    a bad strategy gets: skipping a strategy is harmless, whereas skipping a portfolio may
    abandon open positions.

    Carries the colliding pair and both portfolio labels as structured fields, and builds
    its message in ``__init__`` (the project's exception convention). The message names the
    consequence and the remediation, matching the loud-rejection discipline of the
    single-portfolio guard in ``reconciliation_coordinator``.
    """

    def __init__(
        self,
        venue_name: str,
        account_id: str,
        first_portfolio: str,
        second_portfolio: str,
    ):
        self.venue_name = venue_name
        self.account_id = account_id
        self.first_portfolio = first_portfolio
        self.second_portfolio = second_portfolio
        super().__init__(
            f"Portfolios {first_portfolio!r} and {second_portfolio!r} both name venue "
            f"account ({venue_name!r}, {account_id!r}). Refusing to start (D-15): two "
            f"portfolios sharing one venue account would conflate their buying power and "
            f"positions into a single balance the venue cannot split back out, and there "
            f"is no safe way to decide which portfolio the account belongs to. Give each "
            f"portfolio its own account_id on this venue, or remove one of them."
        )
