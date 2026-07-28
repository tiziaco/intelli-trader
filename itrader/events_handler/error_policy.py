"""The handler-failure policy seam: ``HandlerErrorPolicy`` and its two arms.

``EventHandler`` owns no failure policy of its own — ``_dispatch`` routes a raising
handler through the injected policy. ``FailFastPolicy`` is the backtest/replay arm
(bare re-raise); ``ErrorPolicy`` is the live arm, which publishes an ``ErrorEvent``
and keeps draining because a live session can't abort on one handler error. The
offline deterministic parity driver wires ``FailFastPolicy`` so the parity gate can
never false-green on a swallowed error.

This module sits beside the dispatcher so both ERROR-route guards' source sides live
in one package: the source guard here (never republish a failing ``ErrorEvent``)
pairs with the consumer guard in ``error_handler.py``.

Import-inert: stdlib + core/enums + the events package — no ccxt.pro / async / SQL
(GATE-01).
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
    # Type-only: the settings fields are read via getattr at runtime, so no
    # config→events_handler runtime import edge is created (no layer inversion).
    from itrader.config.safety import FailureRateSettings


# Declarative route→FailureClass map; an unmapped non-ERROR type defaults to
# LOOP_BACKSTOP. EventType.ERROR is deliberately NOT keyed here — keying it would
# make every ErrorEvent default to LOOP_BACKSTOP; classify_failure refines it by
# (source, operation) instead.
_ROUTE_CLASS: dict[EventType, FailureClass] = {
    EventType.FILL: FailureClass.SETTLEMENT,
    EventType.ORDER: FailureClass.ORDER_IO,
    EventType.SIGNAL: FailureClass.ADMISSION,
}

# Per-FailureClass policy: (threshold_attr, window_attr, default_threshold,
# default_window, HaltReason). SETTLEMENT and FILL_TRANSLATION share the settlement
# pair and halt reason — a lost venue fill IS a settlement loss, halt-on-first. The
# defaults are carried in-module so a None failure_settings still arms the tripwire
# without a runtime config import.
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
    """Sliding-window tripwire predicate — one-way, no auto-reset.

    Appends ``now``, prunes every hit at or before ``now - window``, and returns
    whether the surviving hit count has reached ``threshold``. At ``threshold == 1``
    the first call returns True; hits spaced further apart than ``window`` never
    accumulate. ``now`` is a parameter, not a clock read, so the trip is
    deterministic under test.
    """
    hits.append(now)
    cutoff = now - window
    while hits and hits[0] <= cutoff:
        hits.popleft()
    return len(hits) >= threshold


def classify_failure(event: Any) -> "FailureClass | None":
    """Classify a failing event into a ``FailureClass``, or None.

    FILL→SETTLEMENT, ORDER→ORDER_IO, SIGNAL→ADMISSION, any other non-ERROR type→
    LOOP_BACKSTOP. An ERROR-typed event returns FILL_TRANSLATION only for the okx
    fill-translation event; every other ERROR event returns None, because a failure
    that already produced an ErrorEvent was counted by ``on_handler_error``.
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
    """Structural handler-failure policy seam.

    The contract ``EventHandler._dispatch`` routes a raising handler through from
    its except block. Structural, so the fail-fast and publish-and-continue arms are
    interchangeable at wiring without a runtime dependency on either concrete.
    """

    def on_handler_error(self, event: Any, handler: Any) -> None: ...


class FailFastPolicy:
    """Backtest fail-fast handler-failure policy — bare ``raise``.

    Oracle-safety-critical. Called from inside ``EventHandler._dispatch``'s
    ``except Exception:`` block, a bare ``raise`` re-raises the ACTIVE exception with
    its context intact — wrapping or re-raising a new exception would change the
    abort path. A handler failure aborts the backtest run rather than silently
    corrupting state, and the byte-exact oracle is preserved.
    """

    def on_handler_error(self, event: Any, handler: Any) -> None:
        raise


class ErrorPolicy:
    """Live publish-and-continue handler-failure policy + the failure-rate tripwire.

    Wired as the dispatcher's ``HandlerErrorPolicy`` on the daemon/live path, and
    shared with ``ErrorHandler`` as its failure sink. The bus the ErrorEvent is
    published onto is injected — no facade back-reference.
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
        # Bumps the live facade's errors_count when wired; a None counter keeps the
        # policy standalone.
        self._error_counter = error_counter
        # The tripwire's terminal action: a same-thread direct call into
        # ``SafetyController.halt``, which takes the HaltReason's ``.value`` wire
        # string. A None halt (unwired / backtest) records hits but never halts.
        self._halt = halt
        # Tripwire state lives ON the policy — no breaker class, no state machine, no
        # auto-reset. One hit-deque per FailureClass; the (threshold, window,
        # HaltReason) tuple is resolved once at construction, duck-typed off
        # failure_settings with the _POLICY_FIELDS defaults.
        self._policy: dict[FailureClass, tuple[int, float, HaltReason]] = {}
        self._hits: dict[FailureClass, "deque[float]"] = {}
        # Last-trip HaltReason wire string; None until the tripwire first trips.
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
        """Late-wire the halt / error-counter collaborators.

        The policy is constructed before ``SafetyController`` and the live facade
        exist, which is what makes construction-time injection of these two
        impossible; both are only needed once a failure actually occurs. Only
        non-None arguments overwrite the held reference.
        """
        if halt is not None:
            self._halt = halt
        if error_counter is not None:
            self._error_counter = error_counter

    def record_failure(
        self, failure_class: FailureClass, now: Optional[float] = None
    ) -> None:
        """Count one failure into the shared tripwire; halt if the window trips.

        The one counter surface: both ``on_handler_error`` and the ERROR-route consumer
        ``ErrorHandler.on_error`` call it, so a failure is counted against one hit-deque
        set and one halt rather than two independent breakers. A None halt (unwired /
        backtest) records the hit but never halts. ``now`` defaults to a monotonic
        clock read.
        """
        if now is None:
            now = time.monotonic()
        threshold, window, reason = self._policy[failure_class]
        if should_trip(self._hits[failure_class], threshold, window, now):
            # Recorded regardless of whether ``halt`` is wired — the windowed threshold
            # was reached; that IS the trip.
            self._last_trip = reason.value
            if self._halt is not None:
                self._halt(reason.value)

    def breaker_snapshot(self) -> dict[str, Any]:
        """Read-only tripwire snapshot for ``LiveTradingSystem.get_status``.

        Returns a JSON-friendly dict — the current in-window hit count per
        ``FailureClass`` plus the last-trip ``HaltReason`` wire string (``None`` until
        the first trip). Deliberately unlocked: the writes to ``self._hits`` are
        single-threaded (engine thread, via ``record_failure``), while this reader runs
        on the caller's thread, so it is a best-effort GIL-atomic cross-thread read —
        it cannot crash or corrupt, but the per-class counts may be momentarily
        inconsistent with a concurrent trip.
        """
        return {
            "hits": {fc.value: len(self._hits[fc]) for fc in self._hits},
            "last_trip_reason": self._last_trip,
        }

    def on_handler_error(self, event: Any, handler: Any) -> None:
        """Publish an ErrorEvent for a failed handler and keep draining.

        Invoked from ``EventHandler._dispatch`` when a handler raises; emits an
        ErrorEvent onto the bus (consumed by the ERROR route) and returns so the loop
        continues. Reads the active exception via ``sys.exc_info()``.
        """
        exc = sys.exc_info()[1]
        handler_name = getattr(handler, '__qualname__', repr(handler))
        self.logger.error(
            f'Handler {handler_name} failed on {getattr(event, "type", "UNKNOWN")}: {exc}'
        )
        # The ERROR route is TERMINAL. If the FAILING event is itself an ErrorEvent,
        # publishing a fresh one would route it straight back to the same failing
        # ERROR-route consumer — an unbounded error->error loop flooding the
        # engine-thread queue and livelocking a single process_events() drain. The
        # failure is already logged above; stop here rather than republish. Both the
        # errors_count bump and the tripwire count MUST stay AFTER this return, so a
        # failure of the terminal route is a complete bookkeeping no-op and is never
        # conflated with a primary-handler failure.
        if getattr(event, 'type', None) is EventType.ERROR:
            return
        if self._error_counter is not None:
            self._error_counter()
        self._bus.put(ErrorEvent(
            # Prefer the event's own business time; the fallback is tz-aware UTC,
            # never a naive wall clock.
            time=getattr(event, 'time', datetime.now(UTC)),
            source='live_trading_system',
            error_type=type(exc).__name__ if exc is not None else 'UnknownError',
            error_message=str(exc) if exc is not None else 'unknown handler failure',
            operation=handler_name,
            severity=ErrorSeverity.ERROR,
        ))
        failure_class = classify_failure(event)
        if failure_class is not None:
            self.record_failure(failure_class)
