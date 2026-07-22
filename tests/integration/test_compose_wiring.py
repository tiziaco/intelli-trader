"""compose_engine dependency-wiring tests (Plan 10.1-01, DECOMP-01a).

These pin the three ``StrategiesHandler`` deps that used to be assigned AFTER
construction by the live composition root and are now real at ``__init__``:

- ``registry_store`` is handler-derived from ``(environment, sql_engine)`` — ``None``
  on the backtest path, which keeps every persist arm a clean no-op.
- ``portfolio_read_model`` is the SAME ``portfolio_handler`` object compose just built
  (it structurally satisfies the ``PortfolioReadModel`` Protocol). Asserted by identity,
  not equality: the point is that it IS that object, not one equal to it.
- ``strategy_catalog`` rides in as a ``compose_engine`` kwarg and defaults to ``None``,
  keeping the D-10 LOUD-reject on a catalog-less ``add`` reachable.

Driven against a REAL ``compose_engine`` call over a backtest ``EngineContext``
(``FifoEventBus`` + ``CsvPriceStore`` + ``BacktestBarFeed``, ``sql_engine=None``),
mirroring the register-vs-build block in ``test_okx_inertness.py`` so no database is
needed. 4-space indentation (tests house style).
"""

import random

import pytest

from itrader import config as _config
from itrader.events_handler.bus import FifoEventBus
from itrader.execution_handler.execution_handler import DEFAULT_ACCOUNT_ID
from itrader.outils.time_parser import to_timedelta
from itrader.price_handler.feed.bar_feed import BacktestBarFeed
from itrader.price_handler.store.csv_store import CsvPriceStore
from itrader.trading_system.compose import compose_engine
from itrader.trading_system.engine_context import EngineContext

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


def test_portfolio_read_model_is_the_composed_portfolio_handler(
    ctx: EngineContext,
) -> None:
    engine = compose_engine(ctx)
    # D-11 flat-detect seam: an injected READ-model, never a cross-domain call.
    assert (
        engine.strategies_handler.portfolio_read_model is engine.portfolio_handler
    )


def test_strategy_catalog_defaults_to_none(ctx: EngineContext) -> None:
    engine = compose_engine(ctx)
    # D-10: stays None when not supplied, so `add`'s LOUD-reject remains reachable
    # and no external payload can be instantiated on a catalog-less handler.
    assert engine.strategies_handler.strategy_catalog is None


def test_strategy_catalog_is_threaded_through_compose(ctx: EngineContext) -> None:
    catalog = {"SomeStrategy": object}
    engine = compose_engine(ctx, strategy_catalog=catalog)
    assert engine.strategies_handler.strategy_catalog is catalog


def test_the_composed_exchange_holds_the_ctx_rng_instance(ctx: EngineContext) -> None:
    """VENUE-06/D-07: the exchange draws from the ctx's RNG OBJECT, not a copy of it.

    Asserted by ``is`` and never ``==``: two ``random.Random(42)`` instances compare as
    distinct objects but LOOK identical — same seed, same first draw — until either is
    drawn from, at which point the call ORDER diverges and the run silently leaves the
    byte-exact oracle. Equality of seed proves nothing; only identity does.
    """
    engine = compose_engine(ctx)
    # Registry lookup: read `ExecutionHandler.init_exchanges` before changing this key.
    # It is currently the (venue, account_id) PAIR with the simulated venue on
    # DEFAULT_ACCOUNT_ID. Plan 11.1-06 re-keys that registry and plan 11.1-07 changes
    # WHO builds the exchange (the venue plugin) — both will need to update this line.
    exchange = engine.execution_handler.exchanges[("simulated", DEFAULT_ACCOUNT_ID)]
    assert exchange._rng is ctx.rng


def test_backtest_context_yields_no_registry_store(ctx: EngineContext) -> None:
    engine = compose_engine(ctx)
    # DECOMP-01a: derived from (environment='backtest', sql_engine=None) -> None.
    assert engine.strategies_handler.registry_store is None
