"""
System lifecycle-status vocabulary for the iTrader engine.

``SystemStatus`` is the live trading-system lifecycle state, relocated to its
canonical home in ``core/enums/``. ``live_trading_system.py`` imports it from
here. This module imports stdlib ONLY (the core/enums dependency rule).
"""

from enum import Enum

__all__ = ["SystemStatus"]


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
