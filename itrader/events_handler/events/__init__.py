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
    UniverseUpdateEvent,
)

# Universe / live control-plane events (D-03/D-04/D-06/D-09)
from .universe import (
    BarsLoaded,
    BarsLoadFailed,
    UniversePollEvent,
    StrategyCommandEvent,
)

# Signal events
from .signal import SignalEvent

# Order events
from .order import OrderEvent

# Order-ack events (D-06)
from .ack import OrderAckEvent

# Fill events
from .fill import FillEvent

# Error events (D-06)
from .error import (
    ErrorEvent,
    PortfolioErrorEvent,
)

# CONTROL-tier events (SAFE-03): connector → engine stream/fatal handoff
from .control import (
    StreamStateEvent,
    ConnectorFatalEvent,
)

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
    'UniverseUpdateEvent',

    # Universe / live control-plane events
    'BarsLoaded',
    'BarsLoadFailed',
    'UniversePollEvent',
    'StrategyCommandEvent',

    # Signal events
    'SignalEvent',

    # Order events
    'OrderEvent',

    # Order-ack events
    'OrderAckEvent',

    # Fill events
    'FillEvent',

    # Error events
    'ErrorEvent',
    'PortfolioErrorEvent',

    # CONTROL-tier events
    'StreamStateEvent',
    'ConnectorFatalEvent',

    # Event type discriminator
    'EventType',
]
