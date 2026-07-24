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
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.venues.bundles import VenueBundles
from itrader.venues.paper_plugin import PaperVenuePlugin
from itrader.venues.registry import COMPUTE_VENUE, ExecutionVenueRegistry


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
        COMPUTE_VENUE, PaperVenuePlugin(exchange_config or default_exchange_config()))
    ctx = SimpleNamespace(
        bus=bus, rng=rng if rng is not None else random.Random(42))
    return VenueBundles(registry, ConnectorProvider({}), ctx)


def in_memory_state_storage() -> Any:
    """A throwaway in-memory ``PortfolioStateStorage`` for a leaf-focused test.

    11.1-REVIEW **WR-04**: ``SimulatedCashAccount`` / ``SimulatedMarginAccount`` now
    REQUIRE their persistence seam, because a leaf that quietly minted its own lost
    every reservation across a live restart while backtest — which reads those
    containers nowhere else — stayed byte-exact. Tests that build a leaf in isolation
    genuinely have no portfolio seam to share, so they say ``state_storage=`` out
    loud and get this. The default is gone from production; the convenience lives
    here, where "in-memory is fine" is a test's own statement rather than a
    production constructor's assumption.
    """
    from itrader.portfolio_handler.storage import PortfolioStateStorageFactory

    return PortfolioStateStorageFactory.create("backtest")


def compute_account(
    initial_cash: Any = 0.0,
    *,
    enable_margin: bool = False,
    state_storage: Optional[Any] = None,
    account_id: Optional[str] = None,
    venue_name: Optional[str] = None,
) -> Any:
    """The compute ``Account`` the paper plugin would mint for these settings (11.1-09).

    ``Portfolio`` no longer selects or builds an account kind (D-02) — it RECEIVES a
    built one, so every direct ``Portfolio(...)`` construction in the tree has to
    supply it. This exists so those ~68 sites share ONE recipe rather than 68 ad-hoc
    ones.

    It reaches the account THROUGH ``PaperVenuePlugin.new_account`` rather than
    constructing a ``SimulatedCashAccount`` directly, and that indirection is the
    point: D-03 makes ``new_account`` the SOLE owner of the margin-vs-cash rule, so
    a test tree that hand-builds leaves would quietly stop agreeing with production
    the first time that rule changed. Going through the plugin means every site
    follows automatically.

    ``state_storage`` may be omitted: THIS RECIPE then mints a plain in-memory
    backend, and ``Portfolio`` ADOPTS that instance as its own seam, so the account
    and the three managers still share exactly one backend (the invariant the live
    restart path depends on). Pass one explicitly only to model a portfolio wired to
    a specific durable store.

    11.1-REVIEW **WR-04**: the in-memory choice lives HERE, in test wiring, and no
    longer inside ``SimulatedCashAccount.__init__``. That relocation is the whole
    point of the change — a production leaf that named no seam used to fabricate one
    silently and lose every reservation across a live restart, invisibly to backtest.
    Tests genuinely do want a throwaway backend, so they say so; production must
    name the seam the portfolio's other managers hold.
    """
    from itrader.venues.bundle import VenueAccountConfig

    seam = (
        state_storage if state_storage is not None
        else in_memory_state_storage()
    )
    return PaperVenuePlugin(default_exchange_config()).new_account(
        VenueAccountConfig(
            initial_cash=initial_cash,
            enable_margin=enable_margin,
            state_storage=seam,
            # D-23 (11.2-08): the compute leaf is the ONE storage site for the
            # (venue_name, account_id) pair. A direct-construction test that wants
            # its Portfolio to REPORT an identity must build the account with it —
            # ``Portfolio.venue_name`` / ``.account_id`` now read the leaf, not a
            # second copy the portfolio used to store.
            account_id=account_id,
            venue_name=venue_name,
        )
    )


def backtest_portfolio_handler(bus: Optional[Any] = None, **kwargs: Any) -> Any:
    """A ``PortfolioHandler`` wired to a backtest-shaped ``VenueBundles`` (11.1-09).

    ``add_portfolio`` now builds each portfolio's account through the venue plugin
    (D-02/D-08), so a handler constructed without the shared bundle memo REFUSES
    rather than minting one inline. Every direct-construction test site that creates
    portfolios needs the same recipe; this is it.

    The memo is built over the bus so the exchange the paper plugin mints publishes
    onto the same queue the handler does — the shape production wires. The queue may
    arrive positionally or as ``global_queue=``; both call shapes exist in the tree.
    """
    if bus is None:
        bus = kwargs.pop('global_queue')
    kwargs.setdefault('venue_bundles', backtest_venue_bundles(bus))
    return PortfolioHandler(bus, **kwargs)
