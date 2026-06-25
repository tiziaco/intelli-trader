"""
Frozen Event base for the iTrader event system (D-01/D-02).

Every event on the global queue is an immutable fact (M3-01): once
constructed, no field can be rewritten — mutation raises
``AttributeError`` (frozen ``msgspec.Struct``). Concrete events subclass
``Event`` and pin their ``type`` via ``type: ClassVar[EventType] =
EventType.X``.
"""

import uuid
from datetime import datetime
from typing import ClassVar

import msgspec
import uuid_utils.compat as uuid_compat

from itrader.core.enums import EventType


class Event(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    """Immutable event fact. All concrete events subclass this.

    Fields
    ------
    type:
        ``ClassVar`` discriminator — no base default; each subclass sets
        it via ``type: ClassVar[EventType] = EventType.X``.
    time:
        Business time of the event (the simulation clock, never wall clock).
    event_id:
        Unique, time-ordered UUIDv7 identity (D-01), auto-generated via
        ``uuid_utils.compat.uuid7`` (returns a native stdlib ``uuid.UUID``).
    created_at:
        Defaults to business time when not supplied (D-02 — no wall clock
        on the engine path).
    """

    type: ClassVar[EventType]
    time: datetime
    event_id: uuid.UUID = msgspec.field(default_factory=uuid_compat.uuid7)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            # frozen msgspec.Struct honours object.__setattr__ inside
            # __post_init__ (msgspec 0.21.1 / Python 3.13.1) — the idiom
            # ports verbatim from the prior frozen dataclass.
            object.__setattr__(self, "created_at", self.time)
