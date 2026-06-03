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


class TestMatchingEngineStopTriggers(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_sell_stop_triggers_when_low_pierces(self):
		# stop-loss on a long: SELL stop at 30, bar low 20 -> fills
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].fill_price, 30.0)   # filled at stop (no gap)
		self.assertFalse(self.engine.has_order(1))    # removed from book

	def test_sell_stop_does_not_trigger_when_low_above(self):
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=40, high=45, low=35, close=42))
		self.assertEqual(fills, [])
		self.assertTrue(self.engine.has_order(1))

	def test_sell_stop_gap_fills_at_open(self):
		# bar gaps below the stop: open 25 < stop 30 -> realistic fill at open (worse)
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
		self.assertEqual(fills[0].fill_price, 25.0)   # min(open, stop)

	def test_buy_stop_triggers_when_high_pierces(self):
		# stop on a short: BUY stop at 50, bar high 60 -> fills at stop
		self.engine.submit(make_order_event(OrderType.STOP, 'BUY', 50.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
		self.assertEqual(fills[0].fill_price, 50.0)

	def test_buy_stop_gap_fills_at_open(self):
		# bar gaps above the stop: open 55 > stop 50 -> fill at open (worse)
		self.engine.submit(make_order_event(OrderType.STOP, 'BUY', 50.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=55, high=62, low=54, close=60))
		self.assertEqual(fills[0].fill_price, 55.0)   # max(open, stop)
