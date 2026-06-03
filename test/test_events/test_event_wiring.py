import sys
import unittest
from unittest.mock import MagicMock
import queue

# Patch heavy handler modules before importing EventHandler to avoid
# transitive import errors (e.g. CCXT / FORBIDDEN_SYMBOLS chain).
_mock_modules = [
	'itrader.strategy_handler.strategies_handler',
	'itrader.screeners_handler.screeners_handler',
	'itrader.order_handler.order_handler',
	'itrader.portfolio_handler.portfolio_handler',
	'itrader.execution_handler.execution_handler',
	'itrader.universe.universe',
]
for _mod in _mock_modules:
	sys.modules.setdefault(_mod, MagicMock())

from itrader.events_handler.full_event_handler import EventHandler
from itrader.events_handler.event import EventType


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
