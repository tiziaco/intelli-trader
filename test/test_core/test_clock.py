"""Wave 0 scaffold for the injectable Clock seam (M2-05).

These tests lock the contracts the clock module (Task 4 of this plan) must
satisfy:

1. A fresh ``BacktestClock`` has no time yet — ``.now()`` raises ``RuntimeError``
   before ``.set_time(...)`` is called (the clock must be explicitly advanced; it
   never silently falls back to wall-clock, and the guard survives ``python -O``).
2. After ``c.set_time(t)``, ``c.now() == t`` (returns the injected sim/bar time).

They are EXPECTED to fail (red) until Task 4 creates ``itrader/core/clock.py``.
The module itself must import and collect cleanly (no syntax error, no
collection error) — only the import/assertions are allowed to fail.

This scaffold is co-located here (in the plan that builds ``core/clock.py``)
rather than in Plan 01, so no same-wave plan verifies against a scaffold another
same-wave plan creates. It carries an explicit module-level ``pytestmark`` so
``--strict-markers`` is satisfied regardless of conftest ordering.
"""

from datetime import datetime

import pytest

from itrader.core.clock import BacktestClock

pytestmark = pytest.mark.unit


def test_backtest_clock_now_before_advance_raises():
    clock = BacktestClock()
    with pytest.raises(RuntimeError):
        clock.now()


def test_backtest_clock_now_returns_set_time():
    clock = BacktestClock()
    t = datetime(2024, 1, 1, 12, 0, 0)
    clock.set_time(t)
    assert clock.now() == t


def test_backtest_clock_set_time_is_replaceable():
    clock = BacktestClock()
    first = datetime(2024, 1, 1)
    second = datetime(2024, 1, 2)
    clock.set_time(first)
    clock.set_time(second)
    assert clock.now() == second
