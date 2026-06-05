"""
Event-related enums for the iTrader system.
"""

from enum import Enum


class EventType(Enum):
    """Type discriminator carried by every event on the global queue.

    ``TIME`` replaces the legacy ``PING`` member (D-08): the event means
    "the clock advanced to T" (Nautilus precedent), pairing with the
    ``itrader.core.clock.Clock`` family. ``TICK`` is RESERVED for future
    live market-data ticks (D-live) — do not reuse ``TIME`` for that.
    ``ERROR`` is the dedicated error-event type (D-06).

    Member values are explicit uppercase strings, replacing the prior
    inline functional ``Enum("EventType", "PING BAR ...")`` definition in
    ``events_handler/event.py`` (which had auto int values). No code relies
    on the ``.value`` being an int (verified), so explicit string values
    are safe and clearer.
    """
    TIME = "TIME"
    BAR = "BAR"
    UPDATE = "UPDATE"
    SIGNAL = "SIGNAL"
    ORDER = "ORDER"
    FILL = "FILL"
    SCREENER = "SCREENER"
    ERROR = "ERROR"

    @classmethod
    def _missing_(cls, value: object) -> "EventType":
        """Case-insensitive string parse; raise a clear f-string error.

        Invoked by ``EventType(value)`` on lookup failure. Mirrors the
        ``FillStatus._missing_`` house pattern (Phase 3 D-04).
        """
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown EventType: {value!r}")


class Side(Enum):
    """Order/signal side at the event boundary (D-05).

    Boundary rule: events carry ``Side``; ``Portfolio`` maps
    ``Side -> TransactionType`` at its own boundary (same precedent as the
    ``FillStatus -> OrderStatus`` exchange-truth -> mirror mapping).

    Defined here ahead of the Plan 04-05 cutover — event fields are retyped
    from ``str`` to ``Side`` there, not before.
    """
    BUY = "BUY"
    SELL = "SELL"

    @classmethod
    def _missing_(cls, value: object) -> "Side":
        """Case-insensitive string parse; raise a clear f-string error."""
        if isinstance(value, str):
            for member in cls:
                if member.value.upper() == value.upper():
                    return member
        raise ValueError(f"Unknown Side: {value!r}")
