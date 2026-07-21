"""assemble_venue / assemble_venues — resolve plugins, build bundle + provider + lifecycle (05-06, VENUE-06, D-06).

``assemble_venue`` is the SINGLE venue-assembly delegation seam (D-06). It resolves
the execution plugin from the ``ExecutionVenueRegistry`` and the data plugin from
the ``DataProviderRegistry``, builds the execution ``VenueBundle`` + the
``LiveDataProvider`` (both borrowing ONE memoized connector per ``(venue,
account_id)`` via the shared ``ConnectorProvider``, D-03), and wraps them in a
``VenueLifecycle`` — returning ``(bundle, lifecycle)``.

The LOGIC is authored ONCE here and unit-tested standalone against okx + paper
specs WITHOUT a ``LiveTradingSystem`` (D-06). ``LiveTradingSystem.__init__``
delegates to it this phase (P5), replacing the two ``if exchange=='okx'`` /
``elif=='paper'`` constructor blocks; P6 relocates the call site into
``build_live_system`` — the logic does not move again.

Fail-loud (D-01): an unregistered ``execution_venue`` / ``data_provider`` raises
``KeyError`` straight out of the registry ``get`` — a mis-specified venue never
silently wires a wrong one.

The ``"default"`` account_id fallback is applied INSIDE the plugins (05-05,
``spec.account_id or "default"``) — assemble does NOT re-default it.

``assemble_venues`` (11-09) is the PLURAL form: one ``VenueLifecycle`` per account
spec, keyed by account id. It is a plain FUNCTION beside ``assemble_venue``, NOT a
new type — the facade used to shatter one lifecycle into six scalar aliases
(``_venue_bundle`` / ``_okx_connector`` / ``_okx_exchange`` / ``_venue_account`` /
``_okx_data_provider``); you cannot have six scalars per account, but you can have
one lifecycle per account. ``VenueLifecycle`` already exposes ``.bundle`` /
``.provider``, so every former alias is a read THROUGH the lifecycle.

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
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry

# The ``spec.account_id or "default"`` normalization the venue plugins apply inside
# ``build_bundle`` (and ``venue_uid_guard`` mirrors). Declared locally rather than
# imported from ``execution_handler`` so this module keeps its zero-dependency
# import-inertness posture.
_DEFAULT_ACCOUNT_ID = "default"


def assemble_venue(
    ctx: Any,
    spec: Any,
    connectors: ConnectorProvider,
    exec_registry: ExecutionVenueRegistry,
    data_registry: DataProviderRegistry,
    account_store: Any = None,
    alert_sink: Any = None,
) -> tuple[VenueBundle, VenueLifecycle]:
    """Resolve the venue/data plugins, build the bundle + provider + lifecycle (D-06).

    Parameters
    ----------
    ctx :
        The ``EngineContext`` (the plugins read ``ctx.bus``).
    spec :
        The run spec carrying ``execution_venue`` / ``data_provider`` / ``account_id``.
    connectors :
        The shared ``ConnectorProvider`` — the exec + data plugins borrow ONE
        memoized connector per ``(venue, account_id)`` from it (D-03).
    exec_registry, data_registry :
        The two explicit-map registries; ``get`` fails loud (``KeyError``) on an
        unregistered venue (D-01).
    account_store, alert_sink :
        11-04 (D-04): the trust-on-first-use venue-UID guard's collaborators, handed
        to the ``VenueLifecycle`` so the guard runs on the post-connect seam. Optional
        because a deployment without a SQL arm has no ``VenueAccountStore`` — but the
        LIVE composition root supplies both, and the guard logs loudly when skipped.
        The ``plugin`` the guard needs is the exec plugin resolved BELOW: this function
        was previously resolving it locally and discarding it, which is why the
        lifecycle had no handle on it.

    Returns
    -------
    tuple[VenueBundle, VenueLifecycle]
        The built execution bundle + the lifecycle that orchestrates its connector
        start/stop (None-guarded for the connector-less paper bundle).
    """
    # D-01: fail loud on an unregistered venue (the registry get raises KeyError).
    exec_plugin = exec_registry.get(spec.execution_venue)
    # D-04: the concretion imports live inside build_bundle (never at module top).
    bundle = exec_plugin.build_bundle(ctx, spec, connectors)

    data_plugin = data_registry.get(spec.data_provider)
    provider = data_plugin.build_provider(ctx, spec, connectors)

    # D-04: the lifecycle carries the exec plugin + the pair identity so its
    # post-connect hook can run the venue-UID guard. ``account_id`` is passed RAW
    # (Optional[str]) — the guard applies the same ``or "default"`` normalization the
    # plugins apply inside ``build_bundle``, keeping that rule in ONE place rather
    # than duplicating it at every hand-off.
    lifecycle = VenueLifecycle(
        bundle,
        provider,
        connectors=connectors,
        plugin=exec_plugin,
        venue_name=spec.execution_venue,
        account_id=spec.account_id,
        account_store=account_store,
        alert_sink=alert_sink,
    )
    return bundle, lifecycle


def assemble_venues(
    ctx: Any,
    specs: Iterable[Any],
    connectors: ConnectorProvider,
    exec_registry: ExecutionVenueRegistry,
    data_registry: DataProviderRegistry,
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
        restarts.
    ctx, connectors, exec_registry, data_registry, account_store, alert_sink :
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
    for spec in specs:
        _bundle, lifecycle = assemble_venue(
            ctx,
            spec,
            connectors,
            exec_registry,
            data_registry,
            account_store=account_store,
            alert_sink=alert_sink,
        )
        lifecycles[getattr(spec, "account_id", None) or _DEFAULT_ACCOUNT_ID] = lifecycle
    return lifecycles
