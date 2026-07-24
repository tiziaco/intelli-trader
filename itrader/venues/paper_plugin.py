"""Concrete paper EXECUTION venue plugin (05-05, VENUE-02, D-05/D-06/D-17).

Formalizes the ``elif self.exchange == 'paper'`` composition-root execution block
(``live_trading_system.py``) into a registrable plugin:

  - ``PaperVenuePlugin`` — BUILDS its OWN ``SimulatedExchange`` inside
    ``build_bundle`` from the ``ExchangeConfig`` it receives at CONSTRUCTION
    (D-06/D-17). It is exactly symmetric with ``OkxVenuePlugin.build_bundle``
    building its own ``OkxExchange``: the venue plugin is the ONE place a venue's
    exchange is minted, so ``ExecutionHandler`` neither mints one nor is handed
    one — it ASKS ``VenueBundles`` (D-08). Paper still adds NO cost-model
    extraction: with one shared fill-pricing implementation (the simulated
    exchange's, UNTOUCHED) there is nothing to drift, so PAPER-02 stays
    satisfied-by-reuse (D-05). The bundle carries ``connector=None`` — paper has
    no live venue session, so the paper path NEVER touches the
    ``ConnectorProvider`` (D-05 backtest/paper firewall).

D-17 — the ``ExchangeConfig`` is PASSED, never imported. It is RUN-DERIVED: the
backtest factory folds this run's COMPLETE ticker set into
``limits.supported_symbols`` (``_seed_supported_symbols``), and ``ExchangeConfig``
is not a field on ``ITraderConfig`` at all. A plugin-side default preset would
silently narrow the tradeable symbol set — the golden ``BTCUSD`` ticker is NOT in
``ExchangeConfig.default()`` — and the failure would surface as refused orders far
from its cause.

D-07 — the exchange is built with ``rng=ctx.rng``, the ONE shared seeded
``random.Random`` of the run. Never a fresh one and never ``None``
(``exchanges/simulated.py`` documents that ``None`` yields an unseeded RNG).

GATE-01 — the ``SimulatedExchange`` import lives INSIDE ``build_bundle``, matching
the same register-is-not-build idiom ``new_account`` uses for the account leaves.
Registering a plugin must pull no concretion.

TEST-01/D-18/D-20/D-21: paper is a REAL live production mode — only its EXECUTION
venue lives here now. The offline replay DATA side (the data plugin, provider, and
golden-parity window that this module used to also hold) has LEFT the ``itrader``
package for ``tests/support/replay_harness.py``; production ``paper`` re-points to the
OKX live data feed (D-21), so the ``paper`` ↔ replay pairing now lives ONLY in the test
fixture, never in production.

Note ``'simulated'`` is NOT a venue name at all (Phase 5 D-05, hardened by 11.1's
D-05 which retired it from the exchange registry too): ``SimulatedExchange`` is the
class of the backtest/paper fill engine, and the ONE venue name that engine answers
to is ``'paper'``. Registration reads
``register('paper', PaperVenuePlugin(exchange_config))`` — a config, never an
exchange, and never a venue synonym.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.core.exceptions import ConfigurationError

if TYPE_CHECKING:
    from itrader.config.exchange import ExchangeConfig
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.bundle import VenueBundle


class PaperVenuePlugin:
    """The paper execution ``VenuePlugin`` — builds its own simulated exchange (D-06/D-17).

    Constructed at the composition root WITH the run's ``ExchangeConfig``
    (``register('paper', PaperVenuePlugin(exchange_config))``). ``build_bundle``
    then mints a ``SimulatedExchange`` from that config, sharing ``ctx.rng`` (the
    one seeded RNG, D-07), and returns it with ``connector=None`` — no
    ConnectorProvider access at all (D-05).

    The plugin is STATELESS across calls: two ``build_bundle`` calls build two
    exchanges. Single-instance-ness per ``(venue, account_id)`` is ``VenueBundles``'
    memo's job (D-08), never a second memo hand-rolled here.
    """

    def __init__(self, exchange_config: ExchangeConfig) -> None:
        # D-17: the RUN-DERIVED ExchangeConfig, injected at register time. Only the
        # factory knows this run's complete symbol set, so it must ride in — this
        # plugin never constructs one and never reads the process-wide config
        # singleton (a default preset omits the golden ticker).
        self._exchange_config = exchange_config

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

    def new_account(self, config: Any) -> Account:
        """Mint a FRESH compute account from its config — the SOLE factory (D-03).

        The leaf-selection body is the pre-11-07 ``account_factory`` VERBATIM in
        BRANCH ORDER: the margin superset when ``enable_margin``, else the
        verbatim-critical spot cash leaf that is the SMA_MACD byte-exact oracle path
        (D-04). It is copied, not restructured — reordering the arms is what
        ``test_paper_new_account_selects_the_margin_leaf_when_enabled`` exists to
        catch.

        D-03 (11.1-09): this is now the ONLY margin-vs-cash selection in the tree.
        The duplicate branch in ``Portfolio._init_managers`` is deleted; a
        ``Portfolio`` receives the account this method built (D-02) and selects
        nothing. The three values the branch needs — ``initial_cash``,
        ``enable_margin`` and the shared ``state_storage`` seam — used to be read off
        a ``portfolio_ref`` argument; they now ride on ``config``, put there by
        ``PortfolioHandler.add_portfolio``, which holds the ``PortfolioConfig`` and
        builds the seam. That is what lets an account be built BEFORE the portfolio
        that owns it exists.

        ``state_storage`` is forwarded rather than defaulted for a correctness
        reason, not a tidiness one: the leaf routes reserved cash, locked margin and
        the cash-operation audit trail through it, and the live restart path
        (``state_storage.rehydrate(account)``) repopulates those caches on the
        PORTFOLIO's instance. A leaf left on its own private backend loses every
        reservation across a restart — and stays byte-exact in backtest, where
        nothing else reads those containers, so no test would go red.

        No ``account_id`` is required or consulted here, and that asymmetry with the
        venue arm is deliberate: D-11 scopes VENUE accounts, whose balances and
        positions are one real venue account's truth and therefore conflatable. A
        simulated leaf computes its own truth from its own portfolio, so there is
        nothing to conflate and nothing for an account id to protect — requiring one
        would push a venue concept onto the oracle path for no safety gain.

        11.1-REVIEW **WR-08**: the three knobs are read as plain ATTRIBUTES, never
        through a defaulted ``getattr``. A defaulted read is how a missing seam
        became a private in-memory backend and a missing balance became a zero float
        literal — two silent substitutions in a factory whose whole job is to be the
        single honest place an account is minted. Cash enters the Decimal domain
        HERE, at the boundary, via ``to_money``.
        """
        # D-04: the compute-account concretions are lazy-imported inside the body.
        from itrader.core.money import to_money
        from itrader.portfolio_handler.account import (
            SimulatedCashAccount,
            SimulatedMarginAccount,
        )

        state_storage = config.state_storage
        if state_storage is None:
            # WR-04 backstop. ``VenueAccountConfig.state_storage`` still defaults to
            # ``None`` because the OKX arm legitimately supplies none (venue-cached
            # truth takes no wiring seam), so a plain attribute read CAN hand this
            # arm a ``None``. Forwarding it would rebuild the exact
            # live-but-unpersisted leaf the leaf's required keyword removes — and it
            # would do so one hop away from the type checker, since the config field
            # is typed ``Any``. ``PortfolioStateStorageFactory`` stays the ONLY
            # producer of a seam; this factory refuses rather than minting one.
            raise ConfigurationError(
                "state_storage", None,
                "a paper compute account cannot be minted without the "
                "PortfolioStateStorage seam its owning portfolio's other managers "
                "hold: a leaf on a private backend loses every reservation across a "
                "live restart while backtest stays byte-exact (11.1-REVIEW WR-04)",
            )
        # D-12 money policy: the ONE entry into the Decimal domain on this path. The
        # leaf quantizes at its own ledger boundary; ``to_money`` is idempotent for a
        # Decimal, so this is value-inert for every caller that already passes one.
        initial_cash = to_money(config.initial_cash)
        # D-23 (11.2-08): the compute leaf CARRIES the (venue_name, account_id) pair
        # so ``Portfolio.venue_name`` / ``.account_id`` read it back from the ONE
        # storage site. The paper arm still never USES ``account_id`` for wiring (a
        # simulated leaf computes its own truth), but it now RECORDS the identity so
        # the portfolio and its leaf can never disagree about which account this is.
        if config.enable_margin:
            return SimulatedMarginAccount(
                initial_cash=initial_cash, state_storage=state_storage,
                account_id=config.account_id, venue_name=config.venue_name)
        return SimulatedCashAccount(
            initial_cash=initial_cash, state_storage=state_storage,
            account_id=config.account_id, venue_name=config.venue_name)

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the paper ``VenueBundle`` over a freshly-minted ``SimulatedExchange``.

        D-06: the plugin builds its own exchange, exactly as ``OkxVenuePlugin``
        builds its own ``OkxExchange``. D-17: from the config injected at
        construction — the run-derived one, never a preset. D-07: sharing
        ``ctx.rng``, the one seeded RNG of the run.
        """
        # D-04/GATE-01: the exchange + bundle/config value objects are lazy-imported
        # inside the body. The SimulatedExchange import MUST stay here — a
        # module-top concretion import in a plugin is precisely what the
        # register-is-not-build inertness gate exists to catch.
        from itrader.execution_handler.exchanges.simulated import SimulatedExchange
        from itrader.venues.bundle import VenueAccountConfig, VenueBundle

        # D-07: ``ctx.rng`` is the ONE shared seeded random.Random — the exchange and
        # its slippage model both draw from THIS object. Passing a fresh instance (or
        # None, which yields an unseeded RNG) breaks reproducibility silently, because
        # two random.Random(42) objects look identical until the call ORDER diverges.
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
            # 11-07: a thin adapter DELEGATING to the typed `new_account`, so the
            # bundle field and the Protocol method can never mint different accounts.
            # 11.1-09 (D-03): KEYWORD-ONLY and explicit. The `(*args, **kwargs)`
            # catch-all 11-07 removed is NOT reinstated — an arg-swallowing arm
            # type-checks clean against a STRUCTURAL Protocol while silently
            # returning one shared unscoped account, a defect the type system cannot
            # see. `account_id` is accepted and carried for signature symmetry with
            # the venue arm (both bundles are called uniformly by
            # `PortfolioHandler.add_portfolio`); the paper arm's `new_account`
            # deliberately never consults it — see its docstring.
            #
            # 11.1-REVIEW WR-08: NO parameter carries a default, and that is the
            # load-bearing half of this change. THIS closure — not the account
            # constructors — is the seam `PortfolioHandler._new_compute_account`
            # calls, so it is the layer that has to fail loud. Narrowing only the
            # constructors would close the trap one layer BELOW where portfolios are
            # built: a caller omitting `state_storage` here would still sail through,
            # because `= None` would supply the argument the constructor demands. A
            # defaulted cash/margin knob is the same class of defect one field over —
            # a plausible-looking account nobody chose, opened at a float zero.
            return self.new_account(VenueAccountConfig(
                account_id=account_id,
                venue_name=venue_name,
                initial_cash=initial_cash,
                enable_margin=enable_margin,
                state_storage=state_storage,
            ))

        # connector=None — the `connectors` argument is DELIBERATELY UNREAD. Paper has
        # no venue session and holds no credentials; the parameter exists only to
        # satisfy the `VenuePlugin` Protocol. Reading anything off it here would put a
        # credential-bearing object on the paper/backtest path (D-05 firewall), and the
        # exploding double in tests/unit/venues/test_paper_plugin.py proves it stays
        # untouched.
        # lifecycle stays None — assemble_venue (05-06) builds the VenueLifecycle.
        return VenueBundle(
            exchange=exchange,
            account_factory=account_factory,
            connector=None,
        )
