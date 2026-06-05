"""
Frozen event dataclasses for the iTrader event system (D-09).

All inter-component messages on the global queue, organized by domain
module for better maintainability. Every class is an immutable
``frozen=True``/``slots=True``/``kw_only=True`` fact subclassing
``Event`` (M3-01) — mutation raises ``dataclasses.FrozenInstanceError``.
"""

# Event base
from .base import Event

# Market events
from .market import (
    TimeEvent,
    BarEvent,
    PortfolioUpdateEvent,
    ScreenerEvent,
)

# Signal events
from .signal import SignalEvent

# Order events
from .order import OrderEvent

# Fill events
from .fill import FillEvent

# Event type discriminator (single definition lives in core/enums)
from itrader.core.enums import EventType

__all__ = [
    # Event base
    'Event',

    # Market events
    'TimeEvent',
    'BarEvent',
    'PortfolioUpdateEvent',
    'ScreenerEvent',

    # Signal events
    'SignalEvent',

    # Order events
    'OrderEvent',

    # Fill events
    'FillEvent',

    # Event type discriminator
    'EventType',
]
