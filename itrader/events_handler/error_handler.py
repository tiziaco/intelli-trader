"""ErrorHandler — the formalized ERROR-route consumer (D-01).

Lifts the ``full_event_handler.py::_log_error_event`` body VERBATIM (re-indented
tab→4-space) into a standalone, composition-friendly consumer so the ERROR route
becomes ``EventType.ERROR: [self.error_handler.on_error]`` (08-03). This is the
CONSUMER side of the WR-06 two-guard terminal safety: the whole ``on_error`` body
is wrapped in a ``try/except`` that swallows (inner ``try/except: pass`` last-resort
log) so a raising alert-sink / logger / SQL upsert / record_failure can NEVER escape
into ``_dispatch`` — whose live policy would republish a fresh ErrorEvent routed
straight back here (an unbounded error→error feedback loop). The source-side guard
lives in ``error_policy.py::ErrorPolicy.on_handler_error``.

Collaborators are INJECTED and HELD, never constructed (D-03/D-04): a CRITICAL
alert-sink egress, a durable ``SystemStore`` for the D-17 ``state.last_error``
persist, and a ``failure_sink`` (the shared ``ErrorPolicy`` tripwire surface) for
the off-thread okx FILL_TRANSLATION event. All are ``None`` on the backtest path
(no egress / no SQL / no tripwire wired) — a no-op, inertness preserved.

Layering: this module imports stdlib + core/enums + ``error_policy.classify_failure``
ONLY. ``alert_sink``/``system_store`` are NEVER runtime-imported here (a
``trading_system.alert_sink`` edge would invert layering; ``storage.system_store`` is
in the OKX-inertness _FORBIDDEN list) — ``alert_sink`` is typed by a local duck-typed
Protocol, ``system_store``/``failure_sink`` as ``Any``.

Secret discipline (T-05-27 / V7): both the log bind and the persisted dict bind ONLY
declared ErrorEvent fields — never ``str(exc)`` / raw connector payload.

Indentation: 4 SPACES (matches the ``events_handler/events/*`` package).
"""

from datetime import datetime, UTC
from typing import TYPE_CHECKING, Any, Protocol

from itrader.core.enums import ErrorSeverity
from itrader.events_handler.error_policy import classify_failure
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    # Type-only: the events package pulls pandas at runtime; keep the annotation
    # light. ``ErrorEvent`` is the consumed event shape.
    from itrader.events_handler.events import ErrorEvent


class _AlertSinkLike(Protocol):
    """Duck-typed alert-sink egress surface (D-03/D-06).

    Structurally matches the composition-root ``AlertSink`` Protocol WITHOUT a
    runtime dependency on it — a reverse layer edge would invert the layering
    (the composition root wires the alert-sink layer on TOP of the event handler).
    The concrete ``LogAlertSink`` is injected at live wiring; the attribute stays
    ``None`` on the backtest path (no egress, inertness preserved).
    """

    def alert(self, event: "ErrorEvent") -> None: ...


class ErrorHandler:
    """The ERROR route's consumer (D-01): severity-mapped log + escalation + persist.

    Parameters
    ----------
    alert_sink:
        CRITICAL/halt egress (``LogAlertSink``); ``None`` on the backtest path.
    system_store:
        Durable KV store for the D-17 ``state.last_error`` persist; ``None`` in
        backtest (no-op). Typed ``Any`` — no runtime import of ``storage.system_store``
        (it is in the OKX-inertness _FORBIDDEN list).
    failure_sink:
        The shared ``ErrorPolicy`` tripwire surface (exposes ``record_failure``);
        the off-thread okx FILL_TRANSLATION ErrorEvent counts through it. ``None`` in
        backtest. Typed ``Any`` — held, not constructed.
    """

    def __init__(
        self,
        alert_sink: "_AlertSinkLike | None" = None,
        system_store: Any = None,
        failure_sink: Any = None,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="ErrorHandler")
        self._alert_sink = alert_sink
        self._system_store = system_store
        self._failure_sink = failure_sink

    def on_error(self, event: "ErrorEvent") -> None:
        """Consume an ERROR-route event: log, escalate, persist, count (D-01/D-17).

        Binds the ErrorEvent fields explicitly at a severity mapped from
        ``event.severity`` (WARNING/CRITICAL/anything else → ERROR). Never logs or
        persists secrets — only the declared ErrorEvent fields.
        """
        # WR-06: the ERROR route is TERMINAL. A failure WHILE consuming an ErrorEvent —
        # a raising alert sink, a broken logger/structlog processor, a SQL upsert
        # failure, or a raising record_failure — must NEVER escape into _dispatch,
        # whose live policy (ErrorPolicy.on_handler_error) would republish a fresh
        # ErrorEvent routed straight back here: an unbounded error→error feedback loop
        # flooding the engine-thread queue. Log once (best-effort) and swallow; the
        # consumer never re-raises into the dispatcher. (The source guard in
        # ErrorPolicy guards the seam too; this is defense-in-depth so the recursion is
        # impossible either way.)
        try:
            log_method = {
                ErrorSeverity.WARNING: self.logger.warning,
                ErrorSeverity.CRITICAL: self.logger.critical,
            }.get(event.severity, self.logger.error)
            context: dict[str, Any] = {
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
            log_method("Error event consumed", **context)

            # D-06: escalate a CRITICAL/halt event through the injected alert-sink
            # egress (RES-01), AFTER the existing log call. The sink re-binds only
            # declared ErrorEvent fields — the same secret-scrub discipline as above,
            # so no raw connector context / secret ever leaves (Pitfall 16, T-05-01).
            # ``None`` on the backtest path (no egress wired) — a no-op branch.
            if event.severity is ErrorSeverity.CRITICAL and self._alert_sink is not None:
                self._alert_sink.alert(event)

            # D-17: persist ``state.last_error`` (last-write-wins) via the injected
            # durable store — LIVE only. Bind ONLY declared, scrubbed ErrorEvent fields
            # (never str(exc)/raw payload, T-05-27); the correlation id is stringified
            # for JSON portability. ``None`` on the backtest path — a no-op branch.
            # This sits INSIDE the WR-06 guard so a SQL-write failure is swallowed.
            if self._system_store is not None:
                persisted: dict[str, Any] = {
                    "source": event.source,
                    "error_type": event.error_type,
                    "error_message": event.error_message,
                    "operation": event.operation,
                    "correlation_id": (
                        str(event.correlation_id)
                        if event.correlation_id is not None
                        else None
                    ),
                    "severity": event.severity.value,
                }
                if portfolio_id is not None:
                    persisted["portfolio_id"] = portfolio_id
                if event.details is not None:
                    persisted["details"] = event.details
                at = getattr(event, "time", None) or datetime.now(UTC)
                self._system_store.upsert("state.last_error", persisted, at=at)

            # ERR-04 shared counting seam: the off-thread okx FILL_TRANSLATION
            # ErrorEvent (source="okx_exchange", operation="fill-translation") counts
            # into the SAME ErrorPolicy tripwire via record_failure — no second breaker
            # object. Every other ERROR event classifies to None (already counted
            # upstream by on_handler_error) and is NOT re-counted. Inside the WR-06
            # guard so a raising record_failure is swallowed too. ``None`` in backtest.
            if self._failure_sink is not None:
                failure_class = classify_failure(event)
                if failure_class is not None:
                    self._failure_sink.record_failure(failure_class)
        except Exception:
            # Last-resort recovery log is itself wrapped: if the primary logger is
            # what failed, this inner attempt must not re-raise either.
            try:
                self.logger.error(
                    "ERROR-route consumer failed; swallowed to prevent "
                    "error->error recursion (WR-06)",
                    exc_info=True,
                )
            except Exception:
                pass
