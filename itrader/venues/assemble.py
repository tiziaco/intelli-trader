"""assemble_venue / assemble_venues — resolve the venue bundle + wrap it in a lifecycle (05-06, VENUE-06, D-06).

``assemble_venue`` is the SINGLE venue-assembly delegation seam (D-06). It asks the
shared ``VenueBundles`` memo for the execution ``VenueBundle`` of one
``(venue, account_id)`` pair and wraps it in a ``VenueLifecycle`` — returning
``(bundle, lifecycle)``.

**It builds NO data provider (11.1-08, D-14).** It used to resolve a data plugin and
call ``build_provider`` for EVERY account, and every one of those providers except
the primary's was then discarded — ``VenueLifecycle`` only re-exposed it read-only.
That is ``11-REVIEW.md``'s WR-07: each construction resolves that account's OWN
credentials through the ``CredentialResolver``, so a discarded provider is a live
credential-bearing object with no owner, no lifecycle and no halt path. The review
proposed wiring them all; D-14 rejects that (there is ONE feed — wiring N providers
into it is meaningless) and removes the constructions instead. The composition root
now builds exactly ONE provider, explicitly, for the primary account, and hands it to
that account's lifecycle via the ``provider=`` keyword. Every other lifecycle
carries ``provider=None``.

**The bundle comes from the shared memo, never from a direct registry build
(11.1-08, D-08).** ``assemble_venue`` used to call
``exec_registry.get(venue).build_bundle(...)`` itself, which meant the venue-assembly
arm and ``ExecutionHandler``/``PortfolioHandler`` (which read ``VenueBundles``) could
hold two different exchanges for one ``(venue, account_id)``. Two ``OkxExchange``
objects for one authenticated account double-spawn ``_stream_fills`` /
``_stream_orders`` — the exact duplicate-session defect D-08 exists to close. One
memo, one build per pair, tree-wide.

The LOGIC is authored ONCE here and unit-tested standalone against okx + paper
specs WITHOUT a ``LiveTradingSystem`` (D-06). ``LiveTradingSystem.__init__``
delegates to it this phase (P5), replacing the two ``if exchange=='okx'`` /
``elif=='paper'`` constructor blocks; P6 relocates the call site into
``build_live_system`` — the logic does not move again.

Fail-loud (D-01): an unregistered ``execution_venue`` raises ``KeyError`` straight
out of the registry ``get`` behind the memo — a mis-specified venue never silently
wires a wrong one. (The ``data_provider`` half of that guard now fires at the
composition root's ONE ``DataProviderRegistry.get`` call, for the same reason and
with the same ``KeyError``.)

The ``"default"`` account_id fallback is applied INSIDE the plugins (05-05,
``spec.account_id or "default"``) for the connector memo. 11.1-08: assemble now
applies the SAME rule once more when calling ``VenueBundles.get``, whose
``account_id`` is a REQUIRED argument by design (11.1-05) — normalizing inside the
memo would put the rule in two places and let the memo and the exchange registry
disagree about an unnamed account. The RAW ``spec.account_id`` still reaches the
lifecycle, which owns the guard's normalization.

``assemble_venues`` (11-09) is the PLURAL form: one ``VenueLifecycle`` per account
spec, keyed by account id. It is a plain FUNCTION beside ``assemble_venue``, NOT a
new type — the facade used to shatter one lifecycle into six scalar aliases
(``_venue_bundle`` / ``_okx_connector`` / ``_okx_exchange`` / ``_venue_account`` /
``_okx_data_provider``); you cannot have six scalars per account, but you can have
one lifecycle per account. ``VenueLifecycle`` already exposes ``.bundle`` /
``.provider``, so every former alias is a read THROUGH the lifecycle. (Post-D-14
``.provider`` is populated on the PRIMARY lifecycle only — which is exactly what the
one alias it replaced, the single ``_okx_data_provider``, always was.)

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free (the P5 inertness gate) —
the concretion imports live inside the plugins' ``build*`` bodies (D-04). That
property holds for the plural form too: it only loops over the singular one.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.venues.lifecycle import VenueLifecycle

if TYPE_CHECKING:
    from collections.abc import Iterable

    from itrader.connectors.provider import ConnectorProvider
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.bundles import VenueBundles

# The ``spec.account_id or "default"`` normalization the venue plugins apply inside
# ``build_bundle`` (and ``venue_uid_guard`` mirrors). Declared locally rather than
# imported from ``execution_handler`` so this module keeps its zero-dependency
# import-inertness posture.
_DEFAULT_ACCOUNT_ID = "default"


def assemble_venue(
    spec: Any,
    connectors: ConnectorProvider,
    bundles: VenueBundles,
    *,
    provider: LiveDataProvider | None = None,
    account_store: Any = None,
    alert_sink: Any = None,
) -> tuple[VenueBundle, VenueLifecycle]:
    """Resolve one account's shared bundle and wrap it in a lifecycle (D-06/D-08/D-14).

    Parameters
    ----------
    spec :
        The run spec carrying ``execution_venue`` / ``account_id``. (``data_provider``
        is read by the composition root's ONE ``build_provider`` call, not here — D-14.)
    connectors :
        The shared ``ConnectorProvider``. Not read here; handed to the lifecycle, whose
        ``stop()`` prefers ``close_all()`` over the bundle connector's own
        ``disconnect()``.
    bundles :
        The shared ``VenueBundles`` memo (D-08). Both the bundle and the venue plugin
        come from it, so the venue-assembly arm can never hold a different exchange
        from the one ``ExecutionHandler`` / ``PortfolioHandler`` read for the same
        ``(venue, account_id)``. It replaces the former ``exec_registry`` /
        ``data_registry`` pair: a second registry argument beside the memo would let
        the guard's plugin and the bundle's builder diverge.
    provider :
        11.1-08 (D-14): the ONE ``LiveDataProvider`` bound to the ONE feed, supplied by
        the composition root for the PRIMARY account only. Every other account passes
        ``None`` — a non-primary provider is not built at all, so it cannot be left
        unwired (WR-07). Injected at CONSTRUCTION rather than assigned afterwards: a
        lifecycle is never observable in a half-wired state.
    account_store, alert_sink :
        11-04 (D-04): the trust-on-first-use venue-UID guard's collaborators, handed
        to the ``VenueLifecycle`` so the guard runs on the post-connect seam. Optional
        because a deployment without a SQL arm has no ``VenueAccountStore`` — but the
        LIVE composition root supplies both, and the guard logs loudly when skipped.

    Returns
    -------
    tuple[VenueBundle, VenueLifecycle]
        The shared execution bundle + the lifecycle that orchestrates its connector
        start/stop (None-guarded for the connector-less paper bundle).
    """
    venue = spec.execution_venue
    # The ``spec.account_id or "default"`` normalization is applied HERE, at the call
    # site, because ``VenueBundles.get`` takes ``account_id`` as a REQUIRED argument
    # (11.1-05) — normalizing in two places is how the exchange registry and the
    # connector memo end up disagreeing about an unnamed account.
    account_id = getattr(spec, "account_id", None) or _DEFAULT_ACCOUNT_ID
    # D-01: fail loud on an unregistered venue (the registry get behind the memo
    # raises KeyError). Resolved BEFORE the bundle so a mis-specified venue never
    # reaches a build.
    exec_plugin = bundles.plugin_for(venue)
    # D-08: ASK the shared memo. NEVER ``exec_plugin.build_bundle(...)`` — that is the
    # bypass that builds a second exchange per account.
    # D-04: the concretion imports live inside build_bundle (never at module top).
    bundle = bundles.get(venue, account_id, spec)

    # D-04: the lifecycle carries the exec plugin + the pair identity so its
    # post-connect hook can run the venue-UID guard. ``account_id`` is passed RAW
    # (Optional[str]) — the guard applies the same ``or "default"`` normalization the
    # plugins apply inside ``build_bundle``, keeping that rule in ONE place rather
    # than duplicating it at every hand-off.
    lifecycle = VenueLifecycle(
        bundle,
        provider=provider,
        connectors=connectors,
        plugin=exec_plugin,
        venue_name=venue,
        account_id=getattr(spec, "account_id", None),
        account_store=account_store,
        alert_sink=alert_sink,
    )
    return bundle, lifecycle


def assemble_venues(
    specs: Iterable[Any],
    connectors: ConnectorProvider,
    bundles: VenueBundles,
    *,
    primary_provider: LiveDataProvider | None = None,
    account_store: Any = None,
    alert_sink: Any = None,
) -> dict[str, VenueLifecycle]:
    """One ``VenueLifecycle`` per account spec, keyed by account id (11-09, D-19).

    A plain function over ``assemble_venue`` — deliberately NOT a new class. The
    composition root used to keep the primary account's lifecycle and pre-derive five
    scalar aliases off it (bundle / connector / exchange / account / provider), which
    is unrepresentable once there is more than one account. Holding the LIFECYCLE per
    account instead of its pieces makes the multi-account shape fall out with no new
    concept: ``lifecycles[account_id].bundle.exchange`` replaces ``_okx_exchange``,
    ``.bundle.connector`` replaces ``_okx_connector``, ``.provider`` replaces
    ``_okx_data_provider``, and ``.bundle.account_factory(portfolio)`` replaces the
    single unscoped ``_venue_account``.

    Parameters
    ----------
    specs :
        The per-account venue specs, PRIMARY FIRST. Ordering is the caller's
        contract (``_account_ids_for_spec`` pins it): the returned ``dict`` preserves
        insertion order, so ``next(iter(...))`` is the deterministic primary. One
        data provider is wired to the one feed, so the primary must not vary across
        restarts — and 11.1-08 makes that contract load-bearing rather than incidental,
        because the FIRST spec is the one that receives ``primary_provider``.
    primary_provider :
        11.1-08 (D-14): the ONE ``LiveDataProvider`` the composition root built for the
        feed. It is handed to the FIRST spec's lifecycle and to no other — the
        primary-is-first ordering contract above is the single home of that rule, so no
        caller re-derives "which account is primary". ``None`` (the default, and the
        whole map's value on a venue with no data arm) leaves every lifecycle
        provider-less, which is a supported state: ``VenueLifecycle`` never reads it.
    connectors, bundles, account_store, alert_sink :
        Threaded verbatim into each ``assemble_venue`` call.

    Returns
    -------
    dict[str, VenueLifecycle]
        Keyed by ``spec.account_id or "default"`` — the SAME key
        ``ExecutionHandler.exchanges`` and the venue plugins' connector memo use, so
        venue, exchange registry and lifecycle map all agree on one account key.

    Notes
    -----
    Unit-testable standalone with NO ``LiveTradingSystem`` — the same property
    ``assemble_venue`` carries, and the reason the assembly logic lives here rather
    than in the composition root.
    """
    lifecycles: dict[str, VenueLifecycle] = {}
    for index, spec in enumerate(specs):
        _bundle, lifecycle = assemble_venue(
            spec,
            connectors,
            bundles,
            # D-14: ONE feed, ONE provider — the PRIMARY account's, and the primary is
            # the first spec. Handing it to index 0 here (rather than at the call site)
            # keeps the ordering contract documented above as its own enforcement.
            provider=primary_provider if index == 0 else None,
            account_store=account_store,
            alert_sink=alert_sink,
        )
        lifecycles[getattr(spec, "account_id", None) or _DEFAULT_ACCOUNT_ID] = lifecycle
    return lifecycles
