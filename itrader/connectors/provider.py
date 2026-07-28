"""ConnectorProvider — the shared (venue, account_id) connector memo + ConnectorPlugin seam.

A dedicated ``ConnectorProvider`` owns BOTH the per-venue build recipe (via a
``ConnectorPlugin.build(spec)`` per venue) AND the ``(venue, account_id)`` memo,
plus ``close_all()`` for teardown. WHY a memo (not "build once, inject"): the
``ExecutionVenueRegistry`` and ``DataProviderRegistry`` are two SEPARATE
builders. Without a shared memo, each would lazily construct its OWN connector
for the same venue+account → two ``ccxt.pro`` clients / event loops / WS
sessions for one ``(venue, account_id)``. Both the execution ``build_bundle``
and the data ``build_provider`` call ``get(venue, account_id, spec)`` and
receive the SAME connector instance. "Build once at the root and inject" was
rejected because it forces the root to ``import`` the connector concretion —
reintroducing an ``if venue=='okx'`` branch.

A concrete ``ConnectorPlugin.build()`` keeps the concretion import + credential
(``OkxSettings()``) construction INSIDE ``build`` — never at module top, never
at register time. This module holds only the memo + Protocol; it imports no
concretion (``LiveConnector`` is a ``TYPE_CHECKING``-only annotation under
``from __future__ import annotations``), so importing ``connectors.provider``
pulls nothing heavy. That is what lets the BACKTEST composition root carry a
real, empty ``ConnectorProvider({})`` — never ``None`` — without reddening
GATE-01 (``tests/integration/test_okx_inertness.py``).

``connectors/__init__.py`` re-exports only the ``LiveConnector`` Protocol, never
a connector concretion, so importing this module is genuinely inert rather than
inert-by-call-site-discipline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector

#: The spec fields that decide WHICH REAL SESSION a built connector is: ``secret_ref``
#: selects the credentials; ``sandbox`` / ``region`` select the host the authenticated
#: session reaches. Deliberately NOT every spec field — ``data_provider`` and
#: ``market_type`` do not change the session, so including them would refuse
#: perfectly legitimate re-asks.
_SESSION_IDENTITY_FIELDS = ("secret_ref", "sandbox", "region")


def _session_identity(spec: Any) -> tuple[Any, ...]:
    """The connection-identity of ``spec`` — what a built connector IS.

    Read with ``getattr(..., None)`` so a spec-shaped object that carries no routing
    fields (e.g. a test double naming only ``account_id``) yields a stable all-``None``
    identity rather than raising: an object naming no routing cannot CONFLICT with
    anything.
    """
    return tuple(getattr(spec, name, None) for name in _SESSION_IDENTITY_FIELDS)


@runtime_checkable
class ConnectorPlugin(Protocol):
    """Structural per-venue connector build recipe.

    ``@runtime_checkable`` so a fake plugin is swap-in for tests. Registering a
    plugin is inert — it stores an object; the concretion ``import`` and credential
    construction happen only when ``build`` runs, and the network ``connect()``
    stays deferred to ``start()``.
    """

    def build(self, spec: Any) -> LiveConnector:
        """Build ONE ``LiveConnector`` (concretion + credentials constructed inside)."""
        ...


class ConnectorProvider:
    """Owns the per-venue build recipe + the ``(venue, account_id)`` connector memo.

    ``get`` builds-once-then-memoizes on the ``(venue, account_id)`` key so two
    independent builders share ONE connector per key; ``close_all`` disconnects
    every memoized connector for teardown.
    """

    def __init__(self, plugins: dict[str, ConnectorPlugin]) -> None:
        self._plugins = plugins
        self._memo: dict[tuple[str, str], LiveConnector] = {}
        # The session identity each memoized connector was BUILT from, under the same
        # key. Kept beside the memo rather than sniffed back off the connector: the
        # connector holds ``SecretStr`` credentials, and re-deriving an identity from it
        # would mean reading them.
        self._identities: dict[tuple[str, str], tuple[Any, ...]] = {}
        self.logger = get_itrader_logger().bind(component="ConnectorProvider")

    def get(self, venue: str, account_id: str, spec: Any) -> LiveConnector:
        """Return the shared connector for ``(venue, account_id)``; build it once on first call.

        Raises ``KeyError`` when ``venue`` has no registered plugin, and
        ``ValidationError`` when a later call for the SAME pair presents a spec whose
        session identity CONFLICTS with the memoized connector's.

        The conflict guard exists because ``spec`` is read ONLY on the memo MISS: an
        account's own ``config_json`` can carry ``secret_ref`` / ``sandbox`` / ``region``
        — the values that decide which CREDENTIALS a session authenticates with and
        whether it reaches the DEMO or the PRODUCTION host. A silent memo hit would hand
        the second caller a session routed somewhere other than the one it asked for,
        while every lookup above it still looked correct.

        Refusing is the only safe answer — an already-authenticated session cannot be
        rebound, and answering with the stale one is the defect. The guard does NOT
        constrain per-account routing: two different ``account_id``s are two different
        memo keys and may legally differ in every field. Only a same-PAIR disagreement is
        a wiring defect.
        """
        key = (venue, account_id)
        identity = _session_identity(spec)
        if key not in self._memo:
            self._memo[key] = self._plugins[venue].build(spec)
            self._identities[key] = identity
            return self._memo[key]

        recorded = self._identities[key]
        if identity != recorded:
            # Field NAMES only, never values: ``secret_ref`` is a pointer and the other
            # two are non-secret, but building a message out of spec values is how a
            # credential eventually reaches a log line.
            differing = [
                name
                for name, was, now in zip(_SESSION_IDENTITY_FIELDS, recorded, identity)
                if was != now
            ]
            raise ValidationError(
                "spec",
                f"({venue!r}, {account_id!r})",
                f"Refusing to hand back the memoized connector for venue account "
                f"({venue!r}, {account_id!r}): it was built for a DIFFERENT session "
                f"identity and this call disagrees on {differing}. The connector memo "
                f"reads the spec only when it BUILDS, so answering with the existing "
                f"session would give this caller credentials and/or a host it did not "
                f"ask for — a live order routed to the wrong real account. One "
                f"(venue, account_id) pair has exactly one session; give the second "
                f"wiring its own account_id (D-38/D-12).",
            )
        return self._memo[key]

    def close_all(self) -> None:
        """Disconnect every memoized connector exactly once, then drop the memo."""
        try:
            for connector in self._memo.values():
                try:
                    connector.disconnect()
                except Exception:
                    self.logger.error("connector disconnect failed", exc_info=True)
        finally:
            self._memo.clear()
            # The identity map is a shadow of the memo and must never outlive it: a
            # stale entry would refuse the NEXT run's legitimate first build.
            self._identities.clear()
