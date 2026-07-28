from enum import Enum


class ExecutionStatus(Enum):
    SUCCESS = "success"
    PARTIAL_FILL = "partial_fill"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_SYMBOL = "invalid_symbol"
    MARKET_CLOSED = "market_closed"


class ExecutionErrorCode(Enum):
    NO_ERROR = "no_error"
    INVALID_ORDER = "invalid_order"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    EXCHANGE_ERROR = "exchange_error"
    NETWORK_ERROR = "network_error"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    MARKET_CLOSED = "market_closed"
    ORDER_SIZE_TOO_SMALL = "order_size_too_small"
    ORDER_SIZE_TOO_LARGE = "order_size_too_large"
    INVALID_PRICE = "invalid_price"
    EXCHANGE_MAINTENANCE = "exchange_maintenance"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    # The order names a portfolio the engine does not know (``account_for`` ->
    # ``get_portfolio`` raised ``PortfolioNotFoundError``). Operator fix: the
    # order's ``portfolio_id`` is wrong or that portfolio was never registered.
    # A distinct code (not the ``INVALID_ORDER`` misnomer) keeps this class of
    # silent-drop greppable in the event stream and the mirror.
    UNKNOWN_PORTFOLIO = "unknown_portfolio"
    # No exchange is registered for this ``(venue, account_id)`` pair, so the
    # order cannot be routed to a session. Operator fix: bring the account
    # online / seed the exchange registry for that venue — the routing map is
    # misconfigured, not the order. Distinct from the ``EXCHANGE_ERROR``
    # misnomer (which means the venue itself failed).
    UNREGISTERED_VENUE_ACCOUNT = "unregistered_venue_account"


class ExchangeConnectionStatus(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    DISCONNECTING = "disconnecting"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class ExchangeType(Enum):
    SIMULATED = "simulated"
    LIVE = "live"
    PAPER = "paper"
    SANDBOX = "sandbox"


class FillStatus(Enum):
    """Execution-truth fill status emitted by the exchange.

    Kept DISTINCT from ``OrderStatus`` (the order mirror): the
    ``FillStatus.EXECUTED -> OrderStatus.FILLED`` mapping in the reconcile module
    is the intended exchange-truth -> mirror reconciliation and must be preserved.
    """
    EXECUTED = "EXECUTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

    @classmethod
    def _missing_(cls, value: object) -> "FillStatus":
        """Case-insensitive string parse; raise a clear f-string error.

        Invoked by ``FillStatus(value)`` on lookup failure.
        """
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown FillStatus: {value!r}")
