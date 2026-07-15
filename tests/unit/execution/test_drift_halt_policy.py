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

from itrader.core.enums import ErrorSeverity, EventType, SystemStatus
from itrader.events_handler.error_handler import ErrorHandler
from itrader.events_handler.error_policy import FailFastPolicy
from itrader.events_handler.events import ErrorEvent, PortfolioErrorEvent
from itrader.events_handler.full_event_handler import EventHandler
from itrader.trading_system.alert_sink import AlertSink, LogAlertSink
from itrader.trading_system.live_trading_system import LiveTradingSystem

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
    # 08-03/D-06: the policy + consumer are injected at construction. The alert-sink now
    # rides on the ErrorHandler (D-03) — tests set ``handler.error_handler._alert_sink``.
    h = EventHandler(
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
        MagicMock(), q,
        FailFastPolicy(), ErrorHandler(),
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
    handler.error_handler._alert_sink = sink
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
    handler.error_handler._alert_sink = sink
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
    assert handler.error_handler._alert_sink is None
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
    handler.error_handler._alert_sink = sink
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


# --- 05-04: LiveTradingSystem freeze-in-place halt (D-01/D-02/D-06/D-07) --------
#
# The composition-root half of the drift/halt policy: the halt entrypoint sets a
# distinct HALTED status + machine-readable reason, escalates a CRITICAL alert
# through the injected sink, suppresses NEW order submission while BAR/FILL
# streaming continues, and NEVER auto-flattens/auto-cancels. Constructed offline
# for the default 'binance' venue — no OKX credentials, no network.


def _live_system(monkeypatch) -> LiveTradingSystem:
    """A credential-free LiveTradingSystem for the default (non-OKX) venue."""
    for var in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"):
        monkeypatch.delenv(var, raising=False)
    return LiveTradingSystem.for_exchange("binance")


def test_halt_sets_halted_status_and_machine_readable_reason(monkeypatch):
    system = _live_system(monkeypatch)
    system.halt("drift")
    status = system.get_status()
    assert status["status"] == SystemStatus.HALTED.value
    assert status["halt_reason"] == "drift"


def test_halt_emits_critical_alert_through_injected_sink(monkeypatch):
    system = _live_system(monkeypatch)
    sink = _RecordingSink()
    system.event_handler.error_handler._alert_sink = sink
    system.halt("drift")
    # Drain the CRITICAL halt ErrorEvent through the ERROR route -> alert sink.
    system.event_handler.process_events()
    assert len(sink.received) == 1
    assert sink.received[0].severity == ErrorSeverity.CRITICAL


def test_composition_root_wires_a_log_alert_sink(monkeypatch):
    system = _live_system(monkeypatch)
    # The live root injects a LogAlertSink (05-01's None default is the backtest path).
    assert isinstance(system.event_handler.error_handler._alert_sink, LogAlertSink)


def test_halt_suppresses_new_order_submission_but_not_bar_fill(monkeypatch):
    system = _live_system(monkeypatch)
    system.halt("drift")
    system.event_handler._dispatch = MagicMock()

    order_event = MagicMock()
    order_event.type = EventType.ORDER
    signal_event = MagicMock()
    signal_event.type = EventType.SIGNAL
    bar_event = MagicMock()
    bar_event.type = EventType.BAR
    fill_event = MagicMock()
    fill_event.type = EventType.FILL

    # SIGNAL/ORDER are suppressed (frozen in place) — never reach the dispatcher.
    system._safety.gate_and_dispatch(order_event)
    system._safety.gate_and_dispatch(signal_event)
    system.event_handler._dispatch.assert_not_called()

    # BAR/FILL streaming + reconciling continue to drain.
    system._safety.gate_and_dispatch(bar_event)
    system._safety.gate_and_dispatch(fill_event)
    assert system.event_handler._dispatch.call_count == 2


def test_halt_does_not_auto_flatten_or_cancel(monkeypatch):
    system = _live_system(monkeypatch)
    system.halt("drift")
    # ONLY the CRITICAL halt ErrorEvent is queued — no cancel/flatten OrderEvents.
    queued = []
    while not system.global_queue.empty():
        queued.append(system.global_queue.get_nowait())
    assert len(queued) == 1
    assert queued[0].type == EventType.ERROR
    assert queued[0].severity == ErrorSeverity.CRITICAL


def test_halt_is_idempotent_first_reason_wins(monkeypatch):
    system = _live_system(monkeypatch)
    system.halt("drift")
    system.halt("connector-fatal")
    assert system.get_status()["halt_reason"] == "drift"
    # No second CRITICAL event was emitted — the second halt is a no-op.
    count = 0
    while not system.global_queue.empty():
        system.global_queue.get_nowait()
        count += 1
    assert count == 1


def test_portfolio_handler_drift_signal_wired_to_halt(monkeypatch):
    system = _live_system(monkeypatch)
    # The composition root wired PortfolioHandler.set_halt_signal(system.halt), so
    # the engine-thread drift compare's halt signal reaches the freeze-in-place halt.
    system.portfolio_handler._halt_signal("drift")
    status = system.get_status()
    assert status["status"] == SystemStatus.HALTED.value
    assert status["halt_reason"] == "drift"


def test_status_before_halt_has_no_reason(monkeypatch):
    system = _live_system(monkeypatch)
    status = system.get_status()
    assert status["status"] != SystemStatus.HALTED.value
    assert status["halt_reason"] is None
