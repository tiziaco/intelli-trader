"""
Screener event: a Screener object's result broadcast to the strategy
handler (D-screener). A frozen ``Event`` subclass (M3-01).
"""

from typing import ClassVar

from itrader.core.enums import EventType

from .base import Event


class ScreenerEvent(Event, frozen=True, kw_only=True, gc=False):
    """
    Screener event generated from a Screener object.
    This is received by the Strategy handler object
    that update the symbol to trade of the subscribed
    strategies.

    Current fields kept unchanged (frozen structurally; D-screener owns
    the semantics).
    """

    type: ClassVar[EventType] = EventType.SCREENER
    screener_id: str
    screener_name: str
    subscribed_strategies: list[str]
    tickers: list[str]

    def __str__(self) -> str:
        return f"{self.type} ({self.screener_name})"

    def __repr__(self) -> str:
        return str(self)
