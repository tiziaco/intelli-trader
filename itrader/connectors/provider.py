"""ConnectorProvider — the shared (venue, account_id) connector memo + ConnectorPlugin seam (05-04, VENUE-03, D-03/D-04).

A dedicated ``ConnectorProvider`` owns BOTH the per-venue build recipe (via a
``ConnectorPlugin.build(spec)`` per venue) AND the ``(venue, account_id)`` memo,
plus ``close_all()`` for teardown. WHY a memo (not "build once, inject"): the two
independent registries — ``ExecutionVenueRegistry`` and ``DataProviderRegistry``
— are two SEPARATE builders. Without a shared memo, each would lazily construct
its OWN connector for the same venue+account → two ``ccxt.pro`` clients / event
loops / WS sessions for one ``(venue, account_id)`` (T-05-09 resource
exhaustion). Both the execution ``build_bundle`` and the data ``build_provider``
call ``get(venue, account_id, spec)`` and receive the SAME connector instance
(D-03). "Build once at the root and inject" was rejected because it forces the
root to ``import`` the connector concretion — reintroducing the ``if venue=='okx'``
branch this phase deletes.

D-04 (triple-deferral laziness): a concrete ``ConnectorPlugin.build()`` keeps the
concretion import + credential (``OkxSettings()``) construction INSIDE ``build``
— never at module top, never at register time. This module holds only the memo +
Protocol; it imports no concretion (``LiveConnector`` is a ``TYPE_CHECKING``-only
annotation under ``from __future__ import annotations``), so importing
``connectors.provider`` pulls nothing heavy (the inertness gate).

This file lives beside ``connectors/base.py`` / ``connectors/stream_supervisor.py``
and is still imported DIRECTLY (``from itrader.connectors.provider import ...``).
Since Phase 11.1 (RESEARCH F-2, the D-04 prerequisite) ``connectors/__init__.py``
no longer re-exports a connector CONCRETION — the barrel exports only the
``LiveConnector`` Protocol — so importing this module is genuinely inert rather
than inert-by-call-site-discipline: the package ``__init__`` it necessarily runs
pulls neither ``ccxt`` nor ``itrader.connectors.okx``. That is what lets the
BACKTEST composition root carry a ``ConnectorProvider`` (D-04 passes a real, empty
``ConnectorProvider({})``, never ``None``) without reddening GATE-01
(``tests/integration/test_okx_inertness.py``).

Indentation: 4-SPACE (``connectors/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from itrader.core.exceptions import ValidationError
from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector

#: The spec fields that decide WHICH REAL SESSION a built connector is (11.2-06, D-38).
#: ``secret_ref`` selects the credentials; ``sandbox`` / ``region`` select the host the
#: authenticated session reaches. Deliberately NOT every spec field: ``data_provider``
#: and ``market_type`` do not change the session, so including them would refuse
#: perfectly legitimate re-asks.
_SESSION_IDENTITY_FIELDS = ("secret_ref", "sandbox", "region")


def _session_identity(spec: Any) -> tuple[Any, ...]:
    """The connection-identity of ``spec`` — what a built connector IS (11.2-06, D-38).

    Read with ``getattr(..., None)`` so a spec-shaped object that predates D-38 (or a
    test double that carries only ``account_id``) yields a stable all-``None`` identity
    rather than raising: an object naming no routing cannot CONFLICT with anything.
    """
    return tuple(getattr(spec, name, None) for name in _SESSION_IDENTITY_FIELDS)


@runtime_checkable
class ConnectorPlugin(Protocol):
    """Structural per-venue connector build recipe (VENUE-03 / D-04).

    ``@runtime_checkable`` (mirrors the ``LiveConnector`` / ``VenuePlugin`` seams)
    so a fake plugin is swap-in for tests. ``build`` is the D-04 triple-deferral
    seam: a concrete implementation keeps the connector concretion ``import`` AND
    the ``OkxSettings()`` credential construction INSIDE the body — never at
    module top, never at register time. Registering a plugin is therefore inert
    (stores an object); the ``ccxt.pro`` import + credential read happen only when
    ``build`` runs, and the network ``connect()`` stays deferred to ``start()``.
    """

    def build(self, spec: Any) -> LiveConnector:
        """Build ONE ``LiveConnector`` (concretion + credentials constructed inside)."""
        ...


class ConnectorProvider:
    """Owns the per-venue build recipe + the ``(venue, account_id)`` connector memo (D-03).

    ``get`` builds-once-then-memoizes on the ``(venue, account_id)`` key so two
    independent builders share ONE connector per key; ``close_all`` disconnects
    every memoized connector for teardown (``stop()``).
    """

    def __init__(self, plugins: dict[str, ConnectorPlugin]) -> None:
        self._plugins = plugins
        self._memo: dict[tuple[str, str], LiveConnector] = {}
        # 11.2-06 (D-38): the session identity each memoized connector was BUILT from,
        # under the same key. Kept beside the memo rather than sniffed back off the
        # connector: the connector holds ``SecretStr`` credentials, and re-deriving an
        # identity from it would mean reading them.
        self._identities: dict[tuple[str, str], tuple[Any, ...]] = {}
        self.logger = get_itrader_logger().bind(component="ConnectorProvider")

    def get(self, venue: str, account_id: str, spec: Any) -> LiveConnector:
        """Return the shared connector for ``(venue, account_id)``; build it once on first call.

        Fails loud with ``KeyError`` when ``venue`` has no registered plugin, and with
        ``ValidationError`` when a later call for the SAME pair presents a spec whose
        session identity CONFLICTS with the memoized connector's (11.2-06, D-38).

        The conflict guard exists because ``spec`` is read ONLY on the memo MISS. That
        was harmless while a spec carried nothing but venue selection, but D-38 lets an
        account's own ``config_json`` carry ``secret_ref`` / ``sandbox`` / ``region`` —
        the values that decide which CREDENTIALS a session authenticates with and
        whether it reaches the DEMO or the PRODUCTION host. A silent memo hit would then
        hand the second caller a session routed somewhere other than the one it asked
        for, while every lookup above it still looked correct: exactly the misroute
        class the D-04 UID guard exists to detect, arriving through the memo instead.

        Refusing is the only safe answer — an already-authenticated session cannot be
        rebound, and answering with the stale one is the defect. Note the guard does NOT
        constrain per-account routing, which is the whole point of D-38: two different
        ``account_id``s are two different memo keys and may legally differ in every
        field. Only a same-PAIR disagreement is a wiring defect.
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
