"""assemble_venue — resolve the venue bundle + wrap it in a lifecycle (05-06, VENUE-06, D-06).

``assemble_venue`` is the SINGLE venue-assembly delegation seam (D-06). It asks the
shared ``VenueBundles`` memo for the execution ``VenueBundle`` of one
``(venue, account_id)`` pair and wraps it in a ``VenueLifecycle`` — returning
``(bundle, lifecycle)``.

**It builds NO data provider (11.1-08, D-14).** It used to resolve a data plugin and
drive its provider build for EVERY account, and every one of those providers except
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

ACCT-04/WR-03: ``account_id`` is read UNCOERCED and is REQUIRED. After ACCT-03 a
live spec always names an account, so ``assemble_venue`` no longer applies a
``spec.account_id or DEFAULT_ACCOUNT_ID`` fallback — an absent id RAISES instead. The
deleted coercion keyed an unnamed account onto ``"default"`` HERE while the exchange
registry's write side keyed the SAME account differently: a write-only registry entry
no reader reached. Registration-side and resolution-side defaults are not symmetric,
and normalizing in two places is how the exchange registry and the connector memo end
up disagreeing about the same real account. The ONE uncoerced id now feeds both
``VenueBundles.get`` (the memo key) and the lifecycle (which arms the guard), so the
write side and the read side agree.

**The PLURAL boot loop is GONE (11.2-07, D-36).** ``assemble_venues`` — the "one
``VenueLifecycle`` per account spec, PRIMARY FIRST" helper — was DELETED with the
spec-derived boot it served. The boot now reads its account set off durable rows and
brings each online through ``VenueAccountManager.bring_online``, which calls this
singular ``assemble_venue`` once per row. D-36 also deletes "primary account" as a
concept: the feed is bound to a CONNECTION by ``FeedConnectionBinder``, not handed to a
privileged first account's lifecycle, so ``assemble_venue``'s ``provider`` kwarg is left
at its ``None`` default on the boot path (``VenueLifecycle`` never reads it — a
provider-less lifecycle is fully functional).

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free (the P5 inertness gate) —
the concretion imports live inside the plugins' ``build*`` bodies (D-04).

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
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
    """Resolve one account's shared bundle and wrap it in a lifecycle (D-06/D-08/D-14).

    Parameters
    ----------
    spec :
        The run spec carrying ``execution_venue`` / ``account_id``. (``data_provider``
        is read by the composition root's ONE data-provider build, not here — D-14.)
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
    # ACCT-04/WR-03: read ``account_id`` UNCOERCED. ``VenueBundles.get`` takes it as a
    # REQUIRED argument (11.1-05), and after ACCT-03 a live spec always names an account —
    # so an absent id is a wiring bug and RAISES rather than being coerced onto
    # ``"default"``. The deleted ``... or DEFAULT_ACCOUNT_ID`` fallback keyed an unnamed
    # account here while the registration side keyed it differently: a write-only registry
    # entry no reader reached (WR-03). Registration-side and resolution-side defaults are
    # not symmetric.
    account_id = getattr(spec, "account_id", None)
    if account_id is None:
        raise ValidationError(
            "account_id",
            str(account_id),
            f"Cannot assemble venue '{venue}': the spec names no venue account, and "
            "there is no legitimate default one (ACCT-04/WR-03) — registration-side and "
            "resolution-side defaults are not symmetric",
        )
    # D-01: fail loud on an unregistered venue (the registry get behind the memo
    # raises KeyError). Resolved BEFORE the bundle so a mis-specified venue never
    # reaches a build.
    exec_plugin = bundles.plugin_for(venue)
    # D-08: ASK the shared memo. NEVER ``exec_plugin.build_bundle(...)`` — that is the
    # bypass that builds a second exchange per account.
    # D-04: the concretion imports live inside build_bundle (never at module top).
    bundle = bundles.get(venue, account_id, spec)

    # D-04/ACCT-04: the lifecycle carries the exec plugin + the pair identity so its
    # post-connect hook can run the venue-UID guard. ``account_id`` is the SAME uncoerced
    # id handed to ``bundles.get`` above — the guard arms against it verbatim, with no
    # substitution, so the write side (the memo key) and the read side (the guard) can
    # never disagree about the same real account (WR-03).
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
