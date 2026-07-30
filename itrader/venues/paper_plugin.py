"""Paper execution venue plugin — a config-driven ``SimulatedExchange`` behind the ``VenuePlugin`` Protocol.

``PaperVenuePlugin`` builds its own ``SimulatedExchange`` inside ``build_bundle`` from
the ``ExchangeConfig`` it receives at construction, symmetric with
``OkxVenuePlugin.build_bundle`` building its own ``OkxExchange`` — the venue plugin is
the one place a venue's exchange is minted, so ``ExecutionHandler`` asks
``VenueBundles`` for one rather than minting or holding it. The bundle carries
``connector=None``: paper has no live venue session and never touches a
``ConnectorProvider``.

The ``ExchangeConfig`` is passed in at construction, never built here or read off the
process-wide config singleton: the backtest factory folds this run's complete ticker
set into ``limits.supported_symbols`` (``_seed_supported_symbols``), and a plugin-side
default preset would silently narrow the tradeable symbol set — surfacing later as
refused orders far from the cause.

The exchange is built with ``rng=ctx.rng``, the one shared seeded ``random.Random`` of
the run: two ``random.Random(42)`` instances look identical until the call order
diverges, so a fresh or ``None`` rng breaks reproducibility silently.

The ``SimulatedExchange`` import lives inside ``build_bundle``, not at module scope,
so registering the plugin pulls no concretion.

Indentation: 4-space. ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from itrader.core.exceptions import ConfigurationError

if TYPE_CHECKING:
    from itrader.config.exchange import ExchangeConfig
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.bundle import VenueBundle


class PaperVenuePlugin:
    """The paper execution ``VenuePlugin`` — builds a fresh ``SimulatedExchange`` per call.

    Stateless across calls: single-instance-ness per ``(venue, account_id)`` is
    ``VenueBundles``' memo's job, never a second memo hand-rolled here.
    """

    def __init__(self, exchange_config: ExchangeConfig) -> None:
        # The run-derived ExchangeConfig, injected at register time. Only the
        # factory knows this run's complete symbol set, so it must ride in — this
        # plugin never constructs one and never reads the process-wide config
        # singleton (a default preset omits the golden ticker).
        self._exchange_config = exchange_config

    @property
    def credential_model(self) -> type[Any] | None:
        """``None`` — a paper account has no credentials to collect."""
        return None

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """``None`` — paper has no venue-side account to assert against."""
        return None

    def new_account(self, config: Any) -> Account:
        """Mint a fresh compute account from its config — the sole margin-vs-cash selection.

        Selects the margin superset when ``config.enable_margin``, else the plain spot
        cash leaf; the branch order matches the SMA_MACD byte-exact oracle path and
        must not be reordered.

        ``state_storage`` is forwarded rather than defaulted: the leaf routes reserved
        cash, locked margin and the cash-operation audit trail through it, and the live
        restart path (``state_storage.rehydrate(account)``) repopulates those caches on
        the portfolio's instance. A leaf left on its own private backend loses every
        reservation across a restart, while backtest stays byte-exact — so no test
        would catch a defaulted seam.

        No ``account_id`` is required or consulted here, unlike the venue arm, whose
        balance is one real venue account's truth and therefore conflatable across
        portfolios: a simulated leaf computes its own truth from its own portfolio, so
        there is nothing to conflate.

        The three knobs are read as plain attributes, never through a defaulted
        ``getattr`` — a defaulted read is how a missing seam becomes a private
        in-memory backend and a missing balance becomes a zero float literal.
        """
        from itrader.core.money import to_money
        from itrader.portfolio_handler.account import (
            SimulatedCashAccount,
            SimulatedMarginAccount,
        )

        state_storage = config.state_storage
        if state_storage is None:
            # VenueAccountConfig.state_storage still defaults to None because the OKX
            # arm legitimately supplies none (venue-cached truth needs no wiring seam),
            # so this plain attribute read can still hand the paper arm a None.
            # Forwarding it would rebuild the exact live-but-unpersisted leaf the
            # leaf's required keyword exists to prevent; PortfolioStateStorageFactory
            # stays the only producer of a seam, so this factory refuses rather than
            # minting one.
            raise ConfigurationError(
                "state_storage", None,
                "a paper compute account cannot be minted without the "
                "PortfolioStateStorage seam its owning portfolio's other managers "
                "hold: a leaf on a private backend loses every reservation across a "
                "live restart while backtest stays byte-exact (11.1-REVIEW WR-04)",
            )
        # The one entry into the Decimal domain on this path; to_money is idempotent
        # for a Decimal, so this is value-inert for callers that already pass one.
        initial_cash = to_money(config.initial_cash)
        # The compute leaf carries the (venue_name, account_id) pair so
        # Portfolio.venue_name / .account_id read it back from one storage site; the
        # paper arm still never uses account_id for wiring, but records the identity
        # so the portfolio and its leaf can never disagree about which account this is.
        if config.enable_margin:
            return SimulatedMarginAccount(
                initial_cash=initial_cash, state_storage=state_storage,
                account_id=config.account_id, venue_name=config.venue_name)
        return SimulatedCashAccount(
            initial_cash=initial_cash, state_storage=state_storage,
            account_id=config.account_id, venue_name=config.venue_name)

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the paper ``VenueBundle`` over a freshly-minted ``SimulatedExchange``."""
        from itrader.execution_handler.exchanges.simulated import SimulatedExchange
        from itrader.venues.bundle import VenueAccountConfig, VenueBundle

        exchange = SimulatedExchange(
            ctx.bus, config=self._exchange_config, rng=ctx.rng)

        def account_factory(
            *,
            initial_cash: Any,
            enable_margin: bool,
            account_id: str | None,
            state_storage: Any,
            venue_name: str | None = None,
        ) -> Account:
            # Delegates to the typed new_account so the bundle field and the Protocol
            # method can never mint different accounts. Keyword-only and explicit: an
            # (*args, **kwargs) catch-all type-checks clean against a structural
            # Protocol while silently returning one shared unscoped account, a defect
            # the type system cannot see. account_id is accepted and carried for
            # signature symmetry with the venue arm; the paper arm's new_account
            # deliberately never consults it — see its docstring.
            #
            # No parameter carries a default: this closure, not the account
            # constructors, is the seam a bundle's caller reaches, so it is the layer
            # that has to fail loud. Narrowing only the constructors
            # would close the trap one layer below where portfolios are built — a
            # caller omitting state_storage here would still sail through, because
            # `= None` would supply the argument the constructor demands.
            return self.new_account(VenueAccountConfig(
                account_id=account_id,
                venue_name=venue_name,
                initial_cash=initial_cash,
                enable_margin=enable_margin,
                state_storage=state_storage,
            ))

        # connectors is deliberately unread: paper has no venue session and holds no
        # credentials, and the parameter exists only to satisfy the VenuePlugin
        # Protocol. Reading anything off it here would put a credential-bearing
        # object on the paper/backtest path.
        return VenueBundle(
            exchange=exchange,
            account_factory=account_factory,
            connector=None,
        )


def paper_exchange_recipe(
    exchange_config: ExchangeConfig,
) -> Callable[..., AbstractExchange]:
    """The paper execution adapter in RECIPE form, bound to this run's exchange config.

    A one-line alias of ``execution_handler/exchanges/paper.py::paper_exchange_recipe``,
    which is the recipe's home — beside the adapter it builds, as every other recipe
    already is. This name survives only for the callers still reaching the paper venue
    through this module.
    """
    from itrader.execution_handler.exchanges.paper import (
        paper_exchange_recipe as _recipe,
    )

    return _recipe(exchange_config)
