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
and is imported DIRECTLY (``from itrader.connectors.provider import ...``);
``connectors/__init__.py`` is deliberately NOT edited so the barrel/inertness
surface stays unchanged.

Indentation: 4-SPACE (``connectors/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from itrader.connectors.base import LiveConnector


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

    def get(self, venue: str, account_id: str, spec: Any) -> LiveConnector:
        """Return the shared connector for ``(venue, account_id)``; build it once on first call.

        Fails loud with ``KeyError`` when ``venue`` has no registered plugin.
        """
        key = (venue, account_id)
        if key not in self._memo:
            self._memo[key] = self._plugins[venue].build(spec)
        return self._memo[key]

    def close_all(self) -> None:
        """Disconnect every memoized connector exactly once, then drop the memo."""
        for connector in self._memo.values():
            connector.disconnect()
        self._memo.clear()
