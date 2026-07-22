"""Concrete paper EXECUTION venue plugin (05-05, VENUE-02, D-05).

Formalizes the ``elif self.exchange == 'paper'`` composition-root execution block
(``live_trading_system.py``) into a registrable plugin:

  - ``PaperVenuePlugin`` — REUSES the compose-built ``SimulatedExchange`` AS-IS
    (injected at register time, read off the ``('paper', DEFAULT_ACCOUNT_ID)``
    registry key — 11.1's D-05 retired the ``'simulated'``/``'csv'`` synonyms so
    the venue name and the exchange key are now ONE name). Paper adds NO new
    exchange/adapter and NO cost-model extraction: with one shared fill-pricing
    implementation (the simulated exchange's, UNTOUCHED) there is nothing to
    drift, so PAPER-02 is satisfied-by-reuse (D-05). The bundle carries
    ``connector=None`` — paper has no live venue session, so the paper path NEVER
    touches the ``ConnectorProvider`` (D-05 backtest/paper firewall).

TEST-01/D-18/D-20/D-21: paper is a REAL live production mode — only its EXECUTION
venue lives here now. The offline replay DATA side (the data plugin, provider, and
golden-parity window that this module used to also hold) has LEFT the ``itrader``
package for ``tests/support/replay_harness.py``; production ``paper`` re-points to the
OKX live data feed (D-21), so the ``paper`` ↔ replay pairing now lives ONLY in the test
fixture, never in production.

Note ``'simulated'`` is NOT a venue name at all (Phase 5 D-05, hardened by 11.1's
D-05 which retired it from the exchange registry too): ``SimulatedExchange`` is the
class of the backtest/paper fill engine, and the ONE venue name that engine answers
to is ``'paper'``. The object is injected into ``PaperVenuePlugin`` at the LTS root
(``register('paper', PaperVenuePlugin(paper_exchange))``), never resolved through
the venue registry.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.bundle import VenueBundle


class PaperVenuePlugin:
    """The paper execution ``VenuePlugin`` — reuses the compose-built simulated exchange (D-05).

    Constructed at the LTS root WITH the already-built paper ``SimulatedExchange``
    (``register('paper', PaperVenuePlugin(paper_exchange))``).
    ``build_bundle`` wraps that exchange AS-IS (identity) with ``connector=None`` —
    NO new exchange/adapter, NO ConnectorProvider access (D-05).
    """

    def __init__(self, simulated_exchange: AbstractExchange) -> None:
        # The compose-built paper exchange, injected at register time. It
        # already satisfies AbstractExchange and holds no Account (D-06 — fills flow
        # FillEvent -> PortfolioHandler.on_fill), so it is reused verbatim.
        self._simulated_exchange = simulated_exchange

    @property
    def credential_model(self) -> type[Any] | None:
        """``None`` — a paper account has no credentials to collect (D-03).

        The integrations page reads this off the registry and renders NO credential
        form for paper, with no per-venue branching on its side.
        """
        return None

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """``None`` — paper has no venue-side account to assert against (D-04).

        The clean no-op case for the trust-on-first-use guard: there is no external
        identity to spoof, so nothing is recorded and nothing is alerted. A paper
        bundle also carries ``connector=None``, so the guard is skipped upstream by
        the lifecycle's structural ``None``-guard before it ever reaches here.
        """
        return None

    def new_account(self, portfolio_ref: Any, config: Any) -> Account:
        """Mint a FRESH compute account for one portfolio (D-10, 11-07).

        The leaf-selection body is the pre-11-07 ``account_factory`` VERBATIM: the
        margin superset when the portfolio's rules enable margin, else the
        verbatim-critical spot cash leaf that is the SMA_MACD byte-exact oracle path
        (D-04). It is copied, not restructured.

        No ``account_id`` is required or consulted here, and that asymmetry with the
        venue arm is deliberate: D-11 scopes VENUE accounts, whose balances and
        positions are one real venue account's truth and therefore conflatable. A
        simulated leaf computes its own truth from its own portfolio, so there is
        nothing to conflate and nothing for an account id to protect — requiring one
        would push a venue concept onto the oracle path for no safety gain.
        """
        # D-04: the compute-account concretions are lazy-imported inside the body.
        from itrader.portfolio_handler.account import (
            SimulatedCashAccount,
            SimulatedMarginAccount,
        )

        initial_cash = getattr(config, "initial_cash", 0.0)
        # D-01 (11.1-03): the leaves no longer take a portfolio back-reference.
        # `portfolio_ref` is still READ here — for the margin branch below, and to
        # forward the portfolio's shared state-storage seam so a minted leaf lands
        # on the same backend its sibling managers use (behaviour-identical to the
        # getattr the constructor used to do internally). Dropping `portfolio_ref`
        # from the signature entirely is D-03, in plan 11.1-09.
        state_storage = getattr(portfolio_ref, "state_storage", None)
        if portfolio_ref.config.trading_rules.enable_margin:
            return SimulatedMarginAccount(
                initial_cash=initial_cash, state_storage=state_storage)
        return SimulatedCashAccount(
            initial_cash=initial_cash, state_storage=state_storage)

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the paper ``VenueBundle`` over the injected simulated exchange (connector=None)."""
        # D-04: the bundle/config value objects are lazy-imported inside the body.
        from itrader.venues.bundle import VenueAccountConfig, VenueBundle

        def account_factory(portfolio: Any, initial_cash: Any = 0.0) -> Account:
            # 11-07: a thin adapter DELEGATING to the typed `new_account`, so the
            # bundle field and the Protocol method can never mint different accounts.
            return self.new_account(
                portfolio, VenueAccountConfig(initial_cash=initial_cash))

        # D-05: reuse the simulated exchange AS-IS (identity); connector=None — the
        # `connectors` arg is deliberately unused (paper has no venue session).
        # lifecycle stays None — assemble_venue (05-06) builds the VenueLifecycle.
        return VenueBundle(
            exchange=self._simulated_exchange,
            account_factory=account_factory,
            connector=None,
        )
