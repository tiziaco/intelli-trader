"""Live-safety subpackage.

Empty package marker by design. Nothing is re-exported here: the safety stack is
constructed only inside ``build_live_system``, so a barrel re-export would pull the live
stack onto the backtest import graph and break the OKX inertness gate. Keep this file
free of any re-export line.
"""
