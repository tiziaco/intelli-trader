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
from datetime import datetime, UTC
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from itrader.core.enums import ErrorSeverity
from itrader.events_handler.bus import EventBus
from itrader.events_handler.events import EventType, ErrorEvent
from itrader.logger import get_itrader_logger


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
    ) -> None:
        self.logger = get_itrader_logger().bind(component="ErrorPolicy")
        self._bus = bus
        # Preserves the facade's ``with self._stats_lock: _stats['errors_count'] += 1``
        # bookkeeping when wired (06-05); a no-op keeps the policy standalone here.
        self._error_counter = error_counter

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
        if self._error_counter is not None:
            self._error_counter()
        # WR-06: the ERROR route is TERMINAL. If the FAILING event is itself an
        # ErrorEvent, publishing a fresh ErrorEvent would route it straight back to
        # the same failing ERROR-route consumer — an unbounded error->error feedback
        # loop flooding the engine-thread queue (and, when the failure repeats on the
        # re-consumed event, livelocking a single process_events() drain forever). The
        # failure is already logged once above; stop here rather than republish. The
        # tripwire count/classify (Task 2) MUST sit AFTER this return so a
        # COSMETIC/ERROR-type failure is never counted.
        if getattr(event, 'type', None) is EventType.ERROR:
            return
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
