import sys
import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the real enum module BEFORE the stubbed import below. Stubbing
# submodules disrupts the import machinery enough to otherwise re-import
# `itrader.core.enums` a second time, producing a distinct EventType
# enum whose members fail identity-based `==` against the test's EventType.
# Caching it first guarantees full_event_handler reuses the same EventType.
from itrader.core.enums import EventType  # noqa: E402  (must precede stub import)

# `full_event_handler` imports the full handler chain at module load, which
# currently fails on an unrelated pre-existing bug (price_handler -> CCXT ->
# `from itrader.config import FORBIDDEN_SYMBOLS`, shadowed by the config package).
# We stub the heavy handler modules ONLY for the duration of the EventHandler
# import, using patch.dict so sys.modules is restored immediately afterwards —
# this avoids polluting the rest of the pytest session (other suites must still
# import the real modules).
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


def test_bar_routes_to_execution_market_data(wiring):
    ev = wiring.put(EventType.BAR)
    wiring.handler.process_events()
    wiring.execution.on_market_data.assert_called_once_with(ev)
    wiring.order.process_orders_on_market_data.assert_not_called()


def test_fill_routes_to_portfolio_and_order(wiring):
    ev = wiring.put(EventType.FILL)
    wiring.handler.process_events()
    wiring.portfolio.on_fill.assert_called_once_with(ev)
    wiring.order.on_fill.assert_called_once_with(ev)
