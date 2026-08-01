"""``build_handler_graph`` dependency-wiring tests.

These pin the three ``StrategiesHandler`` deps that used to be assigned AFTER
construction by the live composition root and are now real at ``__init__``:

- ``registry_store`` is handler-derived from ``(environment, sql_engine)`` — ``None``
  on the backtest path, which keeps every persist arm a clean no-op.
- ``portfolio_read_model`` is the SAME ``portfolio_handler`` object the graph just built
  (it structurally satisfies the ``PortfolioReadModel`` Protocol). Asserted by identity,
  not equality: the point is that it IS that object, not one equal to it.
- ``strategy_catalog`` rides in as a ``build_handler_graph`` kwarg and defaults to
  ``None``, keeping the LOUD-reject on a catalog-less ``add`` reachable.

Driven against a REAL ``build_handler_graph`` call over a backtest ``EngineContext``
(``FifoEventBus`` + ``CsvPriceStore`` + ``BacktestBarFeed``, ``sql_engine=None``),
mirroring the register-vs-build block in ``test_okx_inertness.py`` so no database is
needed. The exchange registry and portfolio factory are built exactly as the backtest
root builds them, since the graph takes them as REQUIRED, already-built arguments.
4-space indentation (tests house style).
"""

import random

import pytest

from itrader import config as _config
from itrader.config import FeeModelType
from itrader.events_handler.bus import FifoEventBus
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.portfolio_handler.portfolio_factory import AccountFactory, PortfolioFactory
from itrader.trading_system.engine_context import EngineContext
from itrader.trading_system.graph import build_handler_graph

from tests.support.venue_wiring import backtest_exchange_registry

pytestmark = pytest.mark.integration


@pytest.fixture
def ctx() -> EngineContext:
    """A backtest-shaped, database-free EngineContext."""
    store = CsvPriceStore()
    return EngineContext(
        bus=FifoEventBus(),
        config=_config,
        environment="backtest",
        feed=BacktestBarFeed(store, to_timedelta("1d")),
        # D-07: the ONE shared seeded RNG the wiring seam hands to every stochastic
        # component. Held by the fixture so a test can assert IDENTITY against it.
        rng=random.Random(42),
        store=store,
        sql_engine=None,
    )


@pytest.fixture
def exchange_registry(ctx: EngineContext) -> dict[tuple[str, str], object]:
    """The REQUIRED, root-owned ``(venue, account_id) -> exchange`` map.

    Built over the SAME ctx the graph is built from, so ``ctx.rng`` is the RNG the
    paper recipe hands to the exchange it builds.
    """
    return backtest_exchange_registry(ctx.bus, rng=ctx.rng)


def _graph(ctx: EngineContext, exchange_registry: object, **kwargs: object) -> object:
    """Build the handler graph the way the backtest root does."""
    return build_handler_graph(
        ctx,
        exchange_registry=exchange_registry,
        portfolio_factory=PortfolioFactory(
            account_factory=AccountFactory(),
            environment=ctx.environment,
            sql_engine=ctx.sql_engine),
        **kwargs)


def test_portfolio_read_model_is_the_composed_portfolio_handler(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    engine = _graph(ctx, exchange_registry)
    # D-11 flat-detect seam: an injected READ-model, never a cross-domain call.
    assert (
        engine.strategies_handler.portfolio_read_model is engine.portfolio_handler
    )


def test_strategy_catalog_defaults_to_none(ctx: EngineContext, exchange_registry: dict[tuple[str, str], object]) -> None:
    engine = _graph(ctx, exchange_registry)
    # D-10: stays None when not supplied, so `add`'s LOUD-reject remains reachable
    # and no external payload can be instantiated on a catalog-less handler.
    assert engine.strategies_handler.strategy_catalog is None


def test_strategy_catalog_is_threaded_through_the_graph_builder(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    catalog = {"SomeStrategy": object}
    engine = _graph(ctx, exchange_registry, strategy_catalog=catalog)
    assert engine.strategies_handler.strategy_catalog is catalog


def test_the_composed_exchange_holds_the_ctx_rng_instance(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    """VENUE-06/D-07: the exchange draws from the ctx's RNG OBJECT, not a copy of it.

    Asserted by ``is`` and never ``==``: two ``random.Random(42)`` instances compare as
    distinct objects but LOOK identical — same seed, same first draw — until either is
    drawn from, at which point the call ORDER diverges and the run silently leaves the
    byte-exact oracle. Equality of seed proves nothing; only identity does.

    The RNG reaches the exchange through ``build_paper_exchange`` (the recipe that
    BUILDS it), never through an ``ExecutionHandler`` attribute.
    """
    engine = _graph(ctx, exchange_registry)
    # The (venue, account_id) PAIR with the paper venue on DEFAULT_ACCOUNT_ID.
    exchange = engine.execution_handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)]
    assert exchange._rng is ctx.rng


def test_the_handler_resolves_the_exchange_the_root_built(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    """The handler routes to the ROOT's exchange, never one it minted itself.

    The failure this catches is a decorative registry: the map is wired in, every test
    passes, and ``ExecutionHandler`` quietly keeps minting its own exchange on a
    surviving parallel path. Two exchanges over one venue is not a cosmetic duplicate —
    each owns its own resting-order book, so orders and bars would be matched against
    different books.

    Identity is the only assertion that distinguishes the two implementations: an
    equal-but-distinct ``SimulatedExchange`` would satisfy any isinstance/config check
    while proving the mint survived. The map is also asserted to be held BY REFERENCE:
    the live root writes brought-online accounts into the same object the handler reads.
    """
    engine = _graph(ctx, exchange_registry)

    composed = engine.execution_handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)]

    assert composed is exchange_registry[("paper", DEFAULT_ACCOUNT_ID)]
    assert engine.execution_handler.exchanges is exchange_registry
    # Exactly ONE entry: the root seeded the compute venue's single account and the
    # graph builder added no key of its own.
    assert list(exchange_registry) == [("paper", DEFAULT_ACCOUNT_ID)]


def test_backtest_context_yields_no_registry_store(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    engine = _graph(ctx, exchange_registry)
    # DECOMP-01a: derived from (environment='backtest', sql_engine=None) -> None.
    assert engine.strategies_handler.registry_store is None


def test_the_wired_fee_model_provider_is_late_bound(
    ctx: EngineContext, exchange_registry: dict[tuple[str, str], object],
) -> None:
    """The provider the graph ACTUALLY WIRES re-reads the fee model.

    This guards the WIRING, not the contract, and the distinction is the whole
    reason the test exists. The other late-binding tests build their OWN provider and
    assert the PROTOCOL contract — so a capturing regression introduced in the graph
    builder leaves every one of them green, along with the byte-exact oracle (the golden
    run pins ``ZeroFeeModel``, so it can never see a fee change at all).

    This test closes that hole. It reaches the provider the graph injected, swaps
    the exchange's fee model through the REAL ``update_config`` mechanism
    (``exchanges/simulated.py:775``), and asserts the NEXT deref sees the swap.
    Asserted by object IDENTITY: an equal-but-stale model would satisfy any
    isinstance or rate check while proving the capture survived.
    """
    engine = _graph(ctx, exchange_registry)
    provider = engine.order_handler.order_manager.admission_manager.fee_model_provider
    exchange = engine.execution_handler.exchanges[("paper", DEFAULT_ACCOUNT_ID)]

    assert provider is not None
    before = provider("paper", DEFAULT_ACCOUNT_ID)
    # It IS the wired exchange's model, not some independently built one.
    assert before is exchange.fee_model

    # Hot-swap exactly as a runtime reconfiguration does: update_config REPLACES
    # the fee-model object after its atomic config swap.
    exchange.update_config(
        {"fee_model": {"model_type": FeeModelType.PERCENT.value, "fee_rate": "0.001"}})

    after = provider("paper", DEFAULT_ACCOUNT_ID)
    assert after is exchange.fee_model
    assert after is not before
