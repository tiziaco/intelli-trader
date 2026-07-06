"""``UniverseUpdateEvent`` — the dynamic-universe "dispose" notification (D-04).

Plan 06-01 Task 1. ``UniverseUpdateEvent`` is a frozen ``Event`` subclass
carrying ``tuple[str, ...]`` ``added``/``removed`` payloads, pinned to the new
``EventType.UNIVERSE_UPDATE`` discriminator. It is DISTINCT from
``ScreenerEvent`` (the "propose" seam). This plan ships NO consumers — the
``_routes`` entry is explicit-empty (live consumers wired live-only in plan 05)
— so an emitted event must be a safe no-op, never a ``NotImplementedError``.

Six behaviors are pinned here:

1. constructs; ``.type is EventType.UNIVERSE_UPDATE``
2. frozen — assigning ``.added`` raises
3. ``added``/``removed`` are ``tuple[str, ...]`` (immutable payload)
4. ``EventType`` parses ``"universe_update"`` / ``"UNIVERSE_UPDATE"`` case-insensitively
5. importable from the ``itrader.events_handler.events`` barrel
6. dispatch never raises ``NotImplementedError`` (explicit-empty route present)
"""

import queue
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import msgspec
import pytest

from itrader.core.enums import EventType  # noqa: E402 (must precede stub import)
from itrader.events_handler.events.market import UniverseUpdateEvent

pytestmark = pytest.mark.unit


# --- 1/2/3: construction, frozen, tuple payload ---------------------------


def test_universe_update_event_constructs_with_type_discriminator():
    ev = UniverseUpdateEvent(
        time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        added=("ETH/USDC",),
        removed=(),
    )
    assert ev.type is EventType.UNIVERSE_UPDATE
    assert ev.added == ("ETH/USDC",)
    assert ev.removed == ()


def test_universe_update_event_is_frozen():
    ev = UniverseUpdateEvent(
        time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        added=("ETH/USDC",),
        removed=(),
    )
    with pytest.raises((AttributeError, TypeError, msgspec.ValidationError)):
        ev.added = ("BTC/USDC",)  # frozen msgspec.Struct


def test_universe_update_event_payload_is_tuple():
    ev = UniverseUpdateEvent(
        time=datetime(2020, 1, 1, tzinfo=timezone.utc),
        added=("A", "B"),
        removed=("C",),
    )
    assert isinstance(ev.added, tuple)
    assert isinstance(ev.removed, tuple)


# --- 4: case-insensitive enum parse ---------------------------------------


def test_event_type_parses_case_insensitively():
    assert EventType("universe_update") is EventType.UNIVERSE_UPDATE
    assert EventType("UNIVERSE_UPDATE") is EventType.UNIVERSE_UPDATE


# --- 5: barrel import ------------------------------------------------------


def test_universe_update_event_importable_from_barrel():
    from itrader.events_handler.events import UniverseUpdateEvent as Barrel

    assert Barrel is UniverseUpdateEvent


# --- 6: dispatch is a safe no-op (explicit-empty route) --------------------


_STUB_MODULES = {
    name: MagicMock()
    for name in [
        "itrader.strategy_handler.strategies_handler",
        "itrader.screeners_handler.screeners_handler",
        "itrader.order_handler.order_handler",
        "itrader.portfolio_handler.portfolio_handler",
        "itrader.execution_handler.execution_handler",
    ]
}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler


def _handler():
    q = queue.Queue()
    handler = EventHandler(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        MagicMock(), q,
    )
    return SimpleNamespace(q=q, handler=handler)


def test_universe_update_route_is_explicit_empty():
    wiring = _handler()
    assert EventType.UNIVERSE_UPDATE in wiring.handler.routes
    assert wiring.handler.routes[EventType.UNIVERSE_UPDATE] == []


def test_dispatching_universe_update_does_not_raise():
    wiring = _handler()
    ev = MagicMock()
    ev.type = EventType.UNIVERSE_UPDATE
    wiring.q.put(ev)
    # No route consumers, but the type MUST be registered — dispatch is a no-op,
    # never a NotImplementedError.
    wiring.handler.process_events()
    assert wiring.q.empty()
