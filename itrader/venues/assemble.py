"""assemble_venue — resolve plugins, build bundle + provider + lifecycle (05-06, VENUE-06, D-06).

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

Import-inert: ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free (the P5 inertness gate) —
the concretion imports live inside the plugins' ``build*`` bodies (D-04).

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.venues.lifecycle import VenueLifecycle

if TYPE_CHECKING:
    from itrader.connectors.provider import ConnectorProvider
    from itrader.venues.bundle import VenueBundle
    from itrader.venues.registry import DataProviderRegistry, ExecutionVenueRegistry


def assemble_venue(
    ctx: Any,
    spec: Any,
    connectors: ConnectorProvider,
    exec_registry: ExecutionVenueRegistry,
    data_registry: DataProviderRegistry,
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

    lifecycle = VenueLifecycle(bundle, provider, connectors=connectors)
    return bundle, lifecycle
