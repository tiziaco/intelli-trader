"""ConnectorPool — one authenticated session per venue account, plus public sessions.

A connector IS a session: credentials, one ``ccxt.pro`` client, one asyncio loop on a
daemon thread. Two of them for the same account means two clients, two loops and two
websocket sessions where the system believes there is one — which is why sessions are
memoized rather than built per caller.

**What the pool owns and what it does not.** It owns the ``(venue, account_id)`` memo, the
session-identity guard, the public-session memo, and teardown. It owns no build knowledge:
each venue's construction recipe is handed in as ``recipes``, a plain mapping of venue name
to callable. That keeps the pool free of every concretion — importing this module pulls no
ccxt and no settings model — so a composition root that needs an empty pool can hold a real
one instead of ``None``.

**Recipes as data, not plugins.** A recipe is a function, and selecting one is a dict
lookup. The previous shape wrapped each function in a single-method class implementing a
Protocol; the class carried no state and the Protocol had one member, so the wrapper's only
effect was to make "which venue" a type rather than a key.

**The session-identity guard.** ``session`` reads its spec-shaped argument ONLY on a memo
MISS. An account's own stored config can carry ``secret_ref`` / ``sandbox`` / ``region`` —
the values deciding which CREDENTIALS a session authenticates with and whether it reaches
the demo or the production host. A silent memo hit would hand the second caller a session
routed somewhere other than the one it asked for, while every lookup above it still looked
correct, so a same-pair disagreement is refused. Refusing is the only safe answer: an
already-authenticated session cannot be rebound, and answering with the stale one IS the
defect. Two different ``account_id``s are two different keys and may legally differ in
every field — the guard constrains nothing about per-account routing.

**Public sessions.** ``public_session(venue)`` returns an UNAUTHENTICATED session, memoized
per venue. It takes no account and no spec, so it has no identity to conflict: there are no
credentials to disagree about and the host is the venue's own. One public session per venue
is enough because nothing about it is caller-specific.

  Note for the data plane: a venue whose recipe cannot yet build a credential-free session
  will raise from its own recipe rather than silently returning an authenticated one. That
  refusal is deliberate — quietly handing back a credentialed session would recreate the
  borrow the public session exists to eliminate.

Indentation: 4-space. Strict-typed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector
    from itrader.venues.catalog import VenueDescriptor

#: A connector recipe: builds ONE session for a venue. ``descriptor`` supplies the venue's
#: static facts (notably ``credential_model``, from which a recipe derives its required
#: credential set); ``spec`` is the account-shaped record naming ``secret_ref`` and the
#: non-secret connection knobs, or ``None`` for a public session.
ConnectorRecipe = Callable[..., "LiveConnector"]

#: The spec fields that decide WHICH REAL SESSION a built connector is: ``secret_ref``
#: selects the credentials; ``sandbox`` / ``region`` select the host the authenticated
#: session reaches. Deliberately NOT every spec field — ``data_provider`` and
#: ``market_type`` do not change the session, so including them would refuse perfectly
#: legitimate re-asks.
_SESSION_IDENTITY_FIELDS = ("secret_ref", "sandbox", "region")


def _session_identity(spec: Any) -> tuple[Any, ...]:
    """The connection-identity of ``spec`` — what a built session IS.

    Read with ``getattr(..., None)`` so a spec-shaped object carrying no routing fields
    yields a stable all-``None`` identity rather than raising: an object naming no routing
    cannot CONFLICT with anything.
    """
    return tuple(getattr(spec, name, None) for name in _SESSION_IDENTITY_FIELDS)


class ConnectorPool:
    """The venue-session memo: one authenticated session per account, one public per venue.

    Parameters
    ----------
    catalog : Mapping[str, VenueDescriptor]
        The venue catalogue. Supplies each venue's static facts to its recipe.
    resolver : Any
        The ``CredentialResolver`` turning an account's ``secret_ref`` pointer into
        credential material. Handed to recipes; the pool never reads credentials itself.
    recipes : Mapping[str, ConnectorRecipe]
        Venue name to construction recipe. An empty mapping is a legitimate pool that can
        build nothing — the shape a backtest root holds.
    """

    def __init__(
        self,
        *,
        catalog: Mapping[str, VenueDescriptor],
        resolver: Any,
        recipes: Mapping[str, ConnectorRecipe],
    ) -> None:
        self._catalog = catalog
        self._resolver = resolver
        self._recipes = recipes
        self._sessions: dict[tuple[str, str], LiveConnector] = {}
        # The session identity each memoized session was BUILT from, under the same key.
        # Kept beside the memo rather than sniffed back off the connector: a connector
        # holds ``SecretStr`` credentials, and re-deriving an identity from it would mean
        # reading them.
        self._identities: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._public: dict[str, LiveConnector] = {}
        self.logger = get_itrader_logger().bind(component="ConnectorPool")

    def session(self, venue: str, account_id: str, spec: Any) -> LiveConnector:
        """The authenticated session for ``(venue, account_id)``; built once on first ask.

        Raises ``KeyError`` when ``venue`` has no recipe, and ``ValidationError`` when a
        later call for the SAME pair presents a spec whose session identity CONFLICTS with
        the memoized session's.
        """
        key = (venue, account_id)
        identity = _session_identity(spec)
        if key not in self._sessions:
            self._sessions[key] = self._build(venue, spec)
            self._identities[key] = identity
            return self._sessions[key]

        recorded = self._identities[key]
        if identity != recorded:
            # Field NAMES only, never values: ``secret_ref`` is a pointer and the other two
            # are non-secret, but building a message out of spec values is how a credential
            # eventually reaches a log line.
            differing = [
                name
                for name, was, now in zip(_SESSION_IDENTITY_FIELDS, recorded, identity)
                if was != now
            ]
            raise ValidationError(
                "spec",
                f"({venue!r}, {account_id!r})",
                f"Refusing to hand back the memoized session for venue account "
                f"({venue!r}, {account_id!r}): it was built for a DIFFERENT session "
                f"identity and this call disagrees on {differing}. The memo reads the spec "
                f"only when it BUILDS, so answering with the existing session would give "
                f"this caller credentials and/or a host it did not ask for — a live order "
                f"routed to the wrong real account. One (venue, account_id) pair has "
                f"exactly one session; give the second wiring its own account_id.",
            )
        return self._sessions[key]

    def public_session(self, venue: str) -> LiveConnector:
        """The venue's UNAUTHENTICATED session, built once and shared.

        No account, no spec, no credentials — so no identity to conflict. One per venue is
        sufficient because nothing about a public session is caller-specific.
        """
        if venue not in self._public:
            self._public[venue] = self._build(venue, None)
        return self._public[venue]

    def close_session(self, venue: str, account_id: str) -> None:
        """Disconnect and forget ONE account's session; a pair with none is a no-op.

        The per-account teardown a retiring account performs. It must reach exactly its
        OWN session: tearing the whole pool down to retire one account would disconnect
        every OTHER account's streams too, so the accounts that were not retired stop
        receiving fills while still looking online.

        The memo entry is dropped whether or not the disconnect raised — a session that
        failed to close cleanly is still gone, and keeping it memoized would hand the
        next bring-up a dead connector.
        """
        key = (venue, account_id)
        connector = self._sessions.pop(key, None)
        self._identities.pop(key, None)
        if connector is None:
            return
        try:
            connector.disconnect()
        except Exception:
            self.logger.error(
                "connector disconnect failed", exc_info=True,
                venue=venue, account_id=account_id)

    def close_all(self) -> None:
        """Disconnect every session this pool built, exactly once, then drop the memos."""
        try:
            for connector in (*self._sessions.values(), *self._public.values()):
                try:
                    connector.disconnect()
                except Exception:
                    self.logger.error("connector disconnect failed", exc_info=True)
        finally:
            self._sessions.clear()
            # The identity map is a shadow of the session memo and must never outlive it: a
            # stale entry would refuse the NEXT run's legitimate first build.
            self._identities.clear()
            self._public.clear()

    def _build(self, venue: str, spec: Any) -> LiveConnector:
        """Run ``venue``'s recipe. ``spec is None`` asks for a public session."""
        try:
            recipe = self._recipes[venue]
        except KeyError:
            raise KeyError(
                f"no connector recipe for venue {venue!r} — the pool builds "
                f"{sorted(self._recipes)}") from None
        return recipe(
            descriptor=self._catalog.get(venue),
            spec=spec,
            resolver=self._resolver,
        )
