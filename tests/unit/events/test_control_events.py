"""CONTROL-tier event tests (SAFE-03).

Pins the two connector→engine handoff events authored in
``events_handler/events/control.py``:

  1. Both are ``Event`` msgspec.Struct subclasses with ``type`` pinned to the
     pre-enumerated CONTROL EventType members (STREAM_STATE / CONNECTOR_FATAL).
  2. Construction honors frozen/kw_only and carries the declared fields.
  3. Frozen: field mutation raises (immutable fact).
  4. Both are importable from the ``itrader.events_handler.events`` barrel.
  5. V7 secret-scrub: ``reason`` is a plain str field (fixed literal only, never a
     stringified exception) — the source module carries no exception-stringification.
"""

from datetime import datetime

import pytest

from itrader.core.enums import EventType
from itrader.events_handler.events import ConnectorFatalEvent, StreamStateEvent

pytestmark = pytest.mark.unit


def test_type_pins():
    """type is pinned to the pre-enumerated CONTROL EventType members."""
    assert StreamStateEvent.type is EventType.STREAM_STATE
    assert ConnectorFatalEvent.type is EventType.CONNECTOR_FATAL


def test_stream_state_event_construction():
    """StreamStateEvent carries stream_name + up and defaults created_at to time."""
    t = datetime(2026, 7, 14, 12, 0, 0)
    ev = StreamStateEvent(time=t, stream_name="candles", up=False)
    assert ev.stream_name == "candles"
    assert ev.up is False
    assert ev.type is EventType.STREAM_STATE
    assert ev.created_at == t  # base __post_init__ default


def test_connector_fatal_event_construction():
    """ConnectorFatalEvent carries a fixed reason literal."""
    t = datetime(2026, 7, 14, 12, 0, 0)
    ev = ConnectorFatalEvent(time=t, reason="connector-fatal")
    assert ev.reason == "connector-fatal"
    assert ev.type is EventType.CONNECTOR_FATAL


def test_events_are_frozen():
    """Mutation of a constructed CONTROL event raises (immutable fact)."""
    t = datetime(2026, 7, 14, 12, 0, 0)
    ev = StreamStateEvent(time=t, stream_name="candles", up=True)
    with pytest.raises(AttributeError):
        ev.up = False  # type: ignore[misc]
