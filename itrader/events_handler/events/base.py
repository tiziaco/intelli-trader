"""
Frozen Event base for the iTrader event system (D-01/D-02).

Every event on the global queue is an immutable fact (M3-01): once
constructed, no field can be rewritten — mutation raises
``dataclasses.FrozenInstanceError``. Concrete events subclass ``Event``
and pin their ``type`` via ``field(default=EventType.X, init=False)``.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import uuid_utils.compat as uuid_compat

from itrader.core.enums import EventType


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Immutable event fact. All concrete events subclass this.

    Fields
    ------
    type:
        Real (``init=False``) field — no base default; each subclass sets
        it via ``field(default=EventType.X, init=False)``.
    time:
        Business time of the event (the simulation clock, never wall clock).
    event_id:
        Unique, time-ordered UUIDv7 identity (D-01), auto-generated via
        ``uuid_utils.compat.uuid7`` (returns a native stdlib ``uuid.UUID``).
    created_at:
        Defaults to business time when not supplied (D-02 — no wall clock
        on the engine path).
    """

    type: EventType = field(init=False)
    time: datetime
    event_id: uuid.UUID = field(default_factory=uuid_compat.uuid7)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            # stdlib-documented idiom for frozen dataclass __post_init__;
            # works with slots=True (verified on Python 3.13.1).
            object.__setattr__(self, "created_at", self.time)
