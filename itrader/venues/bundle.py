"""VenueBundle + the VenuePlugin / DataProviderPlugin build seams (05-04, VENUE-01/02, D-02/D-04).

This module is the execution-only venue value object plus the two lazy-build
Protocols the registries hold. It is deliberately IMPORT-INERT: it constructs
nothing and imports no concretion at module scope — every domain type it
annotates against (``AbstractExchange`` / ``LiveConnector`` / ``Account`` /
``LiveDataProvider``) is pulled ONLY under ``TYPE_CHECKING`` with
``from __future__ import annotations`` in force, so importing ``venues.bundle``
pulls no ``ccxt`` / ``sqlalchemy`` / async machinery (the P5 acceptance gate,
``test_okx_inertness.py``).

Symbols
-------
- ``VenueBundle`` — a ``@dataclass(frozen=True, slots=True)`` carrying ONLY the
  execution arm (D-02): mandatory ``exchange`` + ``account_factory``; Optional
  ``connector`` / ``lifecycle`` defaulting to ``None`` (``None`` for paper, which
  reuses the compose-built ``'simulated'`` exchange and has no live connector).
  The DATA provider is deliberately NOT carried here — it is built by
  ``DataProviderRegistry`` so the two registries stay independently selectable
  (VENUE-01: OKX execution + a different data feed).
- ``VenuePlugin`` / ``DataProviderPlugin`` — ``@runtime_checkable`` Protocols
  mirroring the ``LiveConnector`` shape (``connectors/base.py``). ``build_bundle``
  / ``build_provider`` are the D-04 lazy-import seams: a concrete plugin (05-05)
  keeps the concretion ``import`` (and any ``OkxSettings()`` construction) INSIDE
  the method body — never at module top, never at register time — so registering
  a venue imports no concretion (register ≠ build).

Indentation: 4-SPACE (new top-level ``venues/`` package; no tab sibling to match).
``mypy --strict`` applies (new code).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from itrader.connectors.base import LiveConnector
    from itrader.execution_handler.exchanges.base import AbstractExchange
    from itrader.portfolio_handler.account.base import Account
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.lifecycle import VenueLifecycle


@dataclass(frozen=True, slots=True)
class VenueBundle:
    """The execution arm one venue plugin builds (D-02) — frozen + slots.

    Carries ONLY the execution concerns: the ``exchange`` (an
    ``AbstractExchange`` — simulated for paper, ``OkxExchange`` for OKX) and the
    per-portfolio ``account_factory`` (builds the balance/margin ``Account`` leaf).
    Both are mandatory. The Optional live arm — ``connector`` (the shared
    ``LiveConnector`` session) and ``lifecycle`` (the 05-06 ``VenueLifecycle``
    orchestrator) — defaults to ``None``; paper carries neither and is the
    ``None``-guarded case the lifecycle handles (D-10).

    The DATA provider is NOT a field here (D-02): it is built separately by
    ``DataProviderRegistry`` so execution-venue and data-provider selection stay
    independent (VENUE-01).
    """

    exchange: AbstractExchange
    account_factory: Callable[..., Account]
    connector: LiveConnector | None = None
    # 05-06: ``lifecycle`` carries the ``VenueLifecycle`` orchestrator. Now that the
    # type exists (``venues/lifecycle.py``) the 05-04 ``Any`` forward-seam is retyped
    # to ``VenueLifecycle | None``; the annotation stays a TYPE_CHECKING forward-ref
    # (``from __future__ import annotations`` in force) so this substrate module
    # remains import-inert. Plugins leave it ``None`` — ``assemble_venue`` returns the
    # lifecycle alongside the bundle rather than mutating this frozen field.
    lifecycle: "VenueLifecycle | None" = None


@runtime_checkable
class VenuePlugin(Protocol):
    """Structural build seam for an execution venue (VENUE-02 / D-04).

    ``@runtime_checkable`` (mirrors the ``LiveConnector`` seam) so a fake plugin
    is swap-in for tests. ``build_bundle`` is the D-04 LAZY-import seam: a concrete
    implementation keeps the venue concretion ``import`` (and credential
    construction) INSIDE the method body, never at module top or register time, so
    registering the plugin imports no ``ccxt.pro`` (register ≠ build — the
    inertness gate). It receives the shared ``ConnectorProvider`` so both the
    execution and data builders borrow the SAME memoized connector per
    ``(venue, account_id)`` (D-03).
    """

    @property
    def credential_model(self) -> type[Any] | None:
        """The venue's credential/settings model class, or ``None`` if it has none (D-03).

        Makes the venue REGISTRY self-describing for credentials: a future
        integrations page renders per-venue form fields by reading this off the
        registry, with ZERO hardcoding. The rejected alternative — the web app
        importing each venue's settings model directly — means adding a venue
        requires editing the web app too, reintroducing the per-venue branching an
        earlier phase spent itself deleting.

        Declared as a ``@property`` rather than a plain class attribute so a concrete
        plugin can LAZY-import its settings concretion in the body: the OKX plugin's
        AST gate (``test_okx_plugin.py``) rejects any module-level import whose name
        contains ``okx_settings``, so ``credential_model = OkxSettings`` would redden
        the inertness discipline this package exists to protect.
        """
        ...

    def build_bundle(self, ctx: Any, spec: Any, connectors: Any) -> VenueBundle:
        """Build the execution ``VenueBundle`` (concretions lazy-imported inside)."""
        ...

    def fetch_venue_uid(self, connector: Any) -> str | None:
        """The venue's own account UID for the connected session, or ``None`` (D-04).

        Keeps the trust-on-first-use guard (``venue_uid_guard.py``) VENUE-AGNOSTIC:
        the guard compares and alerts, the plugin knows the venue's endpoint and
        field. ``None`` means "this venue exposes no account UID" (paper), which the
        guard treats as a clean no-op.

        MUST NOT raise. D-04 is observe-only, so an exception here would abort a
        connect path that is otherwise healthy (T-11-19).
        """
        ...


@runtime_checkable
class DataProviderPlugin(Protocol):
    """Structural build seam for a data provider (VENUE-02 / D-04).

    Mirror of ``VenuePlugin`` on the data axis: ``build_provider`` returns a
    ``LiveDataProvider`` (05-03 uniform surface) with the venue concretion
    lazy-imported INSIDE the body (D-04). It borrows the SAME shared
    ``ConnectorProvider`` so it never opens a second ``ccxt.pro`` client for a
    ``(venue, account_id)`` the execution plugin already built (D-03).
    """

    def build_provider(self, ctx: Any, spec: Any, connectors: Any) -> LiveDataProvider:
        """Build the venue's ``LiveDataProvider`` (concretions lazy-imported inside)."""
        ...
