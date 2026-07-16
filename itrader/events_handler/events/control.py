"""CONTROL-tier events for the live connector → engine handoff (SAFE-03).

Two immutable ``msgspec.Struct`` facts the live connector's asyncio loop puts on
the bus so the engine thread can react to stream health and connector-fatal
conditions WITHOUT the callback touching engine state directly (BUS-03):

  - ``StreamStateEvent`` — a venue stream came up (reconnected) or went down
    (disconnected). Routed to safety.pause on down / recovery.on_reconnect on up.
  - ``ConnectorFatalEvent`` — the connector hit an unrecoverable condition; routed
    to safety.halt.

These subclass ``Event`` as frozen ``msgspec.Struct`` (NOT ``@dataclass`` —
CLAUDE.md's "frozen dataclass" language is stale; the events package migrated to
msgspec, verified against ``events/error.py``). ``type`` is pinned via
``ClassVar[EventType]`` to the pre-enumerated CONTROL members that already exist in
``core/enums/event.py`` (STREAM_STATE / CONNECTOR_FATAL).

SECURITY — V7 secret-scrub (ASVS V7, T-05-01 / T-07-01): ``ConnectorFatalEvent.reason``
carries ONLY a fixed reason literal (e.g. ``'connector-fatal'``). It must NEVER be
stringified from a caught exception or any connector/venue payload — an exception
string or network payload can leak credentials, endpoints, or account internals across
the loop→engine trust boundary. The construction sites in Plan 06 bind fixed literals
only (verified by a grep-0 guard on exception-stringification in this module).

These classes are CONTROL-routed and are NEVER constructed on the backtest path, so
barrel-exporting them is import-inertness-safe (msgspec-only, no live/ccxt/async/sql
import) — the OKX import-inertness gate stays green.
"""

from typing import Any, ClassVar

from itrader.core.enums import EventType

from .base import Event


class StreamStateEvent(Event, frozen=True, kw_only=True, gc=False):
    """A venue stream transitioned up (reconnected) or down (disconnected) (SAFE-03).

    Put on the bus by the connector's asyncio loop; consumed on the engine thread
    via the STREAM_STATE CONTROL route (down → safety.pause_submission, up →
    recovery.on_reconnect). Wired in Plan 06.

    Parameters
    ----------
    stream_name: `str`
        The venue stream identifier (e.g. ``'candles'``).
    up: `bool`
        ``True`` when the stream reconnected, ``False`` when it disconnected.
    """

    type: ClassVar[EventType] = EventType.STREAM_STATE
    stream_name: str
    up: bool


class ConnectorFatalEvent(Event, frozen=True, kw_only=True, gc=False):
    """The connector hit an unrecoverable condition and requests a halt (SAFE-03).

    Put on the bus by the connector's asyncio loop; consumed on the engine thread
    via the CONNECTOR_FATAL CONTROL route (→ safety.halt). Wired in Plan 06.

    Parameters
    ----------
    reason: `str`
        A FIXED reason literal only (e.g. ``'connector-fatal'``). NEVER a stringified
        exception or a connector/venue payload — see the module V7 secret-scrub note.
    """

    type: ClassVar[EventType] = EventType.CONNECTOR_FATAL
    reason: str


class ConfigUpdateEvent(Event, frozen=True, kw_only=True, gc=False):
    """A scoped runtime config change on the CONTROL plane (RTCFG-02 / D-23).

    Put on the bus by the trusted app-layer caller (via ``LiveTradingSystem.add_event``,
    the D-23 external-ingress opening) or an engine-internal source; consumed on the
    engine thread via the CONFIG_UPDATE CONTROL route -> the injected ``ConfigRouter``,
    which runs validate -> persist -> apply -> push (D-15) with default-deny scope->owner
    dispatch (D-11/D-21). The route slot ``EventType.CONFIG_UPDATE: []`` was pre-declared
    (BUS-03); the ``LiveRouteRegistrar`` populates its consumer in P9.

    SECURITY — V7 secret-scrub (ASVS V7, T-9-secret): ``value`` must NEVER carry a venue
    credential/secret to a config store. Credentials stay connector-owned (never routed
    through a config update); the ``VenueStore`` recursive secret-denylist is the last-line
    guard that rejects a secret-like key before any write.

    Parameters
    ----------
    scope: `str`
        The owning scope — one of ``{system, order, venue:{name}, portfolio:{id}}`` (D-21).
        EXACT-string matched (no case-folding / normalization); an unrouted scope is
        default-deny rejected.
    key: `str`
        The mutable sub-model field name to set (EXACT-string; a non-field is rejected).
    value: `Any`
        The new value (coerced + range-validated by the target sub-model's
        ``validate_assignment``; money-typed values stay Decimal end-to-end).
    """

    type: ClassVar[EventType] = EventType.CONFIG_UPDATE
    scope: str
    key: str
    value: Any
