"""VENUE-02: Portfolio RECEIVES its account; the venue plugin is the sole factory.

Plan 11.1-09 (D-02 / D-03). These pin the OWNERSHIP property the phase exists to
establish, which the requirement probe could not classify into a data-shape category:

* ``Portfolio`` is constructible ONLY with an account supplied — omitting it raises
  ``TypeError`` rather than silently minting one (T-11.1-41);
* no branch inside ``Portfolio`` selects an account KIND — the margin-vs-cash rule
  has exactly one owner, ``VenuePlugin.new_account`` (D-03);
* the account a portfolio ends up holding is the EXACT object its venue bundle
  minted for it, proven by ``is``-identity in a TWO-account setup;
* that account and the portfolio's three managers share ONE
  ``PortfolioStateStorage`` instance;
* the account's opening balance and the portfolio's ``cash`` cannot diverge
  (T-11.1-42).

**Why two accounts and not one.** In the single-account backtest a correctly-bound
account and a freshly-minted default leaf are indistinguishable: both are a
``SimulatedCashAccount`` with the right opening cash, so an existence assertion
(``portfolio.account is not None``, or an ``isinstance`` check) passes against an
implementation that mints its own and ignores the one composition built. Two
portfolios whose accounts differ in cash AND in identity is the smallest setup where
a wrong binding is observable.

This directory is package-less (NO ``__init__.py``, per MEMORY: two same-named
top-level test packages break full-suite collection). 4-SPACE indentation.
"""

from __future__ import annotations

import inspect
import queue
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from itrader.core.exceptions import PortfolioConfigurationError, ValidationError
from itrader.portfolio_handler.account import (
    SimulatedCashAccount,
    SimulatedMarginAccount,
)
from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from tests.support.venue_wiring import (
    backtest_portfolio_handler,
    backtest_venue_bundles,
    compute_account,
)


class _RecordingBundles:
    """Wraps a real ``VenueBundles`` and records every account its factory mints.

    A DELEGATING wrapper rather than a fake: the bundle, the plugin and the minting
    body are the production ones, so the identity these tests assert is the identity
    production produces. Only the observation is added.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.minted: list[Any] = []

    def get(self, venue: str, account_id: str, spec: Any) -> Any:
        from types import SimpleNamespace

        bundle = self._inner.get(venue, account_id, spec)

        def recording_factory(**kwargs: Any) -> Any:
            account = bundle.account_factory(**kwargs)
            self.minted.append(account)
            return account

        return SimpleNamespace(
            exchange=bundle.exchange,
            account_factory=recording_factory,
            connector=bundle.connector,
        )


def _handler() -> tuple[PortfolioHandler, _RecordingBundles]:
    bus = queue.Queue()
    bundles = _RecordingBundles(backtest_venue_bundles(bus))
    return PortfolioHandler(bus, venue_bundles=bundles), bundles


# ---------------------------------------------------------------------------
# D-02 — the account is RECEIVED, never minted
# ---------------------------------------------------------------------------


def test_portfolio_cannot_be_constructed_without_an_account() -> None:
    """VENUE-02: omitting the account is a TypeError, never a silent default.

    A default here would be a mint-on-omission path: every construction site that
    forgot to pass one would receive a plausible-looking account of whatever kind the
    default chose, and the mistake would surface as wrong settlement behaviour far
    from its cause rather than at the call site.
    """
    with pytest.raises(TypeError):
        Portfolio("no_account_pf", "paper", Decimal("1000"), datetime.now(UTC))


def test_the_account_parameter_has_no_default() -> None:
    """The same claim asserted on the SIGNATURE, so it survives call-shape churn."""
    parameter = inspect.signature(Portfolio.__init__).parameters["account"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_portfolio_never_re_selects_the_account_kind() -> None:
    """D-03: the margin flag on the config does NOT make Portfolio swap the leaf.

    The selection rule lives in ``VenuePlugin.new_account`` and nowhere else. This
    hands a portfolio whose config enables margin a CASH leaf — a combination the
    composition root never produces — and asserts the portfolio keeps exactly what it
    was given. An implementation that re-derived the kind from ``self.config`` would
    quietly upgrade it, which is the duplicate branch D-03 deleted.
    """
    from itrader.config import PortfolioConfig

    margin_config = PortfolioConfig.default()
    margin_config.trading_rules.enable_margin = True
    cash_leaf = compute_account(Decimal("1000"))

    portfolio = Portfolio(
        "kind_pf", "paper", Decimal("1000"), datetime.now(UTC),
        config=margin_config, account=cash_leaf,
    )

    assert portfolio.account is cash_leaf
    assert isinstance(portfolio.account, SimulatedCashAccount)
    assert not isinstance(portfolio.account, SimulatedMarginAccount)


def test_portfolio_module_constructs_no_account_leaf() -> None:
    """No CALL to either simulated leaf survives in ``portfolio.py`` (D-02).

    ``SimulatedMarginAccount`` is still IMPORTED there as a narrowing type for
    ``_require_margin_account``'s isinstance guard, so an import-level grep would
    false-positive. This walks the AST for a CALL instead, which is the actual claim:
    the module mints nothing.
    """
    import ast
    import pathlib

    import itrader.portfolio_handler.portfolio as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text())
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"SimulatedCashAccount", "SimulatedMarginAccount"}


# ---------------------------------------------------------------------------
# D-02/D-08 — the portfolio holds the EXACT account its bundle minted
# ---------------------------------------------------------------------------


def test_each_portfolio_holds_the_exact_account_its_bundle_minted() -> None:
    """TWO accounts, asserted by IDENTITY — a lucky default cannot pass this.

    With one portfolio, a correct binding and a freshly-minted default leaf are the
    same observable object shape. Here two portfolios open at DIFFERENT cash, so a
    handler that minted its own would have to reproduce both values by accident, and
    ``is`` rules out a different-but-equal account entirely.
    """
    handler, bundles = _handler()

    first = handler.add_portfolio(
        name="pf-one", exchange="paper", cash=Decimal("10000"), venue_name="paper")
    second = handler.add_portfolio(
        name="pf-two", exchange="paper", cash=Decimal("25000"), venue_name="paper")

    assert len(bundles.minted) == 2
    minted_one, minted_two = bundles.minted

    assert handler.get_portfolio(first).account is minted_one
    assert handler.get_portfolio(second).account is minted_two
    assert minted_one is not minted_two
    assert minted_one.balance == Decimal("10000.00")
    assert minted_two.balance == Decimal("25000.00")


def test_the_margin_flag_reaches_the_plugin_from_the_portfolio_config() -> None:
    """D-03: ``PortfolioConfig.trading_rules.enable_margin`` selects the leaf KIND.

    The config that drives the selection is the SAME one the portfolio runs on — the
    handler resolves it once and uses it for both, so a portfolio cannot end up on a
    margin config with a cash ledger.
    """
    from itrader.config import PortfolioConfig

    handler, _ = _handler()
    margin_config = PortfolioConfig.default()
    margin_config.trading_rules.enable_margin = True

    cash_id = handler.add_portfolio(
        name="pf-cash", exchange="paper", cash=Decimal("10000"), venue_name="paper")
    margin_id = handler.add_portfolio(
        name="pf-margin", exchange="paper", cash=Decimal("10000"),
        venue_name="paper", portfolio_config=margin_config)

    cash_account = handler.get_portfolio(cash_id).account
    margin_account = handler.get_portfolio(margin_id).account
    assert isinstance(margin_account, SimulatedMarginAccount)
    assert isinstance(cash_account, SimulatedCashAccount)
    assert not isinstance(cash_account, SimulatedMarginAccount)


def test_a_handler_without_venue_bundles_refuses_rather_than_minting() -> None:
    """The tempting inline fallback is a second account-kind selection — so: refuse.

    A ``SimulatedCashAccount(...)`` here would only ever run in misconfigured wiring,
    so it would reinstate the duplicate branch D-03 deleted on a path nothing covers.
    """
    handler = PortfolioHandler(queue.Queue())
    with pytest.raises(PortfolioConfigurationError):
        handler.add_portfolio(name="pf", exchange="paper", cash=Decimal("1000"))


# ---------------------------------------------------------------------------
# The shared state-storage seam (the silent-corruption shape)
# ---------------------------------------------------------------------------


def test_the_account_and_the_managers_share_one_state_storage() -> None:
    """ONE ``PortfolioStateStorage`` instance across the leaf and its three siblings.

    The account is now built BEFORE its portfolio exists, so this is the invariant a
    naive implementation breaks: the leaf routes reserved cash, locked margin and its
    cash-operation audit trail through the seam, and the live restart path
    (``state_storage.rehydrate(account)``) repopulates those caches on the PORTFOLIO's
    instance. Two instances lose every reservation across a restart — and stay
    byte-exact in backtest, where nothing else reads those containers, so the oracle
    and the whole suite would remain green.
    """
    handler, _ = _handler()
    portfolio_id = handler.add_portfolio(
        name="pf-seam", exchange="paper", cash=Decimal("10000"), venue_name="paper")
    portfolio = handler.get_portfolio(portfolio_id)

    seam = portfolio.state_storage
    assert portfolio.account.state_storage is seam
    assert portfolio.position_manager._storage is seam
    assert portfolio.transaction_manager._storage is seam
    assert portfolio.metrics_manager._storage is seam


def test_two_portfolios_do_not_share_a_state_storage() -> None:
    """Each portfolio's seam is its OWN — the sharing is within a portfolio, not across.

    The mirror of the test above. A handler that built one seam and reused it would
    make two portfolios' reservations and positions visible to each other.
    """
    handler, _ = _handler()
    first = handler.get_portfolio(handler.add_portfolio(
        name="pf-a", exchange="paper", cash=Decimal("10000"), venue_name="paper"))
    second = handler.get_portfolio(handler.add_portfolio(
        name="pf-b", exchange="paper", cash=Decimal("10000"), venue_name="paper"))

    assert first.state_storage is not second.state_storage
    assert first.account.state_storage is not second.account.state_storage


def test_a_directly_constructed_portfolio_adopts_its_accounts_seam() -> None:
    """The adoption direction, asserted on the direct-construction path too."""
    account = compute_account(Decimal("500"))
    portfolio = Portfolio(
        "adopt_pf", "paper", Decimal("500"), datetime.now(UTC), account=account)

    assert portfolio.state_storage is account.state_storage
    assert portfolio.position_manager._storage is account.state_storage


# ---------------------------------------------------------------------------
# T-11.1-42 — the ledger and the portfolio cannot open at different cash
# ---------------------------------------------------------------------------


def test_an_account_opening_at_different_cash_is_refused() -> None:
    """The two are built by different code now, so the disagreement must be loud.

    ``add_portfolio`` computes ``to_money(cash)`` once and passes it to both. A caller
    that supplies one value to the portfolio and another to the account factory would
    otherwise produce a portfolio whose reported opening cash and whose ledger
    disagree, with nothing red.
    """
    with pytest.raises(ValidationError):
        Portfolio(
            "mismatch_pf", "paper", Decimal("10000"), datetime.now(UTC),
            account=compute_account(Decimal("999")),
        )


def test_the_handler_opens_the_ledger_at_exactly_the_requested_cash() -> None:
    """The happy path of the same invariant, through the real composition seam."""
    handler = backtest_portfolio_handler(queue.Queue())
    portfolio = handler.get_portfolio(handler.add_portfolio(
        name="pf-cash", exchange="paper", cash=Decimal("1234.56"),
        venue_name="paper"))

    assert portfolio.account.balance == Decimal("1234.56")
