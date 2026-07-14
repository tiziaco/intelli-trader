"""ErrorHandler — the formalized ERROR-route consumer (D-01).

Locks: severity-mapped log binding ONLY declared ErrorEvent fields; CRITICAL →
injected alert-sink escalation; D-17 live-only ``state.last_error`` persist via the
injected system_store (scrubbed declared fields, no raw payload — T-05-27); the
FILL_TRANSLATION counting seam into the shared ErrorPolicy tripwire; and the WR-06
consumer guard — a raising alert_sink / logger / upsert / record_failure is swallowed
and ``on_error`` NEVER re-raises into ``_dispatch``.
"""

from datetime import datetime
from unittest.mock import MagicMock

from itrader.core.enums import ErrorSeverity, FailureClass
from itrader.events_handler.events import ErrorEvent
from itrader.events_handler.error_handler import ErrorHandler

_TIME = datetime(2024, 1, 1, 12, 0, 0)

_DECLARED_KEYS = {
    "source", "error_type", "error_message", "operation",
    "correlation_id", "severity", "portfolio_id", "details",
}


class _FakeAlertSink:
    def __init__(self) -> None:
        self.alerts: list = []

    def alert(self, event) -> None:
        self.alerts.append(event)


class _RaisingAlertSink:
    def alert(self, event) -> None:
        raise RuntimeError("alert boom")


class _FakeSystemStore:
    def __init__(self) -> None:
        self.upserts: list = []

    def upsert(self, key, value, at) -> None:
        self.upserts.append((key, value, at))


class _RaisingSystemStore:
    def upsert(self, key, value, at) -> None:
        raise RuntimeError("sql boom")


class _FakeFailureSink:
    def __init__(self) -> None:
        self.records: list = []

    def record_failure(self, failure_class) -> None:
        self.records.append(failure_class)


def _err(severity=ErrorSeverity.ERROR, **overrides):
    fields = dict(
        time=_TIME,
        source="execution",
        error_type="RuntimeError",
        error_message="boom",
        operation="fill",
        severity=severity,
    )
    fields.update(overrides)
    return ErrorEvent(**fields)


# --- severity map -------------------------------------------------------------


def test_warning_maps_to_warning_log():
    handler = ErrorHandler()
    handler.logger = MagicMock()
    handler.on_error(_err(severity=ErrorSeverity.WARNING))
    handler.logger.warning.assert_called_once()
    handler.logger.error.assert_not_called()


def test_critical_maps_to_critical_log_and_escalates():
    sink = _FakeAlertSink()
    handler = ErrorHandler(alert_sink=sink)
    handler.logger = MagicMock()
    event = _err(severity=ErrorSeverity.CRITICAL)
    handler.on_error(event)
    handler.logger.critical.assert_called_once()
    assert sink.alerts == [event]


def test_error_maps_to_error_log():
    handler = ErrorHandler()
    handler.logger = MagicMock()
    handler.on_error(_err(severity=ErrorSeverity.ERROR))
    handler.logger.error.assert_called_once()


def test_non_critical_does_not_escalate():
    sink = _FakeAlertSink()
    handler = ErrorHandler(alert_sink=sink)
    handler.on_error(_err(severity=ErrorSeverity.ERROR))
    assert sink.alerts == []


# --- WR-06 consumer guard swallows -------------------------------------------


def test_raising_alert_sink_is_swallowed():
    handler = ErrorHandler(alert_sink=_RaisingAlertSink())
    handler.logger = MagicMock()
    # CRITICAL triggers the raising alert → must be swallowed, no exception escapes.
    assert handler.on_error(_err(severity=ErrorSeverity.CRITICAL)) is None
    handler.logger.error.assert_called_once()  # last-resort recovery log


def test_raising_system_store_is_swallowed():
    handler = ErrorHandler(system_store=_RaisingSystemStore())
    # No exception escapes even though upsert raises inside the guard.
    assert handler.on_error(_err(severity=ErrorSeverity.ERROR)) is None


# --- D-17 last_error persist (live-only) --------------------------------------


def test_last_error_persisted_with_scrubbed_declared_fields():
    store = _FakeSystemStore()
    handler = ErrorHandler(system_store=store)
    handler.on_error(_err(severity=ErrorSeverity.ERROR, correlation_id=None))
    assert len(store.upserts) == 1
    key, value, at = store.upserts[0]
    assert key == "state.last_error"
    assert value["source"] == "execution"
    assert value["error_type"] == "RuntimeError"
    assert value["error_message"] == "boom"
    assert value["operation"] == "fill"
    assert value["severity"] == ErrorSeverity.ERROR.value
    assert at == _TIME
    # Secret scrub (T-05-27): only declared ErrorEvent fields, no raw payload.
    assert set(value.keys()) <= _DECLARED_KEYS


def test_no_system_store_is_noop():
    # No system_store → no persistence attempt, no exception (backtest no-op).
    handler = ErrorHandler(system_store=None)
    assert handler.on_error(_err(severity=ErrorSeverity.ERROR)) is None


# --- FILL_TRANSLATION counting seam ------------------------------------------


def test_okx_fill_translation_event_counts_into_failure_sink():
    sink = _FakeFailureSink()
    handler = ErrorHandler(failure_sink=sink)
    event = _err(
        source="okx_exchange", operation="fill-translation", error_type="ValueError"
    )
    handler.on_error(event)
    assert sink.records == [FailureClass.FILL_TRANSLATION]


def test_generic_error_event_not_counted():
    sink = _FakeFailureSink()
    handler = ErrorHandler(failure_sink=sink)
    handler.on_error(_err(source="live_trading_system", operation="on_fill"))
    assert sink.records == []


def test_raising_failure_sink_is_swallowed():
    class _RaisingFailureSink:
        def record_failure(self, failure_class):
            raise RuntimeError("record boom")

    handler = ErrorHandler(failure_sink=_RaisingFailureSink())
    event = _err(source="okx_exchange", operation="fill-translation")
    assert handler.on_error(event) is None
