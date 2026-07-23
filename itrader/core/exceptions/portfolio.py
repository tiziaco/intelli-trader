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


# Per-key rationale for ImmutableConfigKeyError. Keyed so the message names the ACTUAL
# consequence + remediation for the refused key rather than a vague generic line; the
# fallback keeps a future key honest if its entry is forgotten.
_IMMUTABLE_KEY_RATIONALE: dict[str, str] = {
    "enable_margin": (
        "Four of its five readers bind the value at CONSTRUCTION — "
        "AdmissionManager._enable_margin, EnhancedOrderValidator.enable_margin, "
        "ManagedStrategies.enable_margin (the SHORT-01 direction gate) and the account "
        "leaf's very KIND (cash vs margin) — while only Portfolio.process_transaction "
        "re-reads it per fill. A runtime flip would therefore desynchronize four of the "
        "five readers silently: settlement would take the margin arm while admission, "
        "validation, the strategy gate and the account leaf all still believe margin is "
        "off. Recreate the portfolio with the desired margin setting instead."
    ),
}

_IMMUTABLE_KEY_FALLBACK = (
    "Its readers bind the value at construction, so a runtime flip would desynchronize "
    "them silently. Recreate the portfolio with the desired setting instead."
)


class ImmutableConfigKeyError(PortfolioError):
    """A runtime config update names a portfolio key that is deliberately immutable (11.1-REVIEW CR-02).

    Raised by BOTH refusal layers over the single ``IMMUTABLE_PORTFOLIO_CONFIG_KEYS`` set:
    ``ConfigRouter._apply_portfolio`` (the queue-facing default-deny gate, which converts
    this into its standard deduped WARNING rejection rather than letting it escape
    ``apply()``) and ``Portfolio.update_config`` (the backstop for any caller that reaches
    the domain object directly). The two layers are deliberate defense-in-depth, not
    redundancy: the router cannot see a caller that bypasses the queue.

    The refusal is KEY-scoped, never section-scoped — ``trading_rules`` stays a mutable
    section and every other field in it stays routable. It is also presence-based, not
    value-based: naming the key with its CURRENT value is refused too, so an operator
    cannot discover the boundary by accident and conclude the knob "sometimes works".

    Carries the rejected ``key`` (and the originating ``scope`` when the router raises it)
    as structured fields and builds its message in ``__init__`` (the project's exception
    convention). The message names the CONSEQUENCE (which readers desynchronize) and the
    REMEDIATION (recreate the portfolio) so an operator can act on it.
    """

    def __init__(self, key: str, scope: Optional[str] = None):
        self.key = key
        self.scope = scope
        where = f" (scope {scope!r})" if scope else ""
        rationale = _IMMUTABLE_KEY_RATIONALE.get(key, _IMMUTABLE_KEY_FALLBACK)
        super().__init__(
            f"Portfolio config key {key!r}{where} is not runtime-mutable. {rationale}"
        )


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


# Per-CAUSE rationale for VenueAccountNotProvisionedError (ACCT-03 / D-21).
#
# The three causes are NOT interchangeable and the message must not blur them: only
# ``VenueAccountManager`` can tell "there is no such account" from "the account exists
# but was provisioned after this boot brought its venue online", and an operator's next
# action is different in each case. Keyed so the remediation is the SPECIFIC one; the
# fallback keeps a future cause honest if its entry is forgotten.
_UNPROVISIONED_ACCOUNT_CAUSE: dict[str, str] = {
    "not_provisioned": (
        "no venue_accounts row exists for this pair. Provision it first "
        "(system.venue_accounts.provision(venue, account_id, ...)), then bring it "
        "online — a provisioned account is usable in the same process, with no restart "
        "(D-27)"
    ),
    "disabled": (
        "the venue_accounts row exists but carries enabled=False, so it was "
        "deliberately excluded from this venue's bring-up. Re-enable the account if it "
        "should trade; a disabled account is never silently brought online"
    ),
    "not_online": (
        "the venue_accounts row exists and is enabled, but this account was never "
        "brought online in this process — it was provisioned after its venue came up. "
        "Call bring_online(row) for it (the same single path boot uses in bulk, D-27) "
        "before resolving an account against it"
    ),
}

_UNPROVISIONED_ACCOUNT_FALLBACK = (
    "this account could not be resolved to a provisioned, enabled, online venue "
    "account. Provision and bring the account online before resolving against it."
)


class VenueAccountNotProvisionedError(PortfolioError):
    """A ``(venue_name, account_id)`` names no live, enabled venue account (ACCT-03, D-21).

    The typed refusal ``VenueAccountManager.account_for`` raises instead of returning an
    account. It is deliberately a REFUSAL and not a fallback: the tempting alternative —
    handing back the compute leaf a portfolio would otherwise have — produces an account
    with ``is_venue_truth=False``, which silently disables the venue snapshot, the fill/
    order streams, ``VenueReconciler`` and the unexplained-residual HALT. The portfolio
    then trades against COMPUTED balances while believing they are the venue's, and every
    guard built to catch that divergence is inert. A loud refusal at resolution time is
    strictly cheaper than a quiet one at settlement time.

    ``account_id`` is matched by EXACT STRING at every layer — no case-folding, trimming
    or Unicode normalization — so ``' okx-1'`` and ``'okx-1'`` are different accounts and
    neither silently resolves to the other. This error is what a near-miss produces.

    Carries the pair and the ``cause`` as structured fields and builds its message in
    ``__init__`` (the project's exception convention). The message names the CONSEQUENCE
    of the alternative and the cause-SPECIFIC REMEDIATION, because the operator's next
    action differs per cause (see ``_UNPROVISIONED_ACCOUNT_CAUSE``).
    """

    #: The three causes ``VenueAccountManager.account_for`` distinguishes (D-21).
    NOT_PROVISIONED = "not_provisioned"
    DISABLED = "disabled"
    NOT_ONLINE = "not_online"

    def __init__(self, venue_name: str, account_id: str, cause: str):
        self.venue_name = venue_name
        self.account_id = account_id
        self.cause = cause
        rationale = _UNPROVISIONED_ACCOUNT_CAUSE.get(
            cause, _UNPROVISIONED_ACCOUNT_FALLBACK)
        super().__init__(
            f"Venue account ({venue_name!r}, {account_id!r}) is not available: "
            f"{rationale}. Refusing to resolve an account for it (ACCT-03): returning a "
            f"compute leaf instead would give the portfolio is_venue_truth=False and "
            f"silently disable the venue snapshot, the fill/order streams, "
            f"VenueReconciler and the unexplained-residual HALT."
        )


class DuplicateVenueAccountProvisionError(PortfolioError):
    """``provision`` named a ``(venue_name, account_id)`` that already exists (ACCT-02/D-11).

    Provisioning is CREATE-ONLY. The database's composite primary key on
    ``(venue_name, account_id)`` is the arbiter, and its ``IntegrityError`` is what this
    exception classifies — there is deliberately NO pre-check ``SELECT``, because a
    pre-check is TOCTOU and, decisively, does not bind the out-of-band writers a durable
    table always has. The same argument is already recorded for the sibling
    ``portfolio_definition_store``.

    It is a SEPARATE type from ``DuplicateVenueAccountError``, which reports two
    PORTFOLIOS colliding on one account and carries both portfolio labels. A provision
    refusal has no portfolios in it — the collision is between an existing row and a new
    write — so reusing that type would mean inventing two portfolio names that do not
    exist. Same table, different collision.

    Refusing rather than overwriting is the point. A silent restatement is how a re-run
    provisioning script replaces the operator's ``secret_ref`` and ``config``, and how the
    engine-written ``venue_uid`` (D-04 trust-on-first-use) gets reset to NULL — which
    disarms the venue-identity guard for that account. Repointing an existing account is
    its own targeted verb, never a side effect of create.

    Carries the colliding pair as structured fields and builds its message in ``__init__``
    (the project's exception convention), naming the consequence and the remediation.
    """

    def __init__(self, venue_name: str, account_id: str):
        self.venue_name = venue_name
        self.account_id = account_id
        super().__init__(
            f"Venue account ({venue_name!r}, {account_id!r}) is already provisioned. "
            f"Refusing to provision it again (D-11): provisioning is create-only, and "
            f"overwriting would silently replace the operator's secret_ref and config "
            f"and clear the engine-written venue_uid, disarming the trust-on-first-use "
            f"venue-identity guard for this account. Use a different account_id, or "
            f"update the existing account through its own targeted verb."
        )

