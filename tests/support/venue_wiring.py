"""ONE shared backtest venue-wiring recipe for the direct-construction test sites (11.1-07).

``ExecutionHandler`` no longer mints its own ``SimulatedExchange``; it RESOLVES one
through ``VenueBundles`` (D-06/D-08). Every test that builds an ``ExecutionHandler``
directly therefore needs the same four-line recipe production uses — registry,
plugin-with-config, empty ``ConnectorProvider``, bundle memo.

This module exists so those sites share ONE recipe rather than five. Five hand-rolled
copies drift: one gets a default-preset config while the run needs a seeded one, another
forgets the shared RNG, and the resulting divergence from production wiring is invisible
until a test proves something production never does. Change the recipe HERE and every
site moves together.

``exchange_config`` defaults to ``default_exchange_config()`` — the preset UNION
``{BTCUSD}``, which is what these sites historically got from the handler's own
no-config fallback, so their symbol admission is unchanged. D-17 still holds: a REAL run
passes its run-derived config; this default is the fallback for callers that have none.

4-SPACE indentation (tests house style).
"""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, Optional

from itrader.connectors.provider import ConnectorProvider
from itrader.execution_handler.execution_handler import default_exchange_config
from itrader.venues.bundles import VenueBundles
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import ExecutionVenueRegistry


def backtest_venue_bundles(
    bus: Any,
    *,
    exchange_config: Optional[Any] = None,
    rng: Optional[random.Random] = None,
) -> VenueBundles:
    """Build the backtest-shaped ``VenueBundles`` a direct ``ExecutionHandler`` needs.

    Mirrors both backtest arms in ``backtest_trading_system.py``: an
    ``ExecutionVenueRegistry`` holding ONE ``PaperVenuePlugin`` under ``'paper'``, a
    REAL, EMPTY ``ConnectorProvider({})`` (D-04 — absence is an empty collection, never
    ``None``), and a minimal ctx carrying just the two fields ``build_bundle`` reads:
    ``bus`` and ``rng``.

    ``rng`` defaults to ``random.Random(42)``, the run-wide determinism seed.
    """
    registry = ExecutionVenueRegistry()
    registry.register(
        'paper', PaperVenuePlugin(exchange_config or default_exchange_config()))
    ctx = SimpleNamespace(
        bus=bus, rng=rng if rng is not None else random.Random(42))
    return VenueBundles(registry, ConnectorProvider({}), ctx)
