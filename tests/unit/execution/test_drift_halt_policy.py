"""
Unit tests for the halt vocabulary + CRITICAL alert egress (D-06/D-07, RES-01/T-05-01).

Locks the three reconciliation-cluster egress contracts that downstream Phase-5
plans (drift/halt 05-04, resilience 05-08) build against:

- ``SystemStatus.HALTED`` is a distinct machine-readable member (D-07) — a halt is
  not RUNNING/STOPPED/ERROR.
- A CRITICAL ``ErrorEvent`` routed through the dispatcher reaches an injected
  ``AlertSink`` (D-06); a non-CRITICAL event does NOT.
- The egress carries ONLY declared ``ErrorEvent`` fields — no raw connector context,
  so no ``OKX_API`` / secret substring can leak (Pitfall 16, T-05-01).
"""

import queue
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from itrader.core.enums import ErrorSeverity, SystemStatus
from itrader.events_handler.events import ErrorEvent, PortfolioErrorEvent
from itrader.events_handler.full_event_handler import EventHandler
from itrader.trading_system.alert_sink import AlertSink, LogAlertSink

_TIME = datetime(2024, 1, 1, 12, 0, 0)


class _RecordingSink:
    """Structural AlertSink fake that records the events it receives."""

    def __init__(self) -> None:
        self.received: list[ErrorEvent] = []

    def alert(self, event: ErrorEvent) -> None:
        self.received.append(event)


@pytest.fixture
def handler():
    q: queue.Queue = queue.Queue()
    h = EventHandler(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        MagicMock(), q,
    )
    return h


# --- D-07: HALTED is a distinct machine-readable status ---------------------


def test_halted_is_a_distinct_system_status_member():
    assert SystemStatus.HALTED.value == "halted"
    # Distinct from the pre-existing lifecycle members (not a reuse/alias).
    assert SystemStatus.HALTED not in (
        SystemStatus.RUNNING,
        SystemStatus.STOPPED,
        SystemStatus.ERROR,
        SystemStatus.STOPPING,
        SystemStatus.STARTING,
    )


# --- D-06: CRITICAL routes to the injected sink; nothing else does ----------


def test_critical_error_event_reaches_injected_alert_sink(handler):
    sink = _RecordingSink()
    handler._alert_sink = sink
    err = ErrorEvent(
        time=_TIME,
        source="reconcile",
        error_type="DriftExceeded",
        error_message="per-symbol drift beyond tolerance — halting",
        operation="reconcile",
        severity=ErrorSeverity.CRITICAL,
    )
    handler.global_queue.put(err)
    handler.process_events()
    assert sink.received == [err]


def test_non_critical_error_event_does_not_reach_alert_sink(handler):
    sink = _RecordingSink()
    handler._alert_sink = sink
    for severity in (ErrorSeverity.ERROR, ErrorSeverity.WARNING):
        err = ErrorEvent(
            time=_TIME,
            source="portfolio",
            error_type="ValueError",
            error_message="soft failure",
            severity=severity,
        )
        handler.global_queue.put(err)
    handler.process_events()
    assert sink.received == []


def test_alert_sink_none_on_backtest_path_is_a_noop(handler):
    # Default: no egress wired — a CRITICAL event must not raise.
    assert handler._alert_sink is None
    err = ErrorEvent(
        time=_TIME,
        source="reconcile",
        error_type="DriftExceeded",
        error_message="halt",
        severity=ErrorSeverity.CRITICAL,
    )
    handler.global_queue.put(err)
    handler.process_events()  # must not raise
    assert handler.global_queue.empty()


# --- D-06 seam typing: LogAlertSink structurally satisfies AlertSink --------


def test_log_alert_sink_satisfies_alert_sink_protocol():
    assert isinstance(LogAlertSink(), AlertSink)


# --- T-05-01 / Pitfall 16: no secret leaks through the egress ----------------


def test_critical_egress_carries_no_secret_substring(handler):
    sink = _RecordingSink()
    handler._alert_sink = sink
    # A realistic portfolio halt event — the producer binds only declared
    # ErrorEvent fields; raw connector context / OKX_API secrets never enter.
    err = PortfolioErrorEvent(
        time=_TIME,
        error_type="ReconciliationUnresolved",
        error_message="venue balance mismatch — halting portfolio",
        operation="reconcile",
        severity=ErrorSeverity.CRITICAL,
        details={"symbol": "BTC/USDT", "drift": "0.00000002"},
    )
    handler.global_queue.put(err)
    handler.process_events()

    (received,) = sink.received
    # The egress only reads declared ErrorEvent fields; concatenate them all
    # and assert no secret marker appears.
    declared = " ".join(
        str(getattr(received, f))
        for f in (
            "source", "error_type", "error_message", "operation",
            "correlation_id", "severity", "details", "portfolio_id",
        )
    )
    for secret_marker in ("OKX_API", "api_secret", "passphrase", "api_key"):
        assert secret_marker not in declared


def test_log_alert_sink_emits_marked_critical_without_secrets():
    sink = LogAlertSink()
    sink.logger = MagicMock()
    err = ErrorEvent(
        time=_TIME,
        source="reconcile",
        error_type="ConnectorFatal",
        error_message="unrecoverable connector error — halting",
        operation="reconcile",
        severity=ErrorSeverity.CRITICAL,
    )
    sink.alert(err)
    sink.logger.critical.assert_called_once()
    _, kwargs = sink.logger.critical.call_args
    assert kwargs["alert"] is True
    assert kwargs["source"] == "reconcile"
    assert kwargs["error_type"] == "ConnectorFatal"
    emitted = " ".join(str(v) for v in kwargs.values())
    for secret_marker in ("OKX_API", "api_secret", "passphrase", "api_key"):
        assert secret_marker not in emitted
