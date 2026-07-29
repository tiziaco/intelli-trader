"""VenueBundles — the shared (venue, account_id) bundle memo.

One small memoized provider over ``(registry, connectors, ctx)`` that both
``ExecutionHandler`` and ``PortfolioHandler`` hold, each asking it for the view it
needs — the ``exchange``, or the ``account_factory``.

**WHY a memo and not build-per-caller.** ``ExecutionHandler`` and
``PortfolioHandler`` both need a view of the SAME bundle for one
``(venue, account_id)``. Two independent ``build_bundle`` calls would produce two
``OkxExchange`` instances per account, and ``OkxExchange.connect()`` is the SOLE
spawn site for ``_stream_fills`` / ``_stream_orders`` — so a second bundle would
double-spawn the fill/order streams for one authenticated account. The memo exists
to prevent that duplicate-session defect, not to optimize.

**WHY it sits one layer ABOVE ``ConnectorProvider`` and shares its key.** The
connector memo (``connectors/provider.py``) keys ``(venue, account_id)``. A bundle
memo on any other key (a bare ``account_id``, a bare ``venue``) lets the two drift:
two venues sharing one ``account_id`` would collapse onto one bundle while still
holding two connectors. The memo shape here is copied structurally from
``ConnectorProvider.get`` for exactly that reason.

**WHY the lookup is fail-loud.** ``get`` resolves the plugin through
``ExecutionVenueRegistry.get``, whose bare ``self._plugins[name]`` subscript raises
``KeyError`` on an unknown venue. It is never wrapped in a soft ``.get(...) or
default`` lookup: a wiring path that answers "here is some exchange" when asked
for one that was never registered routes real orders to the wrong venue, and does
it without raising.

**WHY it is not in the barrel.** ``venues/__init__.py`` is the GATE-01 inertness
acceptance evidence: it imports no concretion, so importing ``itrader.venues``
pulls nothing heavy. This module is imported DIRECTLY
(``from itrader.venues.bundles import VenueBundles``) and is deliberately absent
from that barrel — adding it invites a future module-level concretion import that
the inertness gate would then have to be weakened to accommodate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.venues.registry import DEFAULT_ACCOUNT_ID

if TYPE_CHECKING:
    from itrader.portfolio_handler.account.base import Account
    from itrader.venues.bundle import VenueBundle, VenuePlugin
    from itrader.venues.registry import ExecutionVenueRegistry


class VenueBundles:
    """Owns the ``(venue, account_id)`` bundle memo over the venue registry.

    ``get`` builds-once-then-memoizes on the ``(venue, account_id)`` key so the
    execution and portfolio arms share ONE bundle — and therefore one exchange and
    one account factory — per venue+account.
    """

    def __init__(
        self,
        registry: ExecutionVenueRegistry,
        connectors: Any,
        ctx: Any,
    ) -> None:
        # ``connectors`` / ``ctx`` are typed ``Any`` for the same reason
        # ``venues/bundle.py`` types them ``Any``: naming ``ConnectorProvider`` /
        # ``EngineContext`` concretely would drag them onto this module's import graph.
        self._registry = registry
        self._connectors = connectors
        self._ctx = ctx
        self._memo: dict[tuple[str, str], VenueBundle] = {}

    def get(self, venue: str, account_id: str, spec: Any) -> VenueBundle:
        """Return the shared bundle for ``(venue, account_id)``; build it once on first call.

        Fails loud with ``KeyError`` when ``venue`` has no registered plugin.

        ``account_id`` is REQUIRED, not defaulted: it is read UNCOERCED here, with no
        ``or DEFAULT_ACCOUNT_ID`` fallback applied. Normalizing an absent id in more
        than one place is how the exchange registry and the connector memo end up
        disagreeing about the same unnamed account.
        """
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = self._registry.get(venue).build_bundle(
                self._ctx, spec, self._connectors
            )
        return self._memo[key]

    def account_for(
        self,
        venue: str,
        account_id: str,
        *,
        spec: Any = None,
        **portfolio_args: Any,
    ) -> Account:
        """Construct THIS ``(venue, account_id)``'s account leaf.

        The mode-agnostic construction primitive: it resolves the shared bundle through
        ``get`` above and calls that bundle's ``account_factory``. Both backtest arms
        already build a ``VenueBundles``, so this needs no mode branch — the layer split
        puts CONSTRUCTION here and AUTHORITY (does this account exist, and is it
        enabled?) in ``VenueAccountManager``. A manager-only design would need a
        ``VenueAccountManager(store=None)`` on the backtest arm, the Optional-collaborator
        shape this codebase avoids.

        ``account_id`` is REQUIRED and UNCOERCED, exactly like ``get``: no fallback is
        applied here either.

        It is also FORWARDED to the factory as ``account_id=``, because the pair IS the
        account's identity — the memo key and the account the leaf is minted for are the
        same thing, and letting them be supplied separately is how they drift. Callers
        therefore MUST NOT repeat ``account_id`` inside ``portfolio_args`` (Python raises
        ``TypeError`` for the duplicate, which is the intended loud failure).

        ``spec`` is the build-time spec ``get`` forwards to the plugin on a memo MISS. The
        expected case is a memo HIT — the bundle was built by
        ``VenueAccountManager.bring_online`` — where it is unread; it stays available so a
        first-touch construction on a spec-reading plugin is not forced through ``None``.

        Fails loud exactly like ``get``: ``KeyError`` on an unregistered venue, never a
        soft ``.get(...) or default`` that answers with some other venue's account.
        """
        bundle = self.get(venue, account_id, spec)
        account: Account = bundle.account_factory(
            account_id=account_id, **portfolio_args)
        return account

    def plugin_for(self, venue: str) -> VenuePlugin:
        """Return the plugin registered for ``venue`` — METADATA only, never to build.

        The venue-assembly arm needs the venue's PLUGIN OBJECT
        (which calls ``plugin.fetch_venue_uid(connector)``), while its BUNDLE must come
        from ``get`` above so exactly one exchange exists per ``(venue, account_id)``.
        Exposing this narrow read — rather than threading a second
        ``ExecutionVenueRegistry`` argument alongside the memo — makes a divergent
        registry unrepresentable: the guard's plugin and the bundle's builder are
        provably the same object.

        Callers MUST NOT call ``build_bundle`` on the returned plugin. That is the
        memo-bypass this class exists to prevent (it is how a boot ends up with two
        ``OkxExchange`` objects for one authenticated account, double-spawning
        ``_stream_fills`` / ``_stream_orders``). Ask ``get`` for a bundle.

        Fails loud with ``KeyError`` on an unregistered venue, exactly like ``get``.
        """
        return self._registry.get(venue)
