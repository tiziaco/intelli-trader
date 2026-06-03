import sys
import queue
import unittest
from unittest.mock import MagicMock, patch

# Pre-import the real event module BEFORE the stubbed import below. Stubbing
# submodules disrupts the import machinery enough to otherwise re-import
# `itrader.events_handler.event` a second time, producing a distinct EventType
# enum whose members fail identity-based `==` against the test's EventType.
# Caching it first guarantees full_event_handler reuses the same EventType.
from itrader.events_handler.event import EventType  # noqa: E402  (must precede stub import)

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
		'itrader.strategy_handler.strategies_handler',
		'itrader.screeners_handler.screeners_handler',
		'itrader.order_handler.order_handler',
		'itrader.portfolio_handler.portfolio_handler',
		'itrader.execution_handler.execution_handler',
		'itrader.universe.universe',
	]
}
with patch.dict(sys.modules, _STUB_MODULES):
	from itrader.events_handler.full_event_handler import EventHandler


class TestEventWiring(unittest.TestCase):
	def setUp(self):
		self.q = queue.Queue()
		self.strategies = MagicMock()
		self.screeners = MagicMock()
		self.portfolio = MagicMock()
		self.order = MagicMock()
		self.execution = MagicMock()
		self.universe = MagicMock()
		self.handler = EventHandler(
			self.strategies, self.screeners, self.portfolio, self.order,
			self.execution, self.universe, self.q)

	def _put(self, event_type):
		ev = MagicMock()
		ev.type = event_type
		self.q.put(ev)
		return ev

	def test_bar_routes_to_execution_market_data(self):
		ev = self._put(EventType.BAR)
		self.handler.process_events()
		self.execution.on_market_data.assert_called_once_with(ev)
		self.order.process_orders_on_market_data.assert_not_called()

	def test_fill_routes_to_portfolio_and_order(self):
		ev = self._put(EventType.FILL)
		self.handler.process_events()
		self.portfolio.on_fill.assert_called_once_with(ev)
		self.order.on_fill.assert_called_once_with(ev)
