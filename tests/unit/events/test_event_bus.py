"""BUS-01/BUS-02/BUS-03 proof suite for the event-bus substrate (Plan 02-01).

Pure stdlib, no data load. Proves:
* BUS-01 — both buses satisfy the ``EventBus`` runtime_checkable Protocol,
  round-trip a put/get, and raise ``queue.Empty`` on empty.
* BUS-02 — ``PriorityEventBus`` dequeues CONTROL before BUSINESS while
  preserving strict within-tier FIFO; ``get*()`` returns a bare ``Event``
  (never the tuple); events are never compared (bare ``event < event`` raises
  ``TypeError`` — proving the shared ``seq`` guarantee is load-bearing).
* BUS-03 — the three new CONTROL ``EventType`` members are enumerated in
  ``_CONTROL_EVENT_TYPES`` and tier to CONTROL; BUSINESS is the default.
"""

import queue

import msgspec
import pytest

from itrader.core.enums.event import EventType
from itrader.events_handler.bus import (
    EventBus,
    EventTier,
    FifoEventBus,
    PriorityEventBus,
    _CONTROL_EVENT_TYPES,
    _tier,
)


class _StubEvent(msgspec.Struct, frozen=True, kw_only=True, gc=False):
    """Minimal non-orderable event carrying a ``type`` — mirrors the real
    ``Event`` (a frozen ``msgspec.Struct``) which raises ``TypeError`` on ``<``.
    ``tag`` distinguishes instances for FIFO-order assertions.
    """

    type: EventType
    tag: int = 0


def _bar(tag: int = 0) -> _StubEvent:
    return _StubEvent(type=EventType.BAR, tag=tag)


def _control(tag: int = 0) -> _StubEvent:
    return _StubEvent(type=EventType.CONFIG_UPDATE, tag=tag)


# --------------------------------------------------------------------------- #
# BUS-01 — Protocol conformance + drain contract
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bus_cls", [FifoEventBus, PriorityEventBus])
def test_bus_satisfies_protocol(bus_cls):
    bus = bus_cls()
    assert isinstance(bus, EventBus)


@pytest.mark.parametrize("bus_cls", [FifoEventBus, PriorityEventBus])
def test_bus_put_get_roundtrips_same_object(bus_cls):
    bus = bus_cls()
    event = _bar(tag=7)
    bus.put(event)
    got = bus.get_nowait()
    assert got is event  # SAME object round-trips, not a tuple/copy
    assert got.type is EventType.BAR


@pytest.mark.parametrize("bus_cls", [FifoEventBus, PriorityEventBus])
def test_get_nowait_raises_empty_on_empty(bus_cls):
    bus = bus_cls()
    with pytest.raises(queue.Empty):
        bus.get_nowait()


@pytest.mark.parametrize("bus_cls", [FifoEventBus, PriorityEventBus])
def test_bus_reports_expected_types(bus_cls):
    bus = bus_cls()
    assert bus.empty() is True
    assert bus.qsize() == 0
    bus.put(_bar())
    assert bus.empty() is False
    assert bus.qsize() == 1
    depth = bus.depth_by_tier()
    assert isinstance(depth, dict)
    assert all(isinstance(k, EventTier) for k in depth)
    assert all(isinstance(v, int) for v in depth.values())


def test_fifo_is_tierless_single_bucket():
    bus = FifoEventBus()
    bus.put(_bar())
    bus.put(_control())
    # FIFO is tierless — one BUSINESS bucket, monitoring-only.
    assert bus.depth_by_tier() == {EventTier.BUSINESS: 2}


# --------------------------------------------------------------------------- #
# BUS-02 — priority ordering, bare-event unwrap, non-orderability
# --------------------------------------------------------------------------- #

def test_priority_control_preempts_business_then_fifo():
    bus = PriorityEventBus()
    b1 = _bar(tag=1)
    b2 = _bar(tag=2)
    c = _control(tag=99)
    bus.put(b1)   # BUSINESS
    bus.put(b2)   # BUSINESS
    bus.put(c)    # CONTROL — enqueued last, must dequeue FIRST
    assert bus.get_nowait() is c    # CONTROL preempts
    assert bus.get_nowait() is b1   # then strict within-tier FIFO
    assert bus.get_nowait() is b2


def test_priority_get_returns_bare_event_not_tuple():
    bus = PriorityEventBus()
    bus.put(_bar(tag=5))
    got = bus.get_nowait()
    assert isinstance(got, _StubEvent)
    assert not isinstance(got, tuple)
    assert got.type is EventType.BAR  # bare Event has .type


def test_priority_depth_by_tier_tracks_both_tiers():
    bus = PriorityEventBus()
    bus.put(_bar())
    bus.put(_bar())
    bus.put(_control())
    assert bus.depth_by_tier() == {EventTier.CONTROL: 1, EventTier.BUSINESS: 2}
    bus.get_nowait()  # pops the CONTROL event
    assert bus.depth_by_tier() == {EventTier.CONTROL: 0, EventTier.BUSINESS: 2}


def test_priority_never_compares_events():
    # The load-bearing invariant: events are non-orderable, so the unique seq
    # in the (tier, seq, event) tuple is what keeps the heap from ever
    # comparing two events. A bare comparison MUST raise TypeError.
    a = _bar(tag=1)
    b = _bar(tag=2)
    with pytest.raises(TypeError):
        a < b  # noqa: B015 — asserting non-orderability, not using the result


def test_priority_stable_fifo_under_many_same_tier_puts():
    bus = PriorityEventBus()
    events = [_bar(tag=i) for i in range(50)]
    for e in events:
        bus.put(e)  # many same-tier puts — must not raise TypeError
    out = [bus.get_nowait() for _ in range(50)]
    assert out == events  # strict insertion (FIFO) order preserved


# --------------------------------------------------------------------------- #
# BUS-03 — CONTROL vocabulary + tiering
# --------------------------------------------------------------------------- #

def test_control_types_include_three_new_members():
    assert EventType.STREAM_STATE in _CONTROL_EVENT_TYPES
    assert EventType.CONNECTOR_FATAL in _CONTROL_EVENT_TYPES
    assert EventType.CONFIG_UPDATE in _CONTROL_EVENT_TYPES


def test_control_types_include_strategy_command():
    assert EventType.STRATEGY_COMMAND in _CONTROL_EVENT_TYPES


def test_control_types_tier_to_control():
    assert _tier(EventType.STREAM_STATE) == EventTier.CONTROL
    assert _tier(EventType.CONNECTOR_FATAL) == EventTier.CONTROL
    assert _tier(EventType.CONFIG_UPDATE) == EventTier.CONTROL
    assert _tier(EventType.STRATEGY_COMMAND) == EventTier.CONTROL


def test_control_types_business_is_default():
    assert _tier(EventType.BAR) == EventTier.BUSINESS
    assert EventType.BAR not in _CONTROL_EVENT_TYPES
