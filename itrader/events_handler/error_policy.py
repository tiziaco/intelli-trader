"""ErrorPolicy — the live publish-and-continue handler-failure seam + CF-1 tripwire.

RELOCATED (D-02) from the ``trading_system`` package to sit BESIDE the dispatcher
(``full_event_handler.py``) so BOTH ERROR-route guards' source sides live in one
package: the WR-06 source guard here (don't republish/count a failing ErrorEvent)
pairs with the WR-06 consumer guard in ``error_handler.py``.

Carries the LIVE handler-failure policy: today's
``LiveTradingSystem._publish_and_continue`` (the WR-05/WR-06 body) moved VERBATIM
into a standalone, composition-friendly object so ``LiveRunner``/``build_live_system``
can inject it (D-07). It overrides the base ``EventHandler._on_handler_error``
(fail-fast re-raise) on the daemon/live path ONLY — a live session can't abort on
one handler error; it emits an ``ErrorEvent`` and keeps draining. The offline
deterministic parity driver keeps the base fail-fast re-raise so the parity gate
can never false-green on a swallowed error (D-17/WR-04/D-19, T-05-28).

This module also holds the D-06 ``HandlerErrorPolicy`` Protocol + ``FailFastPolicy``
(the backtest fail-fast arm of the injected policy interface). ``FailFastPolicy``'s
body is a bare ``raise`` — the ORACLE-SAFETY-critical seam: a bare ``raise`` inside
a function called from ``_dispatch``'s except block re-raises the active exception
identically, so the backtest run stays byte-exact.

The publish target (``bus``) is an INJECTED constructor dependency (not a facade
back-reference / global). The optional ``error_counter`` callback preserves the
facade's ``_stats['errors_count']`` bookkeeping when wired; it defaults to a
no-op so the policy is standalone. Import-inert: stdlib + core/enums + the events
package (pandas-on-backtest-graph only) — no ccxt.pro / async / SQL.

Indentation: 4 SPACES (matches the ``live_trading_system.py`` donor).
"""

import sys
import time
from collections import deque
from datetime import datetime, UTC
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
    Protocol,
    runtime_checkable,
)

from itrader.core.enums import ErrorSeverity, FailureClass, HaltReason
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import EventType, ErrorEvent
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    # Type-only: reading FailureRateSettings duck-typed at runtime avoids a hard
    # config→events_handler import edge (the fields are read via getattr). The
    # config.safety module is pydantic-only, but keeping the edge type-only mirrors
    # the alert_sink/system_store DI discipline (no runtime layer inversion).
    from itrader.config.safety import FailureRateSettings


# D-09 Option A — the declarative route→FailureClass map (routing-is-data, mirrors
# the EventHandler.routes literal). Keyed on EventType; an unmapped non-ERROR type
# defaults to LOOP_BACKSTOP. An ERROR-typed event is NOT keyed here (its type is
# ERROR, which would wrongly default to LOOP_BACKSTOP) — it is refined by
# (source, operation) in classify_failure so only the okx fill-translation event
# counts as FILL_TRANSLATION.
_ROUTE_CLASS: dict[EventType, FailureClass] = {
    EventType.FILL: FailureClass.SETTLEMENT,
    EventType.ORDER: FailureClass.ORDER_IO,
    EventType.SIGNAL: FailureClass.ADMISSION,
}

# D-11/D-14 — the per-FailureClass policy field map: (threshold_attr, window_attr,
# default_threshold, default_window, HaltReason). SETTLEMENT & FILL_TRANSLATION share
# the settlement (threshold, window) pair and the SETTLEMENT_FAILURE halt reason (a
# lost venue fill IS a settlement loss, halt-on-first). The defaults are the exact
# D-14 ROADMAP values, carried in-module so a None failure_settings still arms the
# tripwire without a runtime config import.
_POLICY_FIELDS: dict[FailureClass, tuple[str, str, int, float, HaltReason]] = {
    FailureClass.SETTLEMENT: (
        "settlement_threshold", "settlement_window_s", 1, 60.0,
        HaltReason.SETTLEMENT_FAILURE,
    ),
    FailureClass.FILL_TRANSLATION: (
        "settlement_threshold", "settlement_window_s", 1, 60.0,
        HaltReason.SETTLEMENT_FAILURE,
    ),
    FailureClass.ORDER_IO: (
        "order_io_threshold", "order_io_window_s", 3, 60.0,
        HaltReason.ORDER_ROUTE_ERRORS,
    ),
    FailureClass.ADMISSION: (
        "admission_threshold", "admission_window_s", 3, 300.0,
        HaltReason.ADMISSION_ERRORS,
    ),
    FailureClass.LOOP_BACKSTOP: (
        "loop_backstop_threshold", "loop_backstop_window_s", 5, 60.0,
        HaltReason.LOOP_BACKSTOP,
    ),
}


def should_trip(
    hits: "deque[float]", threshold: int, window: float, now: float
) -> bool:
    """Sliding-window tripwire predicate (D-07/D-11) — one-way, no auto-reset.

    Append ``now``, prune every hit at or before ``now - window`` (outside the
    window), and return whether the surviving hit count has reached ``threshold``.
    At ``threshold == 1`` the first call returns True (SETTLEMENT halt-on-first);
    hits spaced further than ``window`` apart never accumulate to the threshold.
    ``now`` is injectable so the trip is deterministic in tests (no wall clock).
    """
    hits.append(now)
    cutoff = now - window
    while hits and hits[0] <= cutoff:
        hits.popleft()
    return len(hits) >= threshold


def classify_failure(event: Any) -> "FailureClass | None":
    """Classify a failing event into a FailureClass (D-09 Option A), or None.

    FILL→SETTLEMENT, ORDER→ORDER_IO, SIGNAL→ADMISSION, any other non-ERROR type→
    LOOP_BACKSTOP. An ERROR-typed event is refined by ``(source, operation)`` and
    returns FILL_TRANSLATION ONLY for the okx fill-translation event; every other
    ERROR event returns None so downstream ErrorEvents already counted by
    ``on_handler_error`` are not double-counted.
    """
    event_type: Any = getattr(event, "type", None)
    if event_type is EventType.ERROR:
        source = getattr(event, "source", None)
        operation = getattr(event, "operation", None)
        if (source, operation) == ("okx_exchange", "fill-translation"):
            return FailureClass.FILL_TRANSLATION
        return None
    return _ROUTE_CLASS.get(event_type, FailureClass.LOOP_BACKSTOP)


@runtime_checkable
class HandlerErrorPolicy(Protocol):
    """Structural handler-failure policy seam (D-06).

    The swap-a-policy contract the EventHandler routes a raising handler through
    from ``_dispatch``'s except block. A single method — ``on_handler_error`` —
    so the backtest fail-fast arm (``FailFastPolicy``) and the live
    publish-and-continue arm (``ErrorPolicy``) are interchangeable at wiring
    WITHOUT a runtime dependency on either concrete. Modelled on the
    ``alert_sink.py::AlertSink`` runtime_checkable Protocol shape; method body is
    ``...`` (a contract, not a base class).
    """

    def on_handler_error(self, event: Any, handler: Any) -> None: ...


class FailFastPolicy:
    """Backtest fail-fast handler-failure policy (D-06) — bare ``raise``.

    ORACLE-SAFETY-critical: ``on_handler_error`` re-raises the active
    except-block exception UNCHANGED. Because it is called from inside
    ``_dispatch``'s ``except Exception:`` block, a bare ``raise`` re-raises the
    exception context identically to the pre-refactor inline ``_on_handler_error``
    body — a handler failure aborts the backtest run rather than silently
    corrupting state (T-04-15), and the byte-exact oracle is preserved.
    """

    def on_handler_error(self, event: Any, handler: Any) -> None:
        """Fail-fast: re-raise the active exception unchanged (oracle byte-exact)."""
        raise


class ErrorPolicy:
    """Live publish-and-continue handler-failure policy (WR-05, WR-06 guard intact).

    ``on_handler_error(event, handler)`` matches the signature the EventHandler
    expects for its policy seam; a bound reference to it is what
    ``build_live_system`` installs on the daemon/live path. The bus/queue the
    ErrorEvent is published onto is injected — no facade God-object reference.
    """

    def __init__(
        self,
        bus: EventBus,
        error_counter: Optional[Callable[[], None]] = None,
        *,
        failure_settings: "FailureRateSettings | None" = None,
        halt: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.logger = get_itrader_logger().bind(component="ErrorPolicy")
        self._bus = bus
        # Preserves the facade's ``with self._stats_lock: _stats['errors_count'] += 1``
        # bookkeeping when wired (06-05); a no-op keeps the policy standalone here.
        self._error_counter = error_counter
        # D-12 — the tripwire's terminal action: a same-thread direct call into the
        # SafetyController's ``halt(reason: str)``. Injected at wiring (08-03) or late
        # via ``bind``; a None halt (unwired / backtest) makes ``record_failure`` a
        # no-op. ``halt`` keeps its ``str`` signature — the tripwire passes the typed
        # HaltReason's ``.value`` wire string (the full ``halt(reason: HaltReason)``
        # signature migration across all callers is a separate tidy-up, out of ERR scope).
        self._halt = halt
        # D-11 — the tripwire state lives ON ErrorPolicy (no dedicated breaker class,
        # no state machine, no auto-reset). One hit-deque per FailureClass; the policy
        # tuple ``(threshold, window, HaltReason)`` is built once from failure_settings
        # (duck-typed, defaults carried in _POLICY_FIELDS so a None settings still arms).
        self._policy: dict[FailureClass, tuple[int, float, HaltReason]] = {}
        self._hits: dict[FailureClass, "deque[float]"] = {}
        # D-13 — the last-trip HaltReason wire string, surfaced (read-only) through the
        # live facade get_status breaker snapshot. None until the tripwire first trips.
        self._last_trip: Optional[str] = None
        for failure_class, (
            threshold_attr,
            window_attr,
            default_threshold,
            default_window,
            reason,
        ) in _POLICY_FIELDS.items():
            if failure_settings is not None:
                threshold = int(getattr(failure_settings, threshold_attr, default_threshold))
                window = float(getattr(failure_settings, window_attr, default_window))
            else:
                threshold, window = default_threshold, default_window
            self._policy[failure_class] = (threshold, window, reason)
            self._hits[failure_class] = deque()

    def bind(
        self,
        *,
        halt: Optional[Callable[[str], None]] = None,
        error_counter: Optional[Callable[[], None]] = None,
    ) -> None:
        """Late-wire the halt / error-counter collaborators (D-12).

        08-03 constructs ErrorPolicy at compose time (before ``safety`` / the facade
        exist) then binds ``halt=safety.halt`` + ``error_counter`` once they do — the
        collaborators are only needed when a failure actually occurs at runtime, well
        after wiring. Only non-None arguments overwrite the held reference.
        """
        if halt is not None:
            self._halt = halt
        if error_counter is not None:
            self._error_counter = error_counter

    def record_failure(
        self, failure_class: FailureClass, now: Optional[float] = None
    ) -> None:
        """Count one failure into the shared tripwire; halt if the window trips (D-11/D-12).

        The SHARED counter surface (Open-Q#1 resolution): both the routed-handler seam
        (``on_handler_error``) and the off-thread ERROR-route consumer
        (``ErrorHandler.on_error``, for the okx fill-translation event) call this — one
        classification map, one hit-deque set, one halt. A None halt (unwired / backtest)
        records the hit but never halts. ``now`` defaults to a monotonic clock read.
        """
        if now is None:
            now = time.monotonic()
        threshold, window, reason = self._policy[failure_class]
        if should_trip(self._hits[failure_class], threshold, window, now):
            # Record the trip (D-13 get_status surface) regardless of whether ``halt`` is
            # wired — the windowed threshold was reached; that IS the trip.
            self._last_trip = reason.value
            if self._halt is not None:
                self._halt(reason.value)

    def breaker_snapshot(self) -> dict[str, Any]:
        """Read-only CF-1 tripwire snapshot for the live facade get_status (D-13).

        Returns a plain JSON-friendly dict — the current in-window hit count per
        ``FailureClass`` plus the last-trip ``HaltReason`` wire string (``None`` until the
        first trip). P8 scope is get_status ONLY; the SystemStore stats read-model is P9
        (RTCFG-06). No lock: the *writes* to ``self._hits`` are single-threaded (engine
        thread, via ``should_trip``/``record_failure``); this reader, however, runs on a
        *different* thread — ``LiveTradingSystem.get_status`` is a public status API invoked
        by external/web callers. Under CPython the GIL makes each ``len()``/``append`` atomic,
        so this is a best-effort GIL-atomic cross-thread read: it cannot crash or corrupt, but
        the per-class counts may be momentarily inconsistent with a concurrent trip (WR-01).
        """
        return {
            "hits": {fc.value: len(self._hits[fc]) for fc in self._hits},
            "last_trip_reason": self._last_trip,
        }

    def on_handler_error(self, event: Any, handler: Any) -> None:
        """Live handler-failure policy (WR-05): publish an ErrorEvent, keep draining.

        Overrides the base EventHandler._on_handler_error (fail-fast re-raise).
        Invoked from EventHandler._dispatch when a handler raises; emits an
        ErrorEvent onto the queue (consumed by the ERROR route) and returns so
        the loop continues. Reads the active exception via sys.exc_info().
        """
        # IN-01: sys and ErrorEvent are module-level imports (top of file). The
        # deferred-import rationale (keep the events package out of the dispatcher's
        # import graph) does not apply to THIS module — it already imports
        # EventType/ErrorEvent from the same package at module scope, so re-importing
        # on every handler failure on the hot error path bought nothing.
        exc = sys.exc_info()[1]
        handler_name = getattr(handler, '__qualname__', repr(handler))
        self.logger.error(
            f'Handler {handler_name} failed on {getattr(event, "type", "UNKNOWN")}: {exc}'
        )
        # WR-06: the ERROR route is TERMINAL. If the FAILING event is itself an
        # ErrorEvent, publishing a fresh ErrorEvent would route it straight back to
        # the same failing ERROR-route consumer — an unbounded error->error feedback
        # loop flooding the engine-thread queue (and, when the failure repeats on the
        # re-consumed event, livelocking a single process_events() drain forever). The
        # failure is already logged once above; stop here rather than republish. The
        # tripwire count/classify (Task 2) MUST sit AFTER this return so a
        # COSMETIC/ERROR-type failure is never counted.
        # IN-01: the errors_count bump (below) also sits after this guard so a
        # swallowed ERROR-route consumer failure is a COMPLETE bookkeeping no-op —
        # it does not conflate primary-handler failures with terminal-route failures.
        if getattr(event, 'type', None) is EventType.ERROR:
            return
        if self._error_counter is not None:
            self._error_counter()
        self._bus.put(ErrorEvent(
            # WR-05: prefer the event's own business time; fall back to a
            # tz-aware UTC wall clock (never naive) to stay consistent with the
            # datetime.now(UTC) convention used by the portfolio handler.
            time=getattr(event, 'time', datetime.now(UTC)),
            source='live_trading_system',
            error_type=type(exc).__name__ if exc is not None else 'UnknownError',
            error_message=str(exc) if exc is not None else 'unknown handler failure',
            operation=handler_name,
            severity=ErrorSeverity.ERROR,
        ))
        # D-11/D-14 tripwire count — AFTER the WR-06 source-guard return (a
        # COSMETIC/ERROR-type failure is NEVER counted) and after the publish +
        # error_counter. Classify the FAILING event's route and, when it maps to a
        # FailureClass, count it into the shared tripwire: a FILL handler failing
        # trips SETTLEMENT on the first event (ERR-03 hard criterion, no clock needed).
        failure_class = classify_failure(event)
        if failure_class is not None:
            self.record_failure(failure_class)
