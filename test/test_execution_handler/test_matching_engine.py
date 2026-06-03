import unittest
import pandas as pd
from datetime import datetime

from itrader.execution_handler.matching_engine import MatchingEngine, FillDecision, CancelDecision
from itrader.events_handler.event import OrderEvent, BarEvent
from itrader.core.enums import OrderType, OrderCommand


def make_order_event(order_type, action, price, order_id,
                     ticker='BTCUSDT', quantity=1.0, parent_order_id=None):
	return OrderEvent(
		time=datetime(2024, 1, 1), ticker=ticker, action=action, price=price,
		quantity=quantity, exchange='default', strategy_id=1, portfolio_id=1,
		order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
		command=OrderCommand.NEW,
	)


def make_bar(open_, high, low, close, ticker='BTCUSDT'):
	bars = {ticker: pd.DataFrame(
		{'open': [open_], 'high': [high], 'low': [low], 'close': [close], 'volume': [1]})}
	return BarEvent(time=datetime(2024, 1, 1), bars=bars)


class TestMatchingEngineBook(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_submit_then_cancel(self):
		oe = make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1)
		self.engine.submit(oe)
		self.assertTrue(self.engine.has_order(1))
		self.assertTrue(self.engine.cancel(1))
		self.assertFalse(self.engine.has_order(1))

	def test_cancel_unknown_returns_false(self):
		self.assertFalse(self.engine.cancel(123))

	def test_modify_price_and_quantity(self):
		oe = make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=2, quantity=1.0)
		self.engine.submit(oe)
		self.assertTrue(self.engine.modify(2, new_price=55.0, new_quantity=3.0))
		resting = self.engine.get_order(2)
		self.assertEqual(resting.price, 55.0)
		self.assertEqual(resting.quantity, 3.0)

	def test_modify_unknown_returns_false(self):
		self.assertFalse(self.engine.modify(999, new_price=1.0))
