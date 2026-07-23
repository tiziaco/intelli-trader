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


#: The venue whose plugin backs the simulated fill engine and the COMPUTE account
#: leaves — ``'paper'`` (D-05/D-19).
#:
#: Backtest and live-paper are the SAME behaviour (a simulated fill engine over
#: computed accounts), so they carry ONE name rather than a synonym; ``'simulated'``
#: and ``'csv'`` were retired as routing keys in plan 11.1-06 with no transitional
#: alias. ``SimulatedExchange`` remains the CLASS of that engine — never a venue name.
#:
#: It lives HERE, in the import-inert venue substrate, because it is a venue-domain
#: fact that BOTH handlers need: ``ExecutionHandler`` resolves its exchange under it
#: and ``PortfolioHandler`` mints every portfolio's construction-time compute leaf
#: under it (D-02/D-03, 11.1-09). A second literal in either handler is how the two
#: arms end up asking the bundle memo for different venues.
COMPUTE_VENUE = 'paper'

#: The logical venue account of a SINGLE-account venue (D-27/MPORT-07).
#:
#: The exchange registry, the connector memo and the bundle memo are all keyed on
#: the ``(venue, account_id)`` PAIR, because an order's real target is a specific
#: AUTHENTICATED SESSION, not a venue. Venues that have only ever had one account —
#: the ``COMPUTE_VENUE`` above, and any venue before per-account wiring — register
#: under this constant.
#:
#: It is deliberately a separate KEY HALF and never spliced into the venue name:
#: ``Order.exchange`` is a persisted column, so a composed ``"venue:account"`` string
#: would leak account topology into durable data and into every query over it. The
#: key is a runtime tuple; the persisted column keeps the bare venue name.
#:
#: 11.1-09: HOMED HERE (it was defined in ``execution_handler.py``, which still
#: re-exports it so every existing import path is unchanged) because
#: ``PortfolioHandler`` now needs the same key half to ask the bundle memo for its
#: compute account — and a portfolio module importing the execution handler to get a
#: string would put ``SimulatedExchange`` on the portfolio domain's import graph.
DEFAULT_ACCOUNT_ID = 'default'


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
