"""
Error events: the FastAPI-style concrete-base hierarchy (D-06).

``ErrorEvent`` is a concrete, instantiable base carrying the dedicated
``EventType.ERROR`` discriminator (killing the legacy
``type = EventType.UPDATE`` reuse hack); children narrow ``source`` and
add domain-specific fields, mirroring the ``core/exceptions`` hierarchy
shape (concrete base + narrowing children). The whole tree is frozen —
mixing frozen/non-frozen in one inheritance chain is a stdlib TypeError.
"""

from typing import Any, ClassVar

from itrader.core.enums import ErrorSeverity, EventType
from itrader.core.ids import CorrelationId, PortfolioId

from .base import Event


class ErrorEvent(Event, frozen=True, kw_only=True, gc=False):
    """
    Concrete, instantiable error event (D-06).

    Emitted onto the global queue when a component operation fails;
    consumed by the EventHandler's ERROR route (log consumer, Plan 04-06).

    Parameters
    ----------
    source: `str`
        The emitting component/domain, e.g. 'portfolio'.
    error_type: `str`
        The failure's type name, e.g. the exception class name.
    error_message: `str`
        Human-readable failure description.
    operation: `str | None`
        The operation that failed, if known.
    correlation_id: `CorrelationId | None`
        Operation-tracking correlation id (UUIDv7), if any.
    severity: `ErrorSeverity`
        One of ErrorSeverity.ERROR/CRITICAL/WARNING.
    details: `dict | None`
        Optional structured extra context.
    """

    type: ClassVar[EventType] = EventType.ERROR
    source: str
    error_type: str
    error_message: str
    operation: str | None = None
    correlation_id: CorrelationId | None = None
    severity: ErrorSeverity = ErrorSeverity.ERROR
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        base = f"{self.type} ({self.source}): {self.error_type} - {self.error_message}"
        if self.operation:
            base += f" (Operation: {self.operation})"
        return base

    def __repr__(self) -> str:
        return str(self)


class PortfolioErrorEvent(ErrorEvent, frozen=True, kw_only=True, gc=False):
    """
    Portfolio-domain error event for monitoring and alerting.

    Narrows ``source`` to 'portfolio' and adds the failing portfolio's id
    (when known). Field names match the legacy event so the
    ``PortfolioHandler._publish_error_event`` construction site changes
    minimally at the Plan 04-05 cutover.
    """

    source: str = "portfolio"
    portfolio_id: PortfolioId | None = None

    def __str__(self) -> str:
        base = f"{self.type} ({self.source}): {self.error_type} - {self.error_message}"
        if self.portfolio_id:
            base += f" (Portfolio: {self.portfolio_id})"
        if self.operation:
            base += f" (Operation: {self.operation})"
        return base

    def __repr__(self) -> str:
        return str(self)
