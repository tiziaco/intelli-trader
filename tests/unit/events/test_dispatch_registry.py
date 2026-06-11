"""
D-23 group 1 — the dispatch registry asserted AS DATA (Plan 04-06).

``EventHandler.routes`` IS the documented execution order (D-14/D-17):
BAR runs mark-to-market -> resting-order matching -> new signals; FILL
runs positions/cash -> order-mirror reconciliation. These tests lock that
order as literal data (no engine run needed), the explicit empty
SCREENER/UPDATE routes, the race-free FIFO drain semantics (D-15), and
the NotImplementedError contract for unregistered event types (KB1).
"""

import queue
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# Pre-import the real enum module BEFORE the stubbed import below (same
# trick as tests/integration/test_event_wiring.py). Stubbing submodules
# disrupts the import machinery enough to otherwise re-import
# `itrader.core.enums` a second time, producing a distinct EventType
# enum whose members fail identity-based `==`/`is` checks against this
# module's EventType. Caching it first guarantees full_event_handler
# reuses the same EventType.
from itrader.core.enums import EventType  # noqa: E402  (must precede stub import)

# `full_event_handler` imports the full handler chain at module load. We
# stub the heavy handler modules ONLY for the duration of the EventHandler
# import, using patch.dict so sys.modules is restored immediately
# afterwards — this avoids polluting the rest of the pytest session.
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


@pytest.fixture
def wiring():
    """An EventHandler wired to mock collaborators + its queue and a put() helper."""
    q = queue.Queue()
    strategies = MagicMock()
    screeners = MagicMock()
    portfolio = MagicMock()
    order = MagicMock()
    execution = MagicMock()
    bar_event_source = MagicMock()
    handler = EventHandler(
        strategies, screeners, portfolio, order, execution, bar_event_source, q
    )

    def put(event_type):
        ev = MagicMock()
        ev.type = event_type
        q.put(ev)
        return ev

    yield SimpleNamespace(
        q=q, handler=handler, put=put,
        strategies=strategies, screeners=screeners, portfolio=portfolio,
        order=order, execution=execution, bar_event_source=bar_event_source,
    )

    while not q.empty():
        q.get_nowait()


# --- Route lists asserted as literal data (D-23 group 1) -------------------


def test_bar_route_order_is_data(wiring):
    """BAR order is LAW: mark-to-market -> resting-order matching -> new signals."""
    assert wiring.handler.routes[EventType.BAR] == [
        wiring.portfolio.update_portfolios_market_value,
        wiring.execution.on_market_data,
        wiring.strategies.calculate_signals,
    ]


def test_fill_route_order_is_data(wiring):
    """FILL order is LAW: positions/cash -> order-mirror reconciliation."""
    assert wiring.handler.routes[EventType.FILL] == [
        wiring.portfolio.on_fill,
        wiring.order.on_fill,
    ]


def test_time_signal_order_routes_are_data(wiring):
    # TIME runs screening then the feed-backed BarEvent source (Plan 07-02,
    # D-20: the injected bar_event_source IS the feed's factory callable).
    assert wiring.handler.routes[EventType.TIME] == [
        wiring.screeners.screen_markets,
        wiring.bar_event_source,
    ]
    assert wiring.handler.routes[EventType.SIGNAL] == [wiring.order.on_signal]
    assert wiring.handler.routes[EventType.ORDER] == [wiring.execution.on_order]


def test_screener_and_update_routes_are_explicit_empty(wiring):
    """SCREENER (D-screener) and UPDATE (D-live) are explicit empty routes."""
    assert wiring.handler.routes[EventType.SCREENER] == []
    assert wiring.handler.routes[EventType.UPDATE] == []


def test_registry_covers_every_event_type(wiring):
    """Every EventType member has an explicit route — no silent gaps."""
    assert set(wiring.handler.routes) == set(EventType)


# --- Drain semantics (D-15) -------------------------------------------------


def test_drain_dispatches_all_queued_events_fifo(wiring):
    ev1 = wiring.put(EventType.BAR)
    ev2 = wiring.put(EventType.BAR)
    ev3 = wiring.put(EventType.BAR)
    wiring.handler.process_events()
    assert wiring.portfolio.update_portfolios_market_value.call_args_list == [
        call(ev1), call(ev2), call(ev3),
    ]
    assert wiring.q.empty()


def test_drain_dispatches_mixed_event_types(wiring):
    bar = wiring.put(EventType.BAR)
    sig = wiring.put(EventType.SIGNAL)
    fill = wiring.put(EventType.FILL)
    wiring.handler.process_events()
    wiring.execution.on_market_data.assert_called_once_with(bar)
    wiring.order.on_signal.assert_called_once_with(sig)
    wiring.portfolio.on_fill.assert_called_once_with(fill)
    wiring.order.on_fill.assert_called_once_with(fill)
    assert wiring.q.empty()


def test_drain_terminates_on_empty_queue(wiring):
    """get_nowait() + queue.Empty -> break: an empty queue returns immediately."""
    wiring.handler.process_events()
    assert wiring.q.empty()


# --- Unknown event types raise (KB1 / T-04-18) ------------------------------


def test_unknown_event_type_raises_not_implemented(wiring):
    wiring.put("BOGUS-TYPE")
    with pytest.raises(NotImplementedError, match="unsupported event type"):
        wiring.handler.process_events()
