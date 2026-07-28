"""
System lifecycle-status vocabulary for the iTrader engine.

``SystemStatus`` is the live trading-system lifecycle state; ``live_trading_system.py``
and ``SafetyController`` import it from here.
"""

from enum import Enum

__all__ = ["SystemStatus", "VALID_STATUS_TRANSITIONS", "HaltReason", "FailureClass"]


class SystemStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    HALTED = "halted"  # Reason vocabulary is ``HaltReason`` below.


# Mirrors ``core/enums/order.py::VALID_ORDER_TRANSITIONS`` (the shape donor): a dict
# mapping each state to the SET of states it may legally move to. Enforced at the ONE
# mutation seam ``SafetyController.update_status`` so the engine has genuinely one
# writer and one rule.
#
# ``HALTED`` is the terminal/latched analog of ``OrderStatus.FILLED: []`` — it maps to
# an EMPTY set (no legal exits). A reconcile/guard halt declared the engine's state
# untrustworthy, so no lifecycle transition may silently clear it. The SOLE sanctioned
# exit is the explicit operator ``reset_halt()`` (deliberately OUTSIDE this table — a
# forced write that returns the engine to ``STOPPED`` so a subsequent ``start()``
# re-runs reconciliation + the baseline guard, verify-then-trust).
#
# ANY non-terminal state may transition to ``HALTED`` — a safety halt must always be
# reachable. ``ERROR`` is recoverable (an operator may re-``start()`` or stop it). A
# same-state call is treated as an idempotent no-op by ``update_status`` and so is
# intentionally NOT listed here.
VALID_STATUS_TRANSITIONS: dict[SystemStatus, set[SystemStatus]] = {
    SystemStatus.STOPPED: {SystemStatus.STARTING, SystemStatus.HALTED},
    SystemStatus.STARTING: {
        SystemStatus.RUNNING,
        SystemStatus.STOPPING,
        SystemStatus.ERROR,
        SystemStatus.HALTED,
    },
    SystemStatus.RUNNING: {
        SystemStatus.STOPPING,
        SystemStatus.ERROR,
        SystemStatus.HALTED,
    },
    SystemStatus.STOPPING: {
        SystemStatus.STOPPED,
        SystemStatus.ERROR,
        SystemStatus.HALTED,
    },
    SystemStatus.ERROR: {
        SystemStatus.STARTING,
        SystemStatus.STOPPING,
        SystemStatus.STOPPED,
        SystemStatus.HALTED,
    },
    SystemStatus.HALTED: set(),  # Terminal/latched — only reset_halt() (off-table) exits.
}


class HaltReason(Enum):
    """Typed vocabulary for engine halt reasons.

    Each ``.value`` is the wire string durable halt records are persisted as
    (``storage/halt_record_store.py``); changing a member's value would break the
    resolution of records written before the change.

    NOT YET AUTHORITATIVE: ``SafetyController.halt`` and
    ``SafetyController.update_status(halt_reason=)`` both still take a bare
    ``str``, and nothing checks an argument against this enum. Free-string call
    sites remain, and at least one reason reaching ``halt()`` is absent from
    this vocabulary — ``SafetyController``'s ``deferred-protective-overflow``.
    Treat this as the intended vocabulary, not a guarantee about what reaches
    ``halt()``.
    """

    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
    DRIFT = "drift"

    # One typed halt reason per ``FailureClass`` for the CF-1 aggregate
    # failure-rate tripwire. Each carries a NEW lowercase-hyphen wire string; the
    # five members above are unchanged (durable halt records persist those
    # strings). ``FailureClass.FILL_TRANSLATION`` reuses ``SETTLEMENT_FAILURE``
    # (a lost venue fill IS a settlement loss), so there is no FILL_TRANSLATION
    # reason.
    SETTLEMENT_FAILURE = "settlement-failure"
    ORDER_ROUTE_ERRORS = "order-route-errors"
    ADMISSION_ERRORS = "admission-errors"
    LOOP_BACKSTOP = "loop-backstop"


class FailureClass(Enum):
    """Route-classification of live handler failures for the CF-1 tripwire.

    The CF-1 aggregate failure-rate tripwire classifies each publish-and-continue
    handler failure into one of these five classes and counts it against a
    per-class ``(threshold, window)`` policy (``FailureRateSettings``). Each class
    maps 1:1 onto a tripwire ``HaltReason``:

      - ``SETTLEMENT``       -> ``HaltReason.SETTLEMENT_FAILURE``
      - ``ORDER_IO``         -> ``HaltReason.ORDER_ROUTE_ERRORS``
      - ``ADMISSION``        -> ``HaltReason.ADMISSION_ERRORS``
      - ``LOOP_BACKSTOP``    -> ``HaltReason.LOOP_BACKSTOP``
      - ``FILL_TRANSLATION`` -> ``HaltReason.SETTLEMENT_FAILURE`` (a lost venue
        fill is a settlement loss, halt-on-first)

    ``.value`` is a descriptive lowercase-hyphen literal in the ``HaltReason``
    house style; these values are NOT persisted (unlike ``HaltReason``), so they
    are chosen for readability only.
    """

    SETTLEMENT = "settlement"
    ORDER_IO = "order-io"
    ADMISSION = "admission"
    LOOP_BACKSTOP = "loop-backstop"
    FILL_TRANSLATION = "fill-translation"
