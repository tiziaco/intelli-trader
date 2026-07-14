"""Live-safety subpackage (D-15).

Empty package marker by design. Nothing is re-exported here: the safety stack
(SafetyController and its future siblings) is constructed only inside
build_live_system, so a barrel re-export would pull the live stack onto the
backtest graph and break the OKX inertness gate (Pitfall 5). Keep this file free
of any re-export line.
"""
