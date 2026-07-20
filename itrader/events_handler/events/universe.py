"""
Universe events (D-04/D-06): the two frozen ``Event`` facts that carry
dynamic-universe membership traffic on the global queue.

- ``UniverseUpdateEvent`` — a membership change that already happened (adds/
  removes resolved by a poll), the "dispose" seam (D-04).
- ``UniversePollEvent`` — control-plane poll tick, no payload (D-06).

Both mirror the house event shape (frozen msgspec ``Event``, ``ClassVar`` type
pin, ``__str__``/``__repr__``) and carry the inherited business ``time`` (never
wall clock — callers supply the venue/business time, RESEARCH Pitfall 5).

This plan ships NO consumers: the ``_routes`` entries are explicit-empty and
live consumers are wired live-only in Plan 05/07 (backtest stays inert).
"""

from typing import ClassVar

from itrader.core.enums import EventType

from .base import Event


class UniverseUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
    """Dynamic-universe membership change notification (D-04).

    The "dispose" notification for mid-run universe membership: after a poll
    resolves adds/removes, ``Universe.apply`` mutates membership and the poll
    handler emits ONE ``UniverseUpdateEvent`` carrying the resulting delta.

    DISTINCT from ``ScreenerEvent`` (the "propose" seam — screeners propose,
    membership disposes): this event announces a membership change that already
    happened, not a proposal. Kept a separate type so the two seams never
    conflate on the queue.

    Payload contract:

    - ``added`` / ``removed`` are ``tuple[str, ...]`` (immutable payload on the
      frozen struct) — the symbols that entered / left the universe.
    - ``time`` / ``event_id`` / ``created_at`` are inherited from ``Event``
      (business time, UUIDv7 identity — never wall clock).

    This plan ships NO consumers: the ``_routes`` entry is explicit-empty and
    live consumers are wired live-only in plan 05 (backtest stays inert).
    """

    type: ClassVar[EventType] = EventType.UNIVERSE_UPDATE
    added: tuple[str, ...]
    removed: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.type}, Time: {self.time}"

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
