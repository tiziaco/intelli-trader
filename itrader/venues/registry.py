"""The two independent venue registries — ExecutionVenueRegistry + DataProviderRegistry (05-04, VENUE-01, D-01).

Both are plain ``dict[name -> plugin]`` wrappers populated by EXPLICIT
``register(name, plugin)`` calls at the composition root — NO decorator /
entry-point self-registration (D-01). Rationale: explicit registration keeps
"register ≠ import a concretion" greppable and structurally obvious, and it
never forces the registry module to import a plugin module (one careless
top-level ccxt.pro import inside a plugin would redden the inertness gate).
``get`` is a bare
``self._plugins[name]`` so an unknown venue FAILS LOUD with ``KeyError``.

The two registries are SEPARATE types over separate plugin Protocols so
execution-venue and data-provider selection are independent (VENUE-01: OKX
execution + a different data feed).

Indentation: 4-SPACE (new top-level ``venues/`` package). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import KeysView

    from itrader.venues.bundle import DataProviderPlugin, VenuePlugin


class ExecutionVenueRegistry:
    """Explicit-map registry of execution-venue plugins (D-01, VENUE-01).

    A plain ``dict[str, VenuePlugin]`` populated by ``register`` calls; ``get``
    fails loud (``KeyError``) on an unknown venue.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, VenuePlugin] = {}

    def register(self, name: str, plugin: VenuePlugin) -> None:
        """Register ``plugin`` under ``name`` (explicit, no import side effect — D-01)."""
        self._plugins[name] = plugin

    def get(self, name: str) -> VenuePlugin:
        """Return the plugin registered under ``name``; ``KeyError`` if unknown (fail loud)."""
        return self._plugins[name]

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def names(self) -> KeysView[str]:
        """A live view of the registered venue names."""
        return self._plugins.keys()


class DataProviderRegistry:
    """Explicit-map registry of data-provider plugins (D-01, VENUE-01).

    Identical contract to ``ExecutionVenueRegistry`` over ``DataProviderPlugin``,
    kept a SEPARATE instance/type so data-provider selection is independent of
    execution-venue selection (VENUE-01).
    """

    def __init__(self) -> None:
        self._plugins: dict[str, DataProviderPlugin] = {}

    def register(self, name: str, plugin: DataProviderPlugin) -> None:
        """Register ``plugin`` under ``name`` (explicit, no import side effect — D-01)."""
        self._plugins[name] = plugin

    def get(self, name: str) -> DataProviderPlugin:
        """Return the plugin registered under ``name``; ``KeyError`` if unknown (fail loud)."""
        return self._plugins[name]

    def __contains__(self, name: object) -> bool:
        return name in self._plugins

    def names(self) -> KeysView[str]:
        """A live view of the registered data-provider names."""
        return self._plugins.keys()
