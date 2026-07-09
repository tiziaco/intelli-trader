"""
System lifecycle-status vocabulary for the iTrader engine.

``SystemStatus`` is the live trading-system lifecycle state, relocated to its
canonical home in ``core/enums/``. ``live_trading_system.py`` imports it from
here. This module imports stdlib ONLY (the core/enums dependency rule).
"""

from enum import Enum

__all__ = ["SystemStatus", "VALID_STATUS_TRANSITIONS", "HaltReason"]


class SystemStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    HALTED = "halted"   # D-07: distinct machine-readable halt state, reason ∈
                        # {drift, reconciliation-unresolved, connector-fatal,
                        #  paused-on-disconnect}. Not RUNNING/STOPPED/ERROR —
                        # a reconciliation-driven stop the operator must clear.


# Valid state transitions for the system lifecycle (D-05 / V17-03).
#
# Mirrors ``core/enums/order.py::VALID_ORDER_TRANSITIONS`` (the shape donor): a dict
# mapping each state to the SET of states it may legally move to. Enforced at the ONE
# mutation seam ``LiveTradingSystem._update_status`` so the engine has genuinely one
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
# reachable (F/U-8). ``ERROR`` is recoverable (an operator may re-``start()`` or stop
# it). A same-state call is treated as an idempotent no-op by ``_update_status`` and so
# is intentionally NOT listed here.
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
    """Typed vocabulary for every reachable engine halt reason (CFG-05 / D-10).

    Exactly the reasons that reach ``halt()`` / ``_update_status(halt_reason=)``
    today — one member per live reason, no dead members. ``drift`` is a live
    ``halt()`` reason: ``portfolio_handler`` fires ``_halt_signal("drift")`` on
    unexplained beyond-band drift and ``LiveTradingSystem`` wires that signal
    straight to ``self.halt`` (``set_halt_signal(self.halt)``), so it is a member
    here (CR-01). ``paused-on-disconnect`` is deliberately NOT a member — it is a
    ``pause_submission()`` reason, not a halt.

    Each ``.value`` is the EXISTING wire string, so durable halt records
    persisted as strings (``storage/halt_record_store.py``) still resolve — no
    data migration (T-02-01). P1 defines the enum; migrating the remaining
    ``halt()`` call sites and its ``reason: str`` signature is P8's job (D-11).
    """

    BASELINE_RESIDUAL = "baseline-residual"
    CONNECTOR_FATAL = "connector-fatal"
    RECONCILIATION_UNRESOLVED = "reconciliation-unresolved"
    DURABLE_HALT = "durable-halt"
    DRIFT = "drift"
