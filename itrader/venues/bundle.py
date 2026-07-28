"""VenueBundle + the VenuePlugin / DataProviderPlugin build seams.

This module is the execution-only venue value object plus the two lazy-build
Protocols the registries hold. It is deliberately IMPORT-INERT: it constructs
nothing and imports no concretion at module scope — every domain type it
annotates against (``AbstractExchange`` / ``LiveConnector`` / ``Account`` /
``LiveDataProvider``) is pulled ONLY under ``TYPE_CHECKING`` with
``from __future__ import annotations`` in force, so importing ``venues.bundle``
pulls no ``ccxt`` / ``sqlalchemy`` / async machinery (verified by
``tests/integration/test_okx_inertness.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from itrader.connectors.base import LiveConnector
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider


@dataclass(frozen=True, slots=True)
class VenueAccountConfig:
    """The ``config`` argument of ``VenuePlugin.new_account``.

    A small frozen value object carrying exactly what the two shipped arms need to
    mint one account — nothing speculative:

    * ``account_id`` — the account this account is minted UNDER, and the ONLY
      source for it (``new_account`` takes no portfolio reference). There is no
      fallback for an absent id: minting an unnamed account under whichever account
      a bundle happens to be for would let two accounts collide, so the venue arm
      raises instead.
    * ``venue_name`` — the venue half of the ``(venue_name, account_id)`` pair,
      carried onto the built ``Account`` leaf as the identity ``Portfolio.venue_name``
      reads back. Optional because the byte-exact backtest leaf names no venue.
    * ``connectors`` / ``spec`` — the shared ``ConnectorProvider`` memo and the venue
      spec, so ``new_account`` resolves the connector for ITS OWN
      ``(venue, account_id)`` pair. Because the memo is pair-keyed, the account and
      the bundle's exchange share ONE authenticated session per account.
    * ``quote_currency`` / ``market_type`` / ``symbol`` — the venue-truth channel
      knobs the venue arm threads onto its ``VenueAccount``.
    * ``initial_cash`` — the compute arm's opening balance (the paper/simulated leaf).
    * ``enable_margin`` — selects the COMPUTE arm's leaf kind, the margin superset
      (``SimulatedMarginAccount``) versus the spot cash leaf
      (``SimulatedCashAccount``). It is sourced from the owning
      ``PortfolioConfig.trading_rules`` rather than read off a portfolio reference,
      so account-kind selection lives in exactly one place. The venue arm never
      reads it and always builds a ``VenueAccount`` — venue-cached truth has no
      margin-vs-cash choice to make.
    * ``state_storage`` — the shared ``PortfolioStateStorage`` seam the compute leaf
      routes its reserved cash, locked margin and cash-operation audit trail
      through. It MUST be the SAME instance the owning portfolio's three other
      managers hold: the live restart path calls ``state_storage.rehydrate(account)``
      and repopulates the reservation / locked-margin caches on THAT object, so a
      leaf on a private backend would silently lose every reservation across a
      restart while a backtest (where nothing else reads those containers) stayed
      byte-exact. Venue-truth accounts ignore it.

    Typed ``Any`` for ``connectors`` / ``spec`` / ``state_storage`` for the same
    import-inertness reason the rest of this module is: naming the concrete types
    would drag the venue substrate onto the backtest import graph.

    It lives HERE and not in ``paper_plugin.py`` because that module has a
    test-enforced single-class gate
    (``test_paper_plugin_module_holds_no_replay_symbol`` asserts the module defines
    ONLY ``PaperVenuePlugin``) — and because it is the shape of a Protocol argument,
    so the Protocol's own module is its home.
    """

    account_id: str | None = None
    venue_name: str | None = None
    connectors: Any = None
    spec: Any = None
    quote_currency: str = "USDT"
    market_type: Literal["spot", "derivative"] = "derivative"
    symbol: str | None = None
    initial_cash: Any = 0.0
    enable_margin: bool = False
    state_storage: Any = None


@dataclass(frozen=True, slots=True)
class VenueBundle:
    """The execution arm one venue plugin builds — frozen + slots.

    Carries ONLY the execution concerns: the ``exchange`` (an
    ``AbstractExchange`` — simulated for paper, ``OkxExchange`` for OKX) and the
    ``account_factory`` (builds the balance/margin ``Account`` leaf), signed
    KEYWORD-ONLY and delegating straight to ``VenuePlugin.new_account`` so the
    field and the Protocol method can never mint different accounts. The factory
    is never given an ``(*args, **kwargs)`` catch-all: an arg-swallowing arm would
    type-check clean against this STRUCTURAL Protocol while silently returning one
    shared unscoped account.

    Both fields are mandatory. The Optional live arm — ``connector``, the shared
    ``LiveConnector`` session — defaults to ``None``; paper carries none.

    The DATA provider is NOT a field here: it is built separately by
    ``DataProviderRegistry`` so execution-venue and data-provider selection stay
    independent.
    """

    exchange: AbstractExchange
    account_factory: Callable[..., Account]
    connector: LiveConnector | None = None


@runtime_checkable
class VenuePlugin(Protocol):
    """Structural build seam for an execution venue.

    ``@runtime_checkable`` so a fake plugin is swap-in for tests. ``build_bundle``
    is the LAZY-import seam: a concrete implementation keeps the venue concretion
    ``import`` (and credential construction) INSIDE the method body, never at module
    top or register time, so registering the plugin imports no ``ccxt.pro``
    (register ≠ build). It receives the shared ``ConnectorProvider`` so both the
    execution and data builders borrow the SAME memoized connector per
    ``(venue, account_id)``.
    """

    @property
    def credential_model(self) -> type[Any] | None:
        """The venue's credential/settings model class, or ``None`` if it has none.

        Makes the venue registry self-describing for credentials: a future
        integrations page can render per-venue form fields by reading this off the
        registry, with zero hardcoding — the alternative of the web app importing
        each venue's settings model directly would mean adding a venue requires
        editing the web app too.

        Declared as a ``@property`` rather than a plain class attribute so a concrete
        plugin can lazy-import its settings concretion in the body: the OKX plugin's
        AST gate (``test_okx_plugin.py``) rejects any module-level import whose name
        contains ``okx_settings``, so ``credential_model = OkxSettings`` would break
        that inertness check.
        """
        ...

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the execution ``VenueBundle`` (concretions lazy-imported inside)."""
        ...

    def new_account(self, config: VenueAccountConfig) -> Account:
        """Mint ONE ``Account`` leaf from its config — the SOLE factory.

        Promotes the untyped ``VenueBundle.account_factory`` field to a real typed
        member so account construction is a declared part of the venue seam rather
        than a closure a plugin happens to return. The venue-truth arm returns an
        account scoped to ``config.account_id``, built over the connector memoized
        for that ``(venue, account_id)`` pair; the compute arm returns a fresh
        simulated leaf of the kind ``config.enable_margin`` selects.

        This is the ONE place a venue's account kind is selected — ``Portfolio``
        receives a built account and selects nothing itself, so there is exactly one
        site to keep margin-vs-cash selection consistent.

        A catch-all ``(*args, **kwargs)`` signature would type-check clean against
        this STRUCTURAL Protocol while silently minting one shared unscoped account.
        The guard against that is ``VenueAccount.account_id`` being a REQUIRED
        keyword argument with no default: no arm can produce an unscoped account
        without naming one, and a config that names none raises rather than falling
        back to a "default" account.
        """
        ...

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """The venue's own account UID for the connected session, or ``None``.

        Keeps the trust-on-first-use guard (``venue_uid_guard.py``) venue-agnostic:
        the guard compares and alerts, the plugin knows the venue's endpoint and
        field. ``None`` means "this venue exposes no account UID" (paper), which the
        guard treats as a clean no-op.

        MUST NOT raise: this check is observe-only, so an exception here would abort
        an otherwise-healthy connect path.
        """
        ...


@runtime_checkable
class DataProviderPlugin(Protocol):
    """Structural build seam for a data provider.

    Mirror of ``VenuePlugin`` on the data axis: ``build_provider`` returns a
    ``LiveDataProvider`` with the venue concretion lazy-imported INSIDE the body.
    It borrows the SAME shared ``ConnectorProvider`` so it never opens a second
    ``ccxt.pro`` client for a ``(venue, account_id)`` the execution plugin already
    built.
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the venue's ``LiveDataProvider`` (concretions lazy-imported inside)."""
        ...
