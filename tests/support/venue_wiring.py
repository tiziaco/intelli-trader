"""ONE shared backtest venue-wiring recipe for the direct-construction test sites.

``ExecutionHandler`` does not mint its own ``SimulatedExchange``; the composition root
builds one and injects the ``(venue, account_id) -> exchange`` map. Every test that
builds an ``ExecutionHandler`` directly therefore needs the same recipe production uses.

This module exists so those sites share ONE recipe rather than five. Five hand-rolled
copies drift: one gets a default-preset config while the run needs a seeded one, another
forgets the shared RNG, and the resulting divergence from production wiring is invisible
until a test proves something production never does. Change the recipe HERE and every
site moves together.

``exchange_config`` defaults to ``default_exchange_config()`` — the preset UNION
``{BTCUSD}``, which is what these sites historically got from the handler's own
no-config fallback, so their symbol admission is unchanged. A REAL run passes its
run-derived config; this default is the fallback for callers that have none.

4-SPACE indentation (tests house style).
"""

from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, Optional

from itrader.execution_handler.exchanges.paper import build_paper_exchange
from itrader.execution_handler.execution_handler import (
    COMPUTE_VENUE,
    DEFAULT_ACCOUNT_ID,
    default_exchange_config,
)
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler


def backtest_exchange_registry(
    bus: Any,
    *,
    exchange_config: Optional[Any] = None,
    rng: Optional[random.Random] = None,
) -> Any:
    """Build the backtest-shaped ``(venue, account_id) -> exchange`` registry.

    ``ExecutionHandler`` never builds or holds its own registry — the map is
    composition-root-owned and injected. Every direct-construction test site that builds
    an ``ExecutionHandler`` therefore needs the SAME seed the backtest root produces: one
    connected paper exchange under the ``(paper, default)`` pair key, built through the
    venue's own recipe so a directly-built handler resolves what production resolves.

    ``rng`` defaults to ``random.Random(42)``, the run-wide determinism seed.
    """
    exchange = build_paper_exchange(
        exchange_config=exchange_config or default_exchange_config(),
        bus=bus,
        rng=rng if rng is not None else random.Random(42),
    )
    return {(COMPUTE_VENUE, DEFAULT_ACCOUNT_ID): exchange}


def single_account_read_model(account_id: str = DEFAULT_ACCOUNT_ID) -> Any:
    """The one-account ``PortfolioReadModel`` stand-in a direct ``ExecutionHandler`` needs.

    ``ExecutionHandler`` resolves EVERY order's venue account through an injected
    read-model — there is no mode-dependent default, because a default is what routes one
    account's orders through another account's session. A test that builds the handler
    around a bare exchange registry, with no portfolio handler behind it, still has to say
    which account its orders belong to; this says "the one the registry is keyed under".
    """
    return SimpleNamespace(account_for=lambda portfolio_id: account_id)


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
    from itrader.portfolio_handler.storage import build_portfolio_state_storage

    return build_portfolio_state_storage("backtest")


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

    It reaches the account THROUGH ``build_compute_account`` rather than constructing a
    ``SimulatedCashAccount`` directly, and that indirection is the point: that function
    is the SOLE owner of the margin-vs-cash rule, so a test tree that hand-builds leaves
    would quietly stop agreeing with production the first time that rule changed. Going
    through the one constructor means every site follows automatically.

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
    from itrader.portfolio_handler.account.simulated import build_compute_account

    seam = (
        state_storage if state_storage is not None
        else in_memory_state_storage()
    )
    return build_compute_account(
        initial_cash=initial_cash,
        enable_margin=enable_margin,
        state_storage=seam,
        # The compute leaf is the ONE storage site for the (venue_name, account_id)
        # pair. A direct-construction test that wants its Portfolio to REPORT an
        # identity must build the account with it — ``Portfolio.venue_name`` /
        # ``.account_id`` read the leaf, not a second copy the portfolio stores.
        account_id=account_id,
        venue_name=venue_name,
    )


def backtest_portfolio_factory(
    bus: Any,
    *,
    environment: str = "backtest",
    sql_engine: Any = None,
) -> Any:
    """A backtest-shaped ``PortfolioFactory`` over a validator-less ``AccountFactory``.

    ``PortfolioHandler`` builds every portfolio's account leaf THROUGH an injected
    ``PortfolioFactory`` (D-24), whose ``AccountFactory`` on the backtest arm carries no
    validator and never raises. Every direct-construction test site that creates portfolios
    needs the same recipe; this is it. ``environment`` / ``sql_engine`` thread the durable
    state-storage selectors so the factory scopes state storage exactly as the handler
    expects.

    ``bus`` is accepted and unread: the account factory builds its leaf directly and
    touches no exchange. It stays in the signature because every call site passes it
    positionally and the handler recipe below forwards it.
    """
    from itrader.portfolio_handler.portfolio_factory import (
        AccountFactory,
        PortfolioFactory,
    )

    return PortfolioFactory(
        account_factory=AccountFactory(),
        environment=environment, sql_engine=sql_engine)


def backtest_portfolio_handler(bus: Optional[Any] = None, **kwargs: Any) -> Any:
    """A ``PortfolioHandler`` wired to a backtest-shaped ``PortfolioFactory`` (D-24).

    ``add_portfolio`` now builds each portfolio's account leaf THROUGH the injected
    factory (D-24), so a handler constructed without one REFUSES rather than minting one
    inline. Every direct-construction test site that creates portfolios needs the same
    recipe; this is it.

    The factory's authority is built over the bus so the exchange the paper plugin mints
    publishes onto the same queue the handler does — the shape production wires. The queue
    may arrive positionally or as ``global_queue=``; both call shapes exist in the tree.
    ``environment`` / ``sql_engine`` (if supplied) are threaded into the factory too so its
    state-storage selectors match the handler's.
    """
    if bus is None:
        bus = kwargs.pop('global_queue')
    if 'portfolio_factory' not in kwargs:
        kwargs['portfolio_factory'] = backtest_portfolio_factory(
            bus,
            environment=kwargs.get('environment', 'backtest'),
            sql_engine=kwargs.get('sql_engine'),
        )
    return PortfolioHandler(bus, **kwargs)
