"""The backtest root builds its own venue — asserted at the CONSTRUCTION SITE.

The root no longer resolves its exchange through a venue plugin; it constructs the
``SimulatedExchange``, keys it under ``(paper, default)`` and hands the registry to
``build_handler_graph``. Three of the things it threads there are invisible to the
golden oracle, so the oracle alone cannot protect them:

* **the seeded RNG.** ``SimulatedExchange.__init__`` reads ``rng or random.Random()``,
  so a root that forgot to pass ``ctx.rng`` gets a system-seeded generator instead of
  raising — and with the default zero-slippage model nothing draws from it, so the
  oracle stays byte-exact while the run stops being reproducible.
* **the run-derived exchange config.** A default preset omits the golden ticker; the
  oracle would catch that, but not a narrower symbol set on any OTHER run.
* **the connect.** ``SimulatedExchange.validate_order`` refuses orders on a
  disconnected exchange.

BOTH construction arms are asserted: ``test_backtest_oracle.py`` drives the legacy
``__init__`` arm and ``test_backtest_oracle_factory_arm.py`` the factory arm, and a
wiring assertion against only one goes false-green against the other.

4-space indentation (tests house style).
"""

import random

import pytest

from itrader import config as _config
from itrader.execution_handler.execution_handler import (
    COMPUTE_VENUE,
    DEFAULT_ACCOUNT_ID,
)
from itrader.execution_handler.exchanges.simulated import SimulatedExchange
from itrader.trading_system.backtest.backtest_trading_system import (
    BacktestTradingSystem,
    build_backtest_system,
)
from itrader.trading_system.system_spec import SystemSpec

pytestmark = pytest.mark.integration

_PAIR = (COMPUTE_VENUE, DEFAULT_ACCOUNT_ID)


def _legacy_arm() -> BacktestTradingSystem:
    """The direct-construction arm the byte-exact oracle drives."""
    return BacktestTradingSystem(exchange="paper", start_date="2018-01-01")


def _factory_arm() -> BacktestTradingSystem:
    """The ``build_backtest_system(spec)`` arm."""
    return build_backtest_system(SystemSpec(
        start="2018-01-01", end="", timeframe="1d", ticker="BTCUSD",
        starting_cash=10_000, data={}, strategies=[], portfolios=[]))


@pytest.fixture(params=[_legacy_arm, _factory_arm], ids=["legacy", "factory"])
def system(request) -> BacktestTradingSystem:
    return request.param()


def test_the_paper_exchange_is_registered_under_the_default_account_pair(system):
    exchange = system.execution_handler.exchanges[_PAIR]
    assert isinstance(exchange, SimulatedExchange)


def test_the_exchange_holds_the_runs_seeded_rng(system):
    """The exchange's RNG is the one seeded from ``config.rng_seed``, not a fresh one.

    Compared by generator STATE: a system-seeded ``random.Random()`` cannot match the
    state of a freshly seeded one, so this fails the moment the root stops threading
    ``ctx.rng`` — which nothing else in the suite would notice.
    """
    exchange = system.execution_handler.exchanges[_PAIR]
    assert exchange._rng.getstate() == random.Random(int(_config.rng_seed)).getstate()


def test_the_exchange_is_connected(system):
    """A disconnected paper venue refuses every order at ``validate_order``."""
    exchange = system.execution_handler.exchanges[_PAIR]
    assert exchange.health_check().connected is True


def test_the_exchange_carries_the_run_derived_symbol_set(system):
    """The golden ticker is admitted — the default preset alone omits it."""
    exchange = system.execution_handler.exchanges[_PAIR]
    assert "BTCUSD" in exchange.config.limits.supported_symbols


def test_the_portfolio_factory_is_the_one_the_handler_builds_leaves_through(system):
    """One factory object, held by the handler the root wired it into."""
    factory = system.portfolio_handler._factory
    assert factory is not None
    portfolio_id = system.portfolio_handler.add_portfolio(
        name="wiring_pf", exchange="paper", venue_name="paper", cash=1_000)
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    # The account leaf names the compute venue's one account, so the order router
    # resolves the pair the exchange above is registered under.
    assert portfolio.account_id == DEFAULT_ACCOUNT_ID
    assert system.execution_handler._portfolio_read_model is system.portfolio_handler
