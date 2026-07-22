"""Portfolio identity plumbing: supplyable id, account_id, venue-derived exchange.

Plan 11-05 (F-1 / F-5 / D-06 / D-07 / D-27, MPORT-05).

F-1 is a real pre-existing defect: ``Portfolio.__init__`` minted a fresh UUIDv7 on
EVERY construction with no way to pass an existing one, while two in-tree comments
asserted restart-stability that did not exist. On a restart the prior run's
portfolio-scoped state rows were orphaned. These tests pin the fixed contract:

* the id is SUPPLYABLE (never re-schemed — omitting it still mints through the
  single UUIDv7 ``idgen`` singleton),
* every portfolio can name its venue ``account_id`` (D-06),
* ``exchange`` is DERIVED from ``venue_name`` when supplied (D-07),
* the legacy ``add_portfolio(name, exchange, cash)`` shape — the byte-exact
  backtest oracle call — is unchanged,
* ``account_for`` mirrors ``exchange_for`` on the read-model seam (D-27).
"""

import uuid
from datetime import datetime, UTC
from decimal import Decimal
from queue import Queue
from types import SimpleNamespace

import pytest

from itrader import idgen
from itrader.core.exceptions import PortfolioNotFoundError, PortfolioValidationError
from itrader.core.ids import PortfolioId
from itrader.core.portfolio_read_model import PortfolioReadModel
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler


_NAME = "identity_pf"
_EXCHANGE = "paper"
_CASH = 100000


@pytest.fixture
def env():
    """A PortfolioHandler (test environment) + its global queue."""
    global_queue = Queue()
    handler = PortfolioHandler(
        global_queue=global_queue,
        config_dir="settings",
        environment="test",
    )
    yield SimpleNamespace(global_queue=global_queue, handler=handler)
    while not global_queue.empty():
        global_queue.get_nowait()


def _portfolio(**kwargs) -> Portfolio:
    """A Portfolio built on the default (backtest/in-memory) path."""
    defaults = dict(
        name=_NAME,
        exchange=_EXCHANGE,
        cash=Decimal("100000"),
        time=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return Portfolio(**defaults)


# ---------------------------------------------------------------------------
# F-1 — portfolio_id is SUPPLYABLE (the restart-stability fix)
# ---------------------------------------------------------------------------


def test_supplied_portfolio_id_survives_construction_verbatim():
    """F-1: a rehydrated portfolio keeps the id its durable child tables are keyed by."""
    existing = PortfolioId(idgen.generate_portfolio_id())
    portfolio = _portfolio(portfolio_id=existing)
    assert portfolio.portfolio_id == existing


def test_omitted_portfolio_id_still_mints_a_fresh_uuidv7():
    """F-1: the id becomes SUPPLYABLE, never re-schemed — omitting it mints via idgen."""
    first = _portfolio()
    second = _portfolio()
    assert isinstance(first.portfolio_id, uuid.UUID)
    assert first.portfolio_id.version == 7
    assert first.portfolio_id != second.portfolio_id


def test_supplied_id_is_not_re_minted_on_collision():
    """Uniqueness is a composition-time invariant (plan 11-08), not a constructor re-mint."""
    existing = PortfolioId(idgen.generate_portfolio_id())
    assert _portfolio(portfolio_id=existing).portfolio_id == existing
    assert _portfolio(portfolio_id=existing).portfolio_id == existing


def test_state_storage_is_scoped_to_the_supplied_id():
    """The id supplied on rehydrate is what reattaches the portfolio-scoped child tables."""
    existing = PortfolioId(idgen.generate_portfolio_id())
    portfolio = _portfolio(portfolio_id=existing)
    assert portfolio.state_storage is not None
    assert portfolio.portfolio_id == existing


# ---------------------------------------------------------------------------
# D-06 / D-07 — account_id and the venue_name-derived exchange
# ---------------------------------------------------------------------------


def test_account_id_is_recorded_on_the_portfolio():
    """D-06: every portfolio names an account — there are not two classes of portfolio."""
    assert _portfolio(account_id="acct_a").account_id == "acct_a"


def test_account_id_defaults_to_none():
    """The default exists ONLY to keep the byte-exact backtest call site untouched."""
    assert _portfolio().account_id is None


def test_exchange_is_derived_from_venue_name():
    """D-07: venue_name WINS — exchange is derived, never a second source of truth."""
    portfolio = _portfolio(exchange="paper", venue_name="okx")
    assert portfolio.venue_name == "okx"
    assert portfolio.exchange == "okx"


def test_exchange_falls_back_to_the_legacy_parameter():
    """The legacy `exchange` input is used as-is when no venue_name is supplied."""
    portfolio = _portfolio(exchange="paper")
    assert portfolio.exchange == "paper"
    assert portfolio.venue_name is None


# ---------------------------------------------------------------------------
# add_portfolio — the same three inputs, and the untouched legacy shape
# ---------------------------------------------------------------------------


def test_legacy_add_portfolio_shape_is_unchanged(env):
    """The backtest composition-root call shape still works and mints a fresh id."""
    portfolio_id = env.handler.add_portfolio(name=_NAME, exchange="paper", cash=_CASH)
    portfolio = env.handler.get_portfolio(portfolio_id)
    assert isinstance(portfolio_id, uuid.UUID)
    assert portfolio_id.version == 7
    assert portfolio.exchange == "paper"
    assert portfolio.account_id is None
    assert portfolio.venue_name is None


def test_add_portfolio_threads_all_three_new_inputs(env):
    """F-5: the three inputs land on one signature and reach the Portfolio verbatim."""
    existing = PortfolioId(idgen.generate_portfolio_id())
    returned = env.handler.add_portfolio(
        name=_NAME,
        exchange=_EXCHANGE,
        cash=_CASH,
        portfolio_id=existing,
        account_id="acct_a",
        venue_name="paper",
    )
    assert returned == existing
    portfolio = env.handler.get_portfolio(existing)
    assert portfolio.account_id == "acct_a"
    assert portfolio.venue_name == "paper"
    assert portfolio.exchange == "paper"


def test_duplicate_supplied_portfolio_id_raises_instead_of_clobbering(env):
    """Now that ids are supplyable, a re-add must NOT silently destroy the first
    portfolio, its cash and its positions."""
    existing = PortfolioId(idgen.generate_portfolio_id())
    env.handler.add_portfolio(name=_NAME, exchange=_EXCHANGE, cash=_CASH, portfolio_id=existing)
    with pytest.raises(PortfolioValidationError):
        env.handler.add_portfolio(
            name="second", exchange=_EXCHANGE, cash=_CASH, portfolio_id=existing
        )
    assert env.handler.get_portfolio_count() == 1
    assert env.handler.get_portfolio(existing).name == _NAME


# ---------------------------------------------------------------------------
# D-27 — account_for on the read-model seam
# ---------------------------------------------------------------------------


def test_account_for_returns_the_portfolios_account_id(env):
    """D-27: the account half of the (venue, account_id) routing pair."""
    portfolio_id = env.handler.add_portfolio(
        name=_NAME, exchange=_EXCHANGE, cash=_CASH, account_id="acct_a"
    )
    assert env.handler.account_for(portfolio_id) == "acct_a"


def test_account_for_returns_none_when_no_account_named(env):
    """`Portfolio.account_id` is `str | None`; the seam reports that honestly."""
    portfolio_id = env.handler.add_portfolio(name=_NAME, exchange=_EXCHANGE, cash=_CASH)
    assert env.handler.account_for(portfolio_id) is None


def test_account_for_unknown_id_matches_exchange_for(env):
    """The two methods behave identically on a missing id."""
    unknown = PortfolioId(idgen.generate_portfolio_id())
    with pytest.raises(PortfolioNotFoundError):
        env.handler.exchange_for(unknown)
    with pytest.raises(PortfolioNotFoundError):
        env.handler.account_for(unknown)


def test_handler_still_satisfies_the_read_model_protocol(env):
    """D-16: structural conformance survives the Protocol gaining account_for."""
    assert isinstance(env.handler, PortfolioReadModel)
