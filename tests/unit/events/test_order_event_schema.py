import unittest
from datetime import datetime
from itrader.events_handler.event import OrderEvent
from itrader.core.enums import OrderType, OrderCommand
from itrader.order_handler.order import Order


class TestOrderEventSchema(unittest.TestCase):
	def _order(self, order_type):
		return Order(
			time=datetime(2024, 1, 1), type=order_type, status=None,
			ticker='BTCUSDT', action='SELL', price=42.0, quantity=2.0,
			exchange='default', strategy_id=1, portfolio_id=1,
		)

	def test_preserves_real_order_type(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.STOP))
		self.assertIs(oe.order_type, OrderType.STOP)

	def test_preserves_order_id(self):
		order = self._order(OrderType.LIMIT)
		oe = OrderEvent.new_order_event(order)
		self.assertEqual(oe.order_id, order.id)

	def test_command_defaults_to_new(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.MARKET))
		self.assertIs(oe.command, OrderCommand.NEW)

	def test_command_can_be_overridden(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.STOP), command=OrderCommand.CANCEL)
		self.assertIs(oe.command, OrderCommand.CANCEL)

	def test_parent_order_id_copied(self):
		order = self._order(OrderType.STOP)
		order.parent_order_id = 999
		oe = OrderEvent.new_order_event(order)
		self.assertEqual(oe.parent_order_id, 999)
