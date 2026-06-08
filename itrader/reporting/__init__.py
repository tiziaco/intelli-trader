"""Reporting package (M5-07, D-14): computation split from presentation.

* ``metrics`` — pure metric functions on the run-artifact frames (D-16 formulas)
* ``frames``  — pure frame builders shared by the engine printout + run_backtest.py
* ``plots``   — optional plotly presentation (D-19 minimal set), same frames

The legacy ``statistics`` / ``engine_logger`` / ``base`` / ``performance``
modules were deleted by the M5-07 rework (plan 07-03); any SQL persistence
rebirth is D-sql scope.
"""

from itrader.reporting import frames, metrics, plots

__all__ = ["frames", "metrics", "plots"]
