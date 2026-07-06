"""
Universe / live control-plane events (D-03/D-04/D-06/D-09).

Four frozen ``Event`` facts that carry Phase-7 live dynamic-universe traffic
on the global queue. All mirror the ``UniverseUpdateEvent`` shape (frozen
msgspec ``Event``, ``ClassVar`` type pin, ``__str__``/``__repr__``) and carry
the inherited business ``time`` (never wall clock — callers supply the
venue/business time, RESEARCH Pitfall 5):

- ``BarsLoaded`` — warmup bars bulk-transported for one symbol/timeframe (D-03).
- ``BarsLoadFailed`` — a warmup backfill errored for one symbol (D-04).
- ``UniversePollEvent`` — control-plane poll tick, no payload (D-06).
- ``StrategyCommandEvent`` — an add/remove-ticker command with factory
  classmethods (D-09).

This plan ships NO consumers: the ``_routes`` entries are explicit-empty and
live consumers are wired live-only in Plan 07 (backtest stays inert).
"""

from datetime import datetime
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


class UniversePollEvent(Event, frozen=True, kw_only=True, gc=False):
    """Control-plane universe-poll tick (D-06).

    A pure control signal that the universe poll cadence elapsed — it carries
    NO extra payload beyond the inherited business ``time``. The live poll
    handler (Plan 07) consumes it to re-derive membership; the backtest route
    is explicit-empty, so dispatching one is an inert no-op.
    """

    type: ClassVar[EventType] = EventType.UNIVERSE_POLL

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

    def __repr__(self) -> str:
        return str(self)


class StrategyCommandEvent(Event, frozen=True, kw_only=True, gc=False):
    """An add/remove-ticker command addressed to one strategy (D-09).

    The typed engine-command surface routes a universe membership change to a
    specific strategy as a queue fact (no wrapper method on
    ``LiveTradingSystem`` — the command IS the event, D-09).

    Payload contract:

    - ``strategy_name`` — the target strategy.
    - ``verb`` — ``"add_ticker"`` | ``"remove_ticker"`` today; the vocabulary
      grows to enable/disable/reconfigure later.
    - ``symbol`` — the ticker the verb applies to.
    - ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``.

    Construct via the ``add_ticker`` / ``remove_ticker`` factory classmethods
    (the ``FillEvent.new_fill`` house convention), never by hand.
    """

    type: ClassVar[EventType] = EventType.STRATEGY_COMMAND
    strategy_name: str
    verb: str
    symbol: str

    @classmethod
    def add_ticker(cls, strategy_name: str, symbol: str, *,
                   time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``add_ticker`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="add_ticker", symbol=symbol)

    @classmethod
    def remove_ticker(cls, strategy_name: str, symbol: str, *,
                      time: datetime) -> "StrategyCommandEvent":
        """Build a complete ``remove_ticker`` command (D-09, construct-complete)."""
        return cls(time=time, strategy_name=strategy_name,
                   verb="remove_ticker", symbol=symbol)

    def __str__(self) -> str:
        return f"{self.type} ({self.strategy_name}, {self.verb}, {self.symbol})"

    def __repr__(self) -> str:
        return str(self)
