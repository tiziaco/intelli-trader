"""
Warmup bulk-transport events (D-03/D-04): the REST/backfill feed path's
``BarsLoaded`` / ``BarsLoadFailed`` facts. Frozen ``Event`` subclasses (M3-01)
carrying the inherited business ``time`` (never wall clock — callers supply
the venue/business time, RESEARCH Pitfall 5).
"""

from typing import ClassVar

from itrader.core.bar import Bar
from itrader.core.enums import EventType

from .base import Event


class BarsLoaded(Event, frozen=True, kw_only=True, gc=False):
    """Warmup bars loaded for one ``(symbol, timeframe)`` (D-03).

    Bulk transport for the REST/backfill warmup path: instead of pushing each
    historical bar one at a time, the loader emits ONE ``BarsLoaded`` carrying
    the whole warmup window as an immutable ``tuple[Bar, ...]``.

    Payload contract:

    - ``bars`` is a ``tuple`` of immutable Decimal ``Bar`` structs — reused
      verbatim from ``core.bar.Bar`` (the same struct ``BarEvent`` carries).
      NEVER a pandas frame on the queue (M5-02).
    - ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``
      (business time = the newest fetched bar's time; UUIDv7 identity).
    """

    type: ClassVar[EventType] = EventType.BARS_LOADED
    symbol: str
    timeframe: str
    bars: tuple[Bar, ...]

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)


class BarsLoadFailed(Event, frozen=True, kw_only=True, gc=False):
    """A warmup backfill failed for one ``symbol`` (D-04).

    Emitted when the REST/backfill warmup for a freshly-added universe symbol
    errors, so the readiness gate can move that entry to ``Readiness.FAILED``.

    Security (T-05-27, RESEARCH Security V5): ``reason`` MUST be a SCRUBBED
    exception TYPE / short human message only — NEVER ``str(exc)`` and never a
    secret/credential/URL. The emit site (Plan 07) is responsible for the
    scrub; this struct only carries the already-scrubbed string.

    ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``.
    """

    type: ClassVar[EventType] = EventType.BARS_LOAD_FAILED
    symbol: str
    reason: str

    def __str__(self) -> str:
        return f"{self.type} ({self.symbol})"

    def __repr__(self) -> str:
        return str(self)
