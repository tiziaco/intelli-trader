"""The paper execution adapter's build recipe — beside the adapter it builds.

Every venue supplies ONE recipe that turns a run's context into that venue's execution
adapter, and the recipe lives next to the adapter rather than in a registry of plugin
objects (design §4.3). This is the paper venue's.

``simulated.py`` is deliberately untouched: the adapter is a domain object, the recipe is
composition knowledge, and keeping them in separate modules is what lets a caller import
the adapter's type without importing the run-wiring that selects it.

``exchange_config`` is bound by the caller and never read off the process-wide config
singleton: only the run knows its complete symbol set, and a default preset silently
narrows order admission — the failure then surfaces as refused orders far from the cause.

The exchange is built with the run's ONE seeded ``random.Random``: two ``random.Random(42)``
instances look identical until the call order diverges, so a fresh one breaks
reproducibility silently.

Indentation: 4-space.
"""

from __future__ import annotations

import random
from typing import Any, Callable, TYPE_CHECKING

from itrader.execution_handler.exchanges.base import AbstractExchange
from itrader.execution_handler.exchanges.simulated import SimulatedExchange

if TYPE_CHECKING:
    from itrader.config.exchange import ExchangeConfig


def build_paper_exchange(
    *,
    exchange_config: "ExchangeConfig",
    bus: Any,
    rng: random.Random,
) -> SimulatedExchange:
    """Build one connected ``SimulatedExchange`` for the paper venue.

    ``connect()`` is not ceremony: ``SimulatedExchange.validate_order`` refuses an order on
    a disconnected exchange, so an unconnected paper venue fills nothing.
    """
    exchange = SimulatedExchange(bus, config=exchange_config, rng=rng)
    exchange.connect()
    return exchange


def paper_exchange_recipe(
    exchange_config: "ExchangeConfig",
) -> Callable[..., AbstractExchange]:
    """The paper adapter in RECIPE form, bound to this run's exchange config.

    The venue-account manager builds every execution adapter through one uniform
    ``recipe(spec=..., connector=..., ctx=...)`` call, so the paper venue supplies one too.
    ``exchange_config`` is bound here because the manager knows the account, not the run's
    symbol set.
    """

    def _build(
        *,
        spec: Any = None,
        connector: Any = None,
        ctx: Any = None,
    ) -> AbstractExchange:
        # ``spec`` and ``connector`` are deliberately unread: paper holds no venue session,
        # so the manager opens none for it, and both parameters exist only to keep ONE
        # recipe shape across venues.
        return build_paper_exchange(
            exchange_config=exchange_config, bus=ctx.bus, rng=ctx.rng)

    return _build
