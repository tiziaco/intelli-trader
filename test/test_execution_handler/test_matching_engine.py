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


class TestMatchingEngineLimitTriggers(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_sell_limit_triggers_when_high_pierces(self):
		# take-profit on a long: SELL limit at 50, bar high 60 -> fills at limit
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=1))
		fills, _ = self.engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
		self.assertEqual(fills[0].fill_price, 50.0)

	def test_sell_limit_does_not_trigger_when_high_below(self):
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=1))
		fills, _ = self.engine.on_bar(make_bar(open_=40, high=48, low=39, close=47))
		self.assertEqual(fills, [])

	def test_buy_limit_triggers_when_low_pierces(self):
		self.engine.submit(make_order_event(OrderType.LIMIT, 'BUY', 30.0, order_id=2))
		fills, _ = self.engine.on_bar(make_bar(open_=35, high=36, low=25, close=28))
		self.assertEqual(fills[0].fill_price, 30.0)

	def test_independent_orders_on_same_bar_both_fill(self):
		# two unrelated orders (no bracket link) both trigger -> both fill
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 55.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))
		self.assertEqual(len(fills), 2)
		self.assertEqual(cancels, [])

	def test_ignores_ticker_not_in_bar(self):
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1, ticker='ETHUSDT'))
		fills, _ = self.engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))  # BTCUSDT only
		self.assertEqual(fills, [])
		self.assertTrue(self.engine.has_order(1))


class TestMatchingEngineOCO(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()
		# A bracket: entry id 100; SL and TP are children (parent_order_id=100).
		self.sl = make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=11, parent_order_id=100)
		self.tp = make_order_event(OrderType.LIMIT, 'SELL', 55.0, order_id=12, parent_order_id=100)

	def test_tp_fill_cancels_sl_sibling(self):
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		# TP triggers (high 60 >= 55), SL does not (low 40 > 30)
		fills, cancels = self.engine.on_bar(make_bar(open_=50, high=60, low=40, close=58))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_event.order_id, 12)
		self.assertEqual(len(cancels), 1)
		self.assertEqual(cancels[0].order_event.order_id, 11)
		self.assertFalse(self.engine.has_order(11))
		self.assertFalse(self.engine.has_order(12))

	def test_same_bar_both_pierced_prefers_stop(self):
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		# wide bar pierces BOTH: low 20 <= 30 (SL) and high 60 >= 55 (TP)
		fills, cancels = self.engine.on_bar(make_bar(open_=45, high=60, low=20, close=40))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_event.order_id, 11)      # pessimistic: STOP fills
		self.assertEqual(len(cancels), 1)
		self.assertEqual(cancels[0].order_event.order_id, 12)    # TP cancelled

	def test_non_triggered_sibling_still_cancelled(self):
		# Only TP triggers; SL does not, but must be cancelled because its bracket leg filled.
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		fills, cancels = self.engine.on_bar(make_bar(open_=50, high=56, low=45, close=55))
		self.assertEqual(fills[0].order_event.order_id, 12)
		self.assertEqual([c.order_event.order_id for c in cancels], [11])

	def test_two_independent_brackets_both_resolve(self):
		# Two distinct brackets resolve on the same bar without cross-contamination.
		# Bracket A: SL at 20 (no trigger, low 25 > 20), TP at 55 (fills, high 70 >= 55) -> TP wins.
		sl_a = make_order_event(OrderType.STOP,  'SELL', 20.0, order_id=21, parent_order_id=200)
		tp_a = make_order_event(OrderType.LIMIT, 'SELL', 55.0, order_id=22, parent_order_id=200)
		# Bracket B: SL at 30 (fills, low 25 <= 30), TP at 80 (no trigger, high 70 < 80) -> SL wins.
		sl_b = make_order_event(OrderType.STOP,  'SELL', 30.0, order_id=31, parent_order_id=300)
		tp_b = make_order_event(OrderType.LIMIT, 'SELL', 80.0, order_id=32, parent_order_id=300)
		for o in (sl_a, tp_a, sl_b, tp_b):
			self.engine.submit(o)
		fills, cancels = self.engine.on_bar(make_bar(open_=40, high=70, low=25, close=45))
		self.assertEqual(len(fills), 2)
		self.assertEqual(len(cancels), 2)
		self.assertEqual({f.order_event.order_id for f in fills}, {22, 31})    # A's TP, B's SL
		self.assertEqual({c.order_event.order_id for c in cancels}, {21, 32})  # A's SL, B's TP
