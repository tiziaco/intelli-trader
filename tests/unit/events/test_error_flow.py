"""
D-23 group 3 — error flow through the dispatcher (Plan 04-06).

Locks: ERROR events route to the real log consumer and the run CONTINUES;
unexpected handler exceptions re-raise through the ``_on_handler_error``
fail-fast seam (backtest policy, T-04-15); the latent-UPDATE-crash
regression (Pitfall 5 — the legacy ``PortfolioErrorEvent`` reused
``EventType.UPDATE`` and the old if/elif chain had no UPDATE branch, so a
portfolio failure crashed the dispatcher); UPDATE-typed events dispatch
to the explicit empty route without raising.
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
from itrader.core.enums import EventType  # noqa: E402  (must precede stub import)

# Pre-import the events package OUTSIDE the stub block too: it pulls
# pandas at runtime, and patch.dict would otherwise EVICT freshly-imported
# heavy modules from sys.modules on exit — a later genuine `import numpy`
# would then re-execute numpy, duplicating its `_NoValue` sentinel and
# breaking scipy imports elsewhere in the session.
from itrader.events_handler.events import (  # noqa: E402
    ErrorEvent,
    PortfolioErrorEvent,
)

_STUB_MODULES = {
    name: MagicMock()
    for name in [
        "itrader.strategy_handler.strategies_handler",
        "itrader.screeners_handler.screeners_handler",
        "itrader.order_handler.order_handler",
        "itrader.portfolio_handler.portfolio_handler",
        "itrader.execution_handler.execution_handler",
        "itrader.universe.universe",
    ]
}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler

_TIME = datetime(2024, 1, 1, 12, 0, 0)


@pytest.fixture
def wiring():
    """An EventHandler wired to mock collaborators + its queue and a put() helper."""
    q = queue.Queue()
    strategies = MagicMock()
    screeners = MagicMock()
    portfolio = MagicMock()
    order = MagicMock()
    execution = MagicMock()
    universe = MagicMock()
    handler = EventHandler(
        strategies, screeners, portfolio, order, execution, universe, q
    )

    def put(event_type):
        ev = MagicMock()
        ev.type = event_type
        q.put(ev)
        return ev

    yield SimpleNamespace(
        q=q, handler=handler, put=put,
        strategies=strategies, screeners=screeners, portfolio=portfolio,
        order=order, execution=execution, universe=universe,
    )

    while not q.empty():
        q.get_nowait()


# --- ERROR events reach the log consumer; the run continues -----------------


def test_error_event_routes_to_log_consumer_and_run_continues(wiring):
    wiring.handler.logger = MagicMock()
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
    wiring.handler.logger.error.assert_called_once()
    _, kwargs = wiring.handler.logger.error.call_args
    assert kwargs["source"] == "execution"
    assert kwargs["error_type"] == "RuntimeError"
    assert kwargs["error_message"] == "boom"
    assert kwargs["operation"] == "fill"
    assert kwargs["correlation_id"] == "abc-123"
    assert wiring.q.empty()


def test_error_event_severity_maps_to_warning_level(wiring):
    wiring.handler.logger = MagicMock()
    err = ErrorEvent(
        time=_TIME,
        source="portfolio",
        error_type="ValueError",
        error_message="soft failure",
        severity="WARNING",
    )
    wiring.q.put(err)
    wiring.handler.process_events()
    wiring.handler.logger.warning.assert_called_once()
    wiring.handler.logger.error.assert_not_called()


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
    wiring.handler.logger = MagicMock()
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
    wiring.handler.logger.error.assert_called_once()
    _, kwargs = wiring.handler.logger.error.call_args
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
        wiring.universe,
    ):
        assert collaborator.mock_calls == []
    assert wiring.q.empty()
