import unittest
from datetime import datetime
from itrader.events_handler.event import OrderEvent, FillEvent, FillStatus
from itrader.core.enums import OrderType


class TestFillEventSchema(unittest.TestCase):
	def _order_event(self):
		return OrderEvent(
			time=datetime(2024, 1, 1), ticker='BTCUSDT', action='BUY',
			price=40.0, quantity=1.0, exchange='default', strategy_id=1,
			portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
		)

	def test_executed_fill_carries_order_id(self):
		fill = FillEvent.new_fill('EXECUTED', 0.5, self._order_event())
		self.assertEqual(fill.order_id, 7)
		self.assertIs(fill.status, FillStatus.EXECUTED)

	def test_cancelled_status_supported(self):
		fill = FillEvent.new_fill('CANCELLED', 0.0, self._order_event())
		self.assertIs(fill.status, FillStatus.CANCELLED)
		self.assertEqual(fill.order_id, 7)
