"""ErrorPolicy — FailFastPolicy re-raise, live publish-and-continue, WR-06 source
guard, and the D-07/D-11 CF-1 tripwire (should_trip + classify_failure + _POLICY +
record_failure + bind).

The hard criterion (ERR-03 / CF-1): a FILL-route handler raising on every event
trips the SETTLEMENT halt on the FIRST failure via the injected fake halt, with NO
exception escaping ``on_handler_error`` (WR-06 source guard + live swallow hold).
"""

from collections import deque
from datetime import datetime
from types import SimpleNamespace

import pytest

from itrader.core.enums import ErrorSeverity, EventType, FailureClass, HaltReason
from itrader.config.safety import FailureRateSettings
from itrader.events_handler.error_policy import (
    ErrorPolicy,
    FailFastPolicy,
    classify_failure,
    should_trip,
)

_TIME = datetime(2024, 1, 1, 12, 0, 0)


class _FakeBus:
    """Minimal bus capturing published events (ErrorPolicy only calls put())."""

    def __init__(self) -> None:
        self.events: list = []

    def put(self, event) -> None:
        self.events.append(event)


class _FakeHalt:
    """Records the wire-string reason each halt call receives."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, reason) -> None:
        self.calls.append(reason)


class _SentinelError(Exception):
    """Distinct type so a test proves the ORIGINAL exception propagates."""


def _failing_fill_handler(event):  # noqa: ARG001 — name is what the test asserts
    raise _SentinelError("boom")


# --- FailFastPolicy: bare raise re-raises the active except-block exception ----


def test_failfast_policy_reraises_active_exception():
    policy = FailFastPolicy()
    with pytest.raises(_SentinelError, match="oracle-safe"):
        try:
            raise _SentinelError("oracle-safe")
        except Exception:
            policy.on_handler_error(object(), object())


# --- should_trip windowed math (pure, injected now) ---------------------------


@pytest.mark.parametrize(
    "threshold,window,timestamps,expected_final",
    [
        (1, 60.0, [0.0], True),                        # SETTLEMENT halt-on-first
        (3, 60.0, [0.0, 1.0], False),                  # 2 hits < threshold
        (3, 60.0, [0.0, 1.0, 2.0], True),              # ORDER_IO 3/60 trips at 3rd
        (3, 60.0, [0.0, 100.0, 200.0], False),         # spaced > window: never accumulates
        (3, 300.0, [0.0, 10.0, 20.0], True),           # ADMISSION 3/300
        (5, 60.0, [0.0, 1.0, 2.0, 3.0], False),        # 4 hits < 5
        (5, 60.0, [0.0, 1.0, 2.0, 3.0, 4.0], True),    # LOOP_BACKSTOP 5/60
    ],
)
def test_should_trip_windowed(threshold, window, timestamps, expected_final):
    hits: deque = deque()
    result = False
    for now in timestamps:
        result = should_trip(hits, threshold, window, now)
    assert result is expected_final


def test_should_trip_prunes_entries_outside_window():
    hits: deque = deque()
    should_trip(hits, 3, 60.0, 0.0)
    should_trip(hits, 3, 60.0, 100.0)   # 0.0 is > window old → pruned
    assert list(hits) == [100.0]


# --- classify_failure (D-09 Option A) -----------------------------------------


def test_classify_fill_is_settlement():
    assert classify_failure(SimpleNamespace(type=EventType.FILL)) is FailureClass.SETTLEMENT


def test_classify_order_is_order_io():
    assert classify_failure(SimpleNamespace(type=EventType.ORDER)) is FailureClass.ORDER_IO


def test_classify_signal_is_admission():
    assert classify_failure(SimpleNamespace(type=EventType.SIGNAL)) is FailureClass.ADMISSION


def test_classify_unmapped_is_loop_backstop():
    assert classify_failure(SimpleNamespace(type=EventType.BAR)) is FailureClass.LOOP_BACKSTOP


def test_classify_okx_fill_translation_error_is_fill_translation():
    ev = SimpleNamespace(
        type=EventType.ERROR, source="okx_exchange", operation="fill-translation"
    )
    assert classify_failure(ev) is FailureClass.FILL_TRANSLATION


def test_classify_generic_error_event_is_none():
    ev = SimpleNamespace(
        type=EventType.ERROR, source="live_trading_system", operation="on_fill"
    )
    assert classify_failure(ev) is None


# --- record_failure: injected halt fired with the right HaltReason value -------


def test_record_failure_settlement_halts_on_first():
    halt = _FakeHalt()
    policy = ErrorPolicy(_FakeBus(), failure_settings=FailureRateSettings.default(), halt=halt)
    policy.record_failure(FailureClass.SETTLEMENT, now=0.0)
    assert halt.calls == [HaltReason.SETTLEMENT_FAILURE.value]


def test_record_failure_order_io_trips_on_third_within_window():
    halt = _FakeHalt()
    policy = ErrorPolicy(_FakeBus(), failure_settings=FailureRateSettings.default(), halt=halt)
    policy.record_failure(FailureClass.ORDER_IO, now=0.0)
    policy.record_failure(FailureClass.ORDER_IO, now=1.0)
    assert halt.calls == []
    policy.record_failure(FailureClass.ORDER_IO, now=2.0)
    assert halt.calls == [HaltReason.ORDER_ROUTE_ERRORS.value]


def test_record_failure_none_halt_is_noop():
    policy = ErrorPolicy(_FakeBus(), failure_settings=FailureRateSettings.default())
    policy.record_failure(FailureClass.SETTLEMENT, now=0.0)  # must not raise


def test_record_failure_defaults_from_none_settings():
    """failure_settings=None still yields the D-14 SETTLEMENT halt-on-first defaults."""
    halt = _FakeHalt()
    policy = ErrorPolicy(_FakeBus(), halt=halt)
    policy.record_failure(FailureClass.SETTLEMENT, now=0.0)
    assert halt.calls == [HaltReason.SETTLEMENT_FAILURE.value]


def test_bind_late_wires_halt():
    halt = _FakeHalt()
    policy = ErrorPolicy(_FakeBus(), failure_settings=FailureRateSettings.default())
    policy.bind(halt=halt)
    policy.record_failure(FailureClass.SETTLEMENT, now=0.0)
    assert halt.calls == [HaltReason.SETTLEMENT_FAILURE.value]


# --- on_handler_error: live publish + tripwire after the WR-06 source guard ----


def test_live_publishes_one_error_event_per_handler_failure():
    bus = _FakeBus()
    policy = ErrorPolicy(bus, failure_settings=FailureRateSettings.default())
    fill_event = SimpleNamespace(type=EventType.FILL, time=_TIME)
    try:
        raise ValueError("kaboom")
    except Exception:
        policy.on_handler_error(fill_event, _failing_fill_handler)
    assert len(bus.events) == 1
    published = bus.events[0]
    assert published.error_type == "ValueError"
    assert published.operation == _failing_fill_handler.__qualname__
    assert published.severity is ErrorSeverity.ERROR


def test_wr06_source_guard_error_event_not_republished_or_counted():
    """A failing ERROR-typed event must NOT be republished NOR counted (WR-06).

    Even though this event would classify to FILL_TRANSLATION (halt-on-first), the
    source guard returns BEFORE classification, so halt is never called and no
    error->error ErrorEvent is republished.
    """
    bus = _FakeBus()
    halt = _FakeHalt()
    policy = ErrorPolicy(bus, failure_settings=FailureRateSettings.default(), halt=halt)
    err_event = SimpleNamespace(
        type=EventType.ERROR, time=_TIME, source="okx_exchange", operation="fill-translation"
    )
    try:
        raise RuntimeError("consumer blew up")
    except Exception:
        policy.on_handler_error(err_event, _failing_fill_handler)  # must NOT raise
    assert bus.events == []   # not republished
    assert halt.calls == []   # not counted → not tripped


def test_settlement_trips_on_first():
    """CF-1 HARD CRITERION: a FILL-route handler raising on every event trips the
    SETTLEMENT halt on the FIRST failure; no exception escapes on_handler_error."""
    bus = _FakeBus()
    halt = _FakeHalt()
    policy = ErrorPolicy(bus, failure_settings=FailureRateSettings.default(), halt=halt)
    fill_event = SimpleNamespace(type=EventType.FILL, time=_TIME)
    # Drive the FILL-route handler failing on the first event.
    try:
        raise _SentinelError("settlement boom")
    except Exception:
        policy.on_handler_error(fill_event, _failing_fill_handler)  # must NOT raise
    assert halt.calls == [HaltReason.SETTLEMENT_FAILURE.value]  # halt-on-first
    assert len(bus.events) == 1  # the FILL failure was published (not an ERROR event)
