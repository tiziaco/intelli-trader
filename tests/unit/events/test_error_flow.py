"""
D-23 group 3 — error flow through the dispatcher (Plan 04-06; retargeted 08-03).

Locks: ERROR events route to the formalized ``ErrorHandler.on_error`` consumer and the
run CONTINUES; unexpected handler exceptions re-raise through the injected
``FailFastPolicy`` seam (backtest policy, T-04-15/D-06); the latent-UPDATE-crash
regression (Pitfall 5 — the legacy ``PortfolioErrorEvent`` reused ``EventType.UPDATE``
and the old if/elif chain had no UPDATE branch, so a portfolio failure crashed the
dispatcher); UPDATE-typed events dispatch to the explicit empty route without raising.

08-03 also locks the live seam: with the publish-and-continue ``ErrorPolicy`` injected +
a fake ``halt`` bound, a FILL-route handler failing trips SETTLEMENT halt-on-first while
``process_events`` keeps draining and no exception escapes (ERR-03 / WR-06); and a CRITICAL
ErrorEvent + a PortfolioErrorEvent both funnel through the one ERROR route (ERR-04).
"""

import queue
import sys
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the real enum module BEFORE the stubbed import below (same
# trick as tests/integration/test_event_wiring.py) so full_event_handler
# reuses the same cached EventType enum.
from itrader.core.enums import ErrorSeverity, EventType, HaltReason  # noqa: E402  (must precede stub import)

# Pre-import the events package OUTSIDE the stub block too: it pulls
# pandas at runtime, and patch.dict would otherwise EVICT freshly-imported
# heavy modules from sys.modules on exit — a later genuine `import numpy`
# would then re-execute numpy, duplicating its `_NoValue` sentinel and
# breaking scipy imports elsewhere in the session.
from itrader.events_handler.events import (  # noqa: E402
    ErrorEvent,
    PortfolioErrorEvent,
)
# The injected policy + consumer (08-03/D-01/D-06) — pure imports, no stub needed.
from itrader.events_handler.error_handler import ErrorHandler  # noqa: E402
from itrader.events_handler.error_policy import (  # noqa: E402
    ErrorPolicy,
    FailFastPolicy,
)

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

_TIME = datetime(2024, 1, 1, 12, 0, 0)


@pytest.fixture
def wiring():
    """An EventHandler wired to mock collaborators + the injected FailFastPolicy /
    ErrorHandler (08-03/D-06), its queue and a put() helper.

    The ERROR-route consumer is the injected ``ErrorHandler`` now (NOT the dispatcher's
    own logger) — tests assert against ``error_handler.logger``. FailFastPolicy is the
    backtest arm (bare re-raise) so the fail-fast test still propagates.
    """
    q = queue.Queue()
    strategies = MagicMock()
    screeners = MagicMock()
    portfolio = MagicMock()
    order = MagicMock()
    execution = MagicMock()
    bar_event_source = MagicMock()
    error_policy = FailFastPolicy()
    error_handler = ErrorHandler()
    handler = EventHandler(
        strategies, screeners, portfolio, order, execution, bar_event_source, q,
        error_policy, error_handler,
    )

    def put(event_type):
        ev = MagicMock()
        ev.type = event_type
        q.put(ev)
        return ev

    yield SimpleNamespace(
        q=q, handler=handler, put=put,
        error_policy=error_policy, error_handler=error_handler,
        strategies=strategies, screeners=screeners, portfolio=portfolio,
        order=order, execution=execution, bar_event_source=bar_event_source,
    )

    while not q.empty():
        q.get_nowait()


# --- ERROR events reach the log consumer; the run continues -----------------


def test_error_event_routes_to_log_consumer_and_run_continues(wiring):
    wiring.error_handler.logger = MagicMock()
    err = ErrorEvent(
        time=_TIME,
        source="execution",
        error_type="RuntimeError",
        error_message="boom",
        operation="fill",
        correlation_id="abc-123",
    )
    wiring.q.put(err)
    wiring.handler.process_events()  # must NOT raise
    wiring.error_handler.logger.error.assert_called_once()
    _, kwargs = wiring.error_handler.logger.error.call_args
    assert kwargs["source"] == "execution"
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["error_message"] == "boom"
    assert kwargs["operation"] == "fill"
    assert kwargs["correlation_id"] == "abc-123"
    assert wiring.q.empty()


def test_error_event_severity_maps_to_warning_level(wiring):
    wiring.error_handler.logger = MagicMock()
    err = ErrorEvent(
        time=_TIME,
        source="portfolio",
        error_type="ValueError",
        error_message="soft failure",
        severity=ErrorSeverity.WARNING,
    )
    wiring.q.put(err)
    wiring.handler.process_events()
    wiring.error_handler.logger.warning.assert_called_once()
    wiring.error_handler.logger.error.assert_not_called()


# --- Fail-fast seam: unexpected handler exceptions re-raise (T-04-15) -------


class _SentinelError(Exception):
    """Distinct type so the test proves the ORIGINAL exception propagates."""


def test_handler_exception_propagates_out_of_process_events(wiring):
    wiring.portfolio.on_fill.side_effect = _SentinelError("portfolio blew up")
    wiring.put(EventType.FILL)
    with pytest.raises(_SentinelError, match="portfolio blew up"):
        wiring.handler.process_events()
    # Fail-fast: the second FILL handler never runs after the first raises.
    wiring.order.on_fill.assert_not_called()


# --- Pitfall 5 regression: PortfolioErrorEvent no longer crashes ------------


def test_portfolio_error_event_reaches_log_consumer_not_a_crash(wiring):
    """The latent-UPDATE-crash regression (Pitfall 5).

    The legacy PortfolioErrorEvent carried type=EventType.UPDATE and the
    old dispatch chain had no UPDATE branch — a portfolio failure with
    publish_error_events enabled fell into `raise NotImplementedError`.
    The event now carries type=EventType.ERROR and must reach the log
    consumer; the run continues.
    """
    wiring.error_handler.logger = MagicMock()
    err = PortfolioErrorEvent(
        time=_TIME,
        error_type="InsufficientFundsError",
        error_message="not enough cash",
        operation="on_fill",
        portfolio_id=42,
    )
    assert err.type is EventType.ERROR
    wiring.q.put(err)
    wiring.handler.process_events()  # must NOT raise
    wiring.error_handler.logger.error.assert_called_once()
    _, kwargs = wiring.error_handler.logger.error.call_args
    assert kwargs["source"] == "portfolio"
    assert kwargs["error_type"] == "InsufficientFundsError"
    assert kwargs["portfolio_id"] == 42


# --- UPDATE events hit the explicit empty route without raising -------------


def test_update_event_dispatches_to_empty_route_without_raising(wiring):
    wiring.put(EventType.UPDATE)
    wiring.handler.process_events()  # must NOT raise
    for collaborator in (
        wiring.strategies,
        wiring.screeners,
        wiring.portfolio,
        wiring.order,
        wiring.execution,
        wiring.bar_event_source,
    ):
        assert collaborator.mock_calls == []
    assert wiring.q.empty()


# --- ERR-03: live FILL-route failure trips the tripwire + keeps draining -----


def _build_live_wiring(portfolio, *, alert_sink=None):
    """Build an EventHandler wired to the LIVE publish-and-continue ErrorPolicy.

    Mirrors ``build_live_system``'s compose seam (D-06): the injected ``ErrorPolicy`` is
    the dispatcher failure policy AND the ErrorHandler's ``failure_sink`` (the shared
    tripwire the off-thread okx event would count through). failure_settings=None arms the
    in-module D-14 defaults (SETTLEMENT threshold 1 → halt-on-first).
    """
    q = queue.Queue()
    error_policy = ErrorPolicy(q)
    error_handler = ErrorHandler(alert_sink=alert_sink, failure_sink=error_policy)
    handler = EventHandler(
        MagicMock(), MagicMock(), portfolio, MagicMock(), MagicMock(), MagicMock(), q,
        error_policy, error_handler,
    )
    return SimpleNamespace(
        q=q, handler=handler, error_policy=error_policy, error_handler=error_handler)


def test_live_fill_route_failure_trips_halt_and_keeps_draining():
    """ERR-03 hard criterion: a FILL (settlement) handler failing EVERY event drives the
    injected fake ``halt`` on the FIRST failure (SETTLEMENT halt-on-first) while
    ``process_events`` keeps draining and NO exception escapes (WR-06 terminal swallow).
    """
    portfolio = MagicMock()
    portfolio.on_fill.side_effect = _SentinelError("settlement boom")
    w = _build_live_wiring(portfolio)

    fake_halt = MagicMock(name="safety.halt")
    w.error_policy.bind(halt=fake_halt)

    # A FILL event whose first route handler (portfolio.on_fill) raises on every event.
    w.q.put(SimpleNamespace(type=EventType.FILL, time=_TIME))
    w.handler.process_events()  # must NOT raise — WR-06 publish-and-continue + swallow

    # SETTLEMENT halt-on-first: the tripwire fired exactly once with the typed reason.
    fake_halt.assert_called_once_with(HaltReason.SETTLEMENT_FAILURE.value)
    # The queue is fully drained (the republished ErrorEvent was consumed + swallowed,
    # never re-counted — no error->error livelock).
    assert w.q.empty()
    # The breaker snapshot surfaces the trip for get_status (D-13).
    assert w.error_policy.breaker_snapshot()["last_trip_reason"] == (
        HaltReason.SETTLEMENT_FAILURE.value)


# --- ERR-04: every error source funnels through the ONE ERROR route ----------


def test_critical_and_portfolio_error_events_both_funnel_to_error_handler():
    """ERR-04: a CRITICAL ErrorEvent (the halt escalation) AND a PortfolioErrorEvent both
    reach ``ErrorHandler.on_error`` via the single ERROR route — the CRITICAL one escalates
    to the injected alert-sink, the portfolio one logs at ERROR; the run continues.
    """
    alert_sink = MagicMock(name="alert_sink")
    w = _build_live_wiring(MagicMock(), alert_sink=alert_sink)
    w.error_handler.logger = MagicMock()

    crit = ErrorEvent(
        time=_TIME,
        source="safety_controller",
        error_type="EngineHalted",
        error_message="halted: settlement-failure",
        operation="halt",
        severity=ErrorSeverity.CRITICAL,
    )
    perr = PortfolioErrorEvent(
        time=_TIME,
        error_type="InsufficientFundsError",
        error_message="not enough cash",
        operation="on_fill",
        portfolio_id=7,
    )
    w.q.put(crit)
    w.q.put(perr)
    w.handler.process_events()  # must NOT raise

    # Both funneled through the ONE ERROR-route consumer.
    w.error_handler.logger.critical.assert_called_once()   # CRITICAL ErrorEvent
    w.error_handler.logger.error.assert_called_once()      # PortfolioErrorEvent (ERROR)
    # Only the CRITICAL event escalates to the injected alert-sink egress.
    alert_sink.alert.assert_called_once_with(crit)
    assert w.q.empty()
