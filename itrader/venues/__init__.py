"""Venue-parametrization substrate — registries, bundle, plugin Protocols (05-04, VENUE-01/02).

The top-level ``venues/`` package parallels ``connectors/``: it holds the two
independent registries (``ExecutionVenueRegistry`` / ``DataProviderRegistry``),
the execution-only ``VenueBundle`` value object, and the ``VenuePlugin`` /
``DataProviderPlugin`` build seams the registries hold.

This barrel is deliberately INERT (the P5 acceptance gate): it re-exports ONLY
the pure value objects / Protocols / registry classes, and imports NO concretion
(no ccxt.pro, no OKX connector, no SQL). Concrete plugins (05-05) are registered
by the live composition root via explicit ``register(...)`` calls (D-01) — never
imported here — so importing ``itrader.venues`` pulls nothing heavy.
"""

from itrader.venues.bundle import DataProviderPlugin, VenueBundle, VenuePlugin
from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry

__all__ = [
    "DataProviderPlugin",
    "DataProviderRegistry",
    "ExecutionVenueRegistry",
    "VenueBundle",
    "VenuePlugin",
]
