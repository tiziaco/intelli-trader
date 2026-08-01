"""
Pluggable alert-sink egress for CRITICAL/halt escalation.

A halt or unrecoverable error escalates to a CRITICAL ``ErrorEvent``; that event must
reach an operator through a swappable egress seam so an external channel
(PagerDuty/Slack/webhook) drops in later WITHOUT touching the event-handler code that
emits it. ``LogAlertSink`` is the one shipped implementation — it emits a marked
structured ``logger.critical``.

``AlertSink`` is a ``runtime_checkable Protocol``, not an ABC: there is no shared body to
inherit, and tests inject a structural fake.

Secret discipline: the sink emits ONLY the declared ``ErrorEvent`` fields — it never
reaches into raw connector context, so ``SecretStr`` credentials (OKX key / secret /
passphrase) can never leak to logs. The ``ErrorEvent`` boundary is the scrub point and
the sink trusts it.

``ErrorEvent`` is imported under ``TYPE_CHECKING`` only — the events package pulls pandas
at runtime, and ``alert_sink`` must stay import-light so wiring it never drags heavy deps
onto a cold path.
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.events_handler.events import ErrorEvent

__all__ = ["AlertSink", "LogAlertSink"]


@runtime_checkable
class AlertSink(Protocol):
    """Structural egress seam for CRITICAL/halt alerts.

    A single method, so an external channel implementation drops in without any change to
    the emitting code. The method body is ``...``: this is a contract, not a base class.
    """

    def alert(self, event: "ErrorEvent") -> None:
        """Escalate a CRITICAL ``ErrorEvent`` to the operator egress channel."""
        ...


class LogAlertSink:
    """The shipped alert-sink implementation.

    Emits a marked structured ``logger.critical`` binding ONLY the declared ``ErrorEvent``
    fields, never raw connector context. ``alert=True`` marks the record so a later
    log-shipping channel can filter escalations without re-parsing severity.
    """

    def __init__(self) -> None:
        self.logger = get_itrader_logger().bind(component="LogAlertSink")

    def alert(self, event: "ErrorEvent") -> None:
        """Emit the CRITICAL escalation as a marked structured critical log.

        ``portfolio_id`` and ``details`` are optional narrowing fields bound when present.
        """
        context: dict[str, Any] = {
            "alert": True,
            "source": event.source,
            "error_type": event.error_type,
            "error_message": event.error_message,
            "operation": event.operation,
            "correlation_id": event.correlation_id,
        }
        portfolio_id = getattr(event, "portfolio_id", None)
        if portfolio_id is not None:
            context["portfolio_id"] = portfolio_id
        if event.details is not None:
            context["details"] = event.details
        self.logger.critical("Alert escalated", **context)
