"""
Injectable clock seam for the iTrader system (D-09/D-10).

Determinism requires that domain time come from an injected clock rather than a
direct ``datetime.now()`` call inside the engine. This module provides the
mechanism: a structural ``Clock`` protocol plus two concrete implementations.

- ``BacktestClock`` returns the explicitly-advanced simulation/bar time. It never
  silently falls back to wall-clock — ``now()`` asserts that the clock has been
  advanced, so a forgotten ``set_time`` surfaces loudly instead of leaking
  non-deterministic wall-clock time into a backtest.
- ``WallClock`` returns real ``datetime.now()`` for live/telemetry callers.

**D-10 scope:** this plan builds the mechanism only. M2a wires the clock onto the
backtest engine path (Plan 06). It deliberately does NOT touch ``order.py`` audit
timestamps or ``transaction`` timestamps — order-audit and transaction-timestamp
determinism are M2b. Run-duration / perf-telemetry wall-clock reads are not domain
facts (D-09) and stay on the wall clock.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Structural clock seam: anything with ``now() -> datetime`` qualifies."""

    def now(self) -> datetime: ...


class BacktestClock:
    """Deterministic clock that returns the injected simulation/bar time.

    Must be advanced via ``set_time`` before use; ``now()`` asserts the clock
    has been advanced rather than falling back to wall-clock.
    """

    def __init__(self) -> None:
        self._t: datetime | None = None

    def set_time(self, t: datetime) -> None:
        self._t = t

    def now(self) -> datetime:
        assert self._t is not None, "BacktestClock not advanced"
        return self._t


class WallClock:
    """Real-time clock for live/telemetry callers."""

    def now(self) -> datetime:
        return datetime.now()
