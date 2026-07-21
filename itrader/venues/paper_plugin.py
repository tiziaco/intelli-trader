"""Concrete paper EXECUTION venue plugin (05-05, VENUE-02, D-05).

Formalizes the ``elif self.exchange == 'paper'`` composition-root execution block
(``live_trading_system.py``) into a registrable plugin:

  - ``PaperVenuePlugin`` — REUSES the compose-built ``'simulated'``
    ``SimulatedExchange`` AS-IS (injected at register time). Paper adds NO new
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

Note ``'simulated'`` is deliberately NOT a registered venue name (D-05): it is the
compose-built backtest/paper fill engine, injected into ``PaperVenuePlugin`` at the
LTS root (``register('paper', PaperVenuePlugin(simulated_exchange))``), never
resolved through the registry.

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

    Constructed at the LTS root WITH the already-built ``'simulated'``
    ``SimulatedExchange`` (``register('paper', PaperVenuePlugin(simulated_exchange))``).
    ``build_bundle`` wraps that exchange AS-IS (identity) with ``connector=None`` —
    NO new exchange/adapter, NO ConnectorProvider access (D-05).
    """

    def __init__(self, simulated_exchange: AbstractExchange) -> None:
        # The compose-built 'simulated' exchange, injected at register time. It
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

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the paper ``VenueBundle`` over the injected simulated exchange (connector=None)."""
        # D-04: the compute-account concretion is lazy-imported inside the body.
        from itrader.portfolio_handler.account import (
            SimulatedCashAccount,
            SimulatedMarginAccount,
        )
        from itrader.venues.bundle import VenueBundle

        def account_factory(portfolio: Any, initial_cash: Any = 0.0) -> Account:
            # Mirror the portfolio leaf-selection (portfolio.py:136-140): the margin
            # superset when enabled, else the verbatim-critical spot cash leaf (the
            # SMA_MACD byte-exact oracle path, D-04).
            if portfolio.config.trading_rules.enable_margin:
                return SimulatedMarginAccount(portfolio, initial_cash=initial_cash)
            return SimulatedCashAccount(portfolio, initial_cash=initial_cash)

        # D-05: reuse the simulated exchange AS-IS (identity); connector=None — the
        # `connectors` arg is deliberately unused (paper has no venue session).
        # lifecycle stays None — assemble_venue (05-06) builds the VenueLifecycle.
        return VenueBundle(
            exchange=self._simulated_exchange,
            account_factory=account_factory,
            connector=None,
        )
