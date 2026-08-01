"""Venue substrate — the catalogue of venues and the venue-account domain.

``venues/catalog.py`` answers every pre-build question about a venue as DATA (which
capabilities it has, which credential model it needs, which data provider it defaults
to); ``venues/accounts.py`` owns the venue-account records and their bring-up.

This barrel re-exports the CATALOGUE ONLY. ``venues.accounts`` is deliberately absent:
it is one of the roots the backtest/live import boundary forbids on the backtest graph
(``tests/integration/test_okx_inertness.py``), and a barrel re-export would put it there
the moment anything imported ``itrader.venues``. Live callers import it by path. For the
same reason the connector pool is never re-exported from anywhere.
"""

from itrader.venues.catalog import (
    CATALOG,
    VenueCapability,
    VenueDescriptor,
    descriptor_for,
)

__all__ = [
    "CATALOG",
    "VenueCapability",
    "VenueDescriptor",
    "descriptor_for",
]
