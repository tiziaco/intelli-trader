"""Concrete paper venue / replay-data plugins (05-05, VENUE-02, D-05).

Formalizes the ``elif self.exchange == 'paper'`` composition-root block
(``live_trading_system.py`` ~554-590) into two registrable plugins:

  - ``PaperVenuePlugin`` — REUSES the compose-built ``'simulated'``
    ``SimulatedExchange`` AS-IS (injected at register time). Paper adds NO new
    exchange/adapter and NO cost-model extraction: with one shared fill-pricing
    implementation (the simulated exchange's, UNTOUCHED) there is nothing to
    drift, so PAPER-02 is satisfied-by-reuse (D-05). The bundle carries
    ``connector=None`` — paper has no live venue session, so the paper path NEVER
    touches the ``ConnectorProvider`` (D-05 backtest/paper firewall).
  - ``ReplayDataPlugin`` — builds the offline, synchronous ``ReplayDataProvider``
    that replays the golden ``CsvPriceStore`` over the shared ``PAPER_PARITY_*``
    window (the paper-parity comparand). The replay concretion imports live INSIDE
    ``build_provider`` (D-04 — the backtest import path never pulls them, the
    inertness gate).

Note ``'simulated'`` is deliberately NOT a registered venue name (D-05): it is the
compose-built backtest/paper fill engine, injected into ``PaperVenuePlugin`` at the
LTS root (``register('paper', PaperVenuePlugin(simulated_exchange))``), never
resolved through the registry.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# The paper-parity window anchor (single source): the replay store window/symbol/
# timeframe are wired from these so the paper comparand and the backtest can never
# silently desync (WR-02). These are pure string constants — importing them pulls
# nothing heavy, so re-homing the values here keeps the module import-inert while
# leaving the LTS constants (their canonical home) untouched.
PAPER_PARITY_START_DATE = "2018-01-01"
PAPER_PARITY_END_DATE = "2026-06-03"
PAPER_PARITY_SYMBOL = "BTCUSD"
PAPER_PARITY_TIMEFRAME = "1d"

if TYPE_CHECKING:
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider
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


class ReplayDataPlugin:
    """The paper ``DataProviderPlugin`` — builds the offline ``ReplayDataProvider`` (D-04).

    ``build_provider`` constructs the replay provider from the shared ``PAPER_PARITY_*``
    window (mirrors ``live_trading_system.py`` ~579-583). The replay concretion +
    CSV store imports live inside the body so the backtest import path never pulls
    them (the inertness gate, D-12).
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the ``ReplayDataProvider`` over the golden parity window (concretions lazy)."""
        # D-04/D-12: the replay provider + CSV store are lazy-imported inside the
        # body — never at module top — so the backtest hot path stays replay-free.
        from itrader.price_handler.providers.replay_provider import ReplayDataProvider
        from itrader.price_handler.store.csv_store import CsvPriceStore

        # D-18 (structural half): construct the replay store EXPLICITLY from the
        # shared parity window so the paper comparand and the backtest read ONE
        # source and can never silently desync (WR-02 coincidental parity gone).
        return ReplayDataProvider(
            store=CsvPriceStore(
                start_date=PAPER_PARITY_START_DATE, end_date=PAPER_PARITY_END_DATE
            ),
            symbol=PAPER_PARITY_SYMBOL,
            timeframe=PAPER_PARITY_TIMEFRAME,
        )
