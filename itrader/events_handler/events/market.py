"""
Market-side events: clock ticks and OHLCV bars. All frozen ``Event``
subclasses (M3-01).
"""

from typing import ClassVar

from itrader.core.bar import Bar
from itrader.core.enums import EventType

from .base import Event


class TimeEvent(Event, frozen=True, kw_only=True, gc=False):
    """
    Signals that the simulation clock advanced to ``time`` ("the clock
    advanced to T"), pairing with the ``itrader.core.clock.Clock`` family
    (D-08). Drives per-tick screening and bar generation.
    """

    type: ClassVar[EventType] = EventType.TIME

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)


class BarEvent(Event, frozen=True, kw_only=True, gc=False):
    """
    A new market OHLCV bar for every ticker that traded at ``time``.

    Payload contract (M5-02, D-14/D-15):

    - ``bars`` maps ticker -> ONE immutable ``Bar`` struct per tick
      (Decimal OHLCV entered via the string path — no pandas payloads
      on the queue).
    - A ticker with no bar at T is ABSENT from the dict (sparse
      universe / data gap); consumers guard membership with
      ``bars.get(ticker)`` or an ``in`` check.
    - The event carries only the current fact; history comes from the
      Feed (D-15 "event = fact, feed = query").
    """

    type: ClassVar[EventType] = EventType.BAR
    bars: dict[str, Bar]

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)
