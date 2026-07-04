"""
Pluggable alert-sink egress for CRITICAL/halt escalation (D-06, RES-01).

A halt or unrecoverable error escalates to a CRITICAL ``ErrorEvent``; that event
must reach an operator through a swappable egress seam so an external channel
(PagerDuty/Slack/webhook) drops in later WITHOUT touching the event-handler code
that emits it. This milestone ships ONE implementation — ``LogAlertSink`` — which
emits a marked structured ``logger.critical``; external push is deferred (RES-01).

``AlertSink`` follows the ``connectors/base.py::LiveConnector`` swap-a-fake seam
pattern (a ``runtime_checkable Protocol``, not an ABC — there is no shared body to
inherit; tests inject a structural fake). Indent: 4 spaces (matches
``trading_system/`` siblings).

Secret discipline (Pitfall 16, T-05-01): the sink emits ONLY the declared
``ErrorEvent`` fields — it never reaches into raw connector context, so
``SecretStr`` credentials (OKX key/secret/passphrase) can never leak to logs. The
``ErrorEvent`` boundary is the scrub point; the sink trusts it.

``ErrorEvent`` is imported under ``TYPE_CHECKING`` only — the events package pulls
pandas at runtime, and ``alert_sink`` must stay import-light so wiring it never
drags heavy deps onto a cold path.
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.events_handler.events import ErrorEvent

__all__ = ["AlertSink", "LogAlertSink"]


@runtime_checkable
class AlertSink(Protocol):
    """Structural egress seam for CRITICAL/halt alerts (D-06).

    The swap-a-fake contract the event handler routes CRITICAL ``ErrorEvent``s
    through. A single method — ``alert`` — so an external channel implementation
    drops in without any change to the emitting code. Method body is ``...``:
    this is a contract, not a base class.
    """

    def alert(self, event: "ErrorEvent") -> None:
        """Escalate a CRITICAL ``ErrorEvent`` to the operator egress channel."""
        ...


class LogAlertSink:
    """The ONLY alert-sink implementation this milestone (external push deferred, RES-01).

    Emits a marked structured ``logger.critical`` binding ONLY the declared
    ``ErrorEvent`` fields (never raw connector context — secrets stay scrubbed,
    Pitfall 16 / T-05-01). ``alert=True`` marks the record so a later log-shipping
    channel can filter escalations without re-parsing severity.
    """

    def __init__(self) -> None:
        self.logger = get_itrader_logger().bind(component="LogAlertSink")

    def alert(self, event: "ErrorEvent") -> None:
        """Emit the CRITICAL escalation as a marked structured critical log.

        Binds only the declared ``ErrorEvent`` fields; ``portfolio_id`` and
        ``details`` are optional narrowing fields bound when present. No raw
        venue/connector context is ever read here.
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
