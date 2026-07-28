"""assemble_venue — resolve the venue bundle + wrap it in a lifecycle.

``assemble_venue`` is the SINGLE venue-assembly delegation seam. It asks the shared
``VenueBundles`` memo for the execution ``VenueBundle`` of one ``(venue, account_id)``
pair and wraps it in a ``VenueLifecycle`` — returning ``(bundle, lifecycle)``.

**It builds NO data provider.** A discarded, unwired provider would be a live
credential-bearing object with no owner or halt path (each construction resolves its
own account's credentials through the ``CredentialResolver``). There is also no
"primary account" to privilege: the ONE live feed is bound to a CONNECTION by
``FeedConnectionBinder``, not handed to one account's lifecycle, so ``provider``
stays a keyword-only argument defaulting to ``None`` — the sole production caller
(``VenueAccountManager.bring_online``) never passes it.

**The bundle comes from the shared ``VenueBundles`` memo, never a direct registry
build.** Building it directly here could produce a different exchange instance from
the one ``ExecutionHandler`` / ``PortfolioHandler`` read off the memo for the same
``(venue, account_id)`` — two ``OkxExchange`` objects for one authenticated account
would double-spawn ``_stream_fills`` / ``_stream_orders``.

Fail-loud: an unregistered ``execution_venue`` raises ``KeyError`` straight out of
the registry ``get`` behind the memo, resolved BEFORE the bundle build so a
mis-specified venue never reaches a build. (The ``data_provider`` half of that guard
fires at ``FeedConnectionBinder``'s own ``DataProviderRegistry.get`` call, with the
same ``KeyError``.)

``account_id`` is read UNCOERCED and is REQUIRED — an absent id RAISES rather than
falling back to a default account (see the guard in the function body for why).

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free — the concretion imports
live inside the plugins' ``build*`` bodies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.core.exceptions import ValidationError
from itrader.venues.lifecycle import VenueLifecycle

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.price_handler.providers.live_provider import LiveDataProvider
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.bundles import VenueBundles


def assemble_venue(
    spec: Any,
    connectors: ConnectorProvider,
    bundles: VenueBundles,
    *,
    provider: LiveDataProvider | None = None,
    account_store: Any = None,
    alert_sink: Any = None,
) -> tuple[VenueBundle, VenueLifecycle]:
    """Resolve one account's shared bundle and wrap it in a lifecycle.

    Parameters
    ----------
    spec :
        The run spec carrying ``execution_venue`` / ``account_id``. (``data_provider``
        is read by ``FeedConnectionBinder``'s own data-provider build, not here.)
    connectors :
        The shared ``ConnectorProvider``. Not read here; handed to the lifecycle, whose
        ``stop()`` prefers ``close_all()`` over the bundle connector's own
        ``disconnect()``.
    bundles :
        The shared ``VenueBundles`` memo. Both the bundle and the venue plugin come
        from it, so the venue-assembly arm can never hold a different exchange from
        the one ``ExecutionHandler`` / ``PortfolioHandler`` read for the same
        ``(venue, account_id)``.
    provider :
        The ``LiveDataProvider`` bound to the ONE live feed, for a caller that wants
        it attached to this account's lifecycle. The boot path
        (``VenueAccountManager.bring_online``) never supplies one, since building an
        unused provider per account would leave an unwired, credential-bearing object
        with no owner. Injected at CONSTRUCTION rather than assigned afterwards: a
        lifecycle is never observable in a half-wired state.
    account_store, alert_sink :
        The trust-on-first-use venue-UID guard's collaborators, handed to the
        ``VenueLifecycle`` so the guard runs on the post-connect seam. Optional
        because a deployment without a SQL arm has no ``VenueAccountStore`` — but the
        LIVE composition root supplies both, and the guard logs loudly when skipped.

    Returns
    -------
    tuple[VenueBundle, VenueLifecycle]
        The shared execution bundle + the lifecycle that orchestrates its connector
        start/stop (None-guarded for the connector-less paper bundle).
    """
    venue = spec.execution_venue
    # ``account_id`` is read UNCOERCED and REQUIRED: an absent id is a wiring bug, not
    # a case to paper over with a "default" account — coercing it here while the
    # registration side keys the same account differently is how the exchange
    # registry and the connector memo end up disagreeing about the same real account.
    account_id = getattr(spec, "account_id", None)
    if account_id is None:
        raise ValidationError(
            "account_id",
            str(account_id),
            f"Cannot assemble venue '{venue}': the spec names no venue account, and "
            "there is no legitimate default one (ACCT-04/WR-03) — registration-side and "
            "resolution-side defaults are not symmetric",
        )
    # Resolved BEFORE the bundle so a mis-specified venue never reaches a build: the
    # registry get behind the memo raises KeyError on an unknown venue.
    exec_plugin = bundles.plugin_for(venue)
    # ASK the shared memo. NEVER ``exec_plugin.build_bundle(...)`` directly — that
    # bypass is what builds a second exchange per account. The concretion imports
    # live inside ``build_bundle`` itself, never at module top.
    bundle = bundles.get(venue, account_id, spec)

    # The lifecycle carries the exec plugin + the pair identity so its post-connect
    # hook can run the venue-UID guard. ``account_id`` is the SAME uncoerced id handed
    # to ``bundles.get`` above, with no substitution — so the memo key and the guard
    # can never disagree about the same real account.
    lifecycle = VenueLifecycle(
        bundle,
        provider=provider,
        connectors=connectors,
        plugin=exec_plugin,
        venue_name=venue,
        account_id=account_id,
        account_store=account_store,
        alert_sink=alert_sink,
    )
    return bundle, lifecycle
