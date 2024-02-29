import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.strategy_handler.base import Strategy
from itrader.events_handler.event import SignalEvent, BarEvent


class TestStrategy(unittest.TestCase):
	"""
	Test the base strategy object performing the different actions
	like send a buy and sell signal.
	"""

	@classmethod
	def setUpClass(cls):
		"""
		Set up the test data that will be used across all test methods.
		"""
		cls.user_id = 1
		cls.portfolio_name = 'test_pf'
		cls.ticker = 'SOLUSDT'
		cls.queue = Queue()
		cls.strategy = Strategy("test_strategy", '1h', [cls.ticker],
							global_queue=cls.queue)
		cls.strategy.subscribe_portfolio(cls.portfolio_name)

	def setUp(self):
		"""
		Set up the the BaseSTartegy instance and the global queue.
		"""

		bars_dict = {self.ticker: pd.DataFrame({'Open': [100], 'High': [110], 'Low': [90], 'Close': [105], 'Volume': [1000]})}
		event = BarEvent(time=datetime.now(), bars=bars_dict)
		self.strategy.last_event = event

	def test_strategy_instance(self):
		"""
		Test the correct initialization of the Strategy instance.
		"""
		self.assertIsInstance(self.strategy, Strategy)
		self.assertIsInstance(self.strategy.global_queue, Queue)
		self.assertEqual(self.strategy.is_active, True)
		self.assertEqual(self.strategy.order_type, 'market')
		self.assertEqual(self.strategy.subscribed_portfolios, [self.portfolio_name])
		self.assertEqual(self.strategy.tickers, [self.ticker])
	
	def test_buy_signal(self):
		"""
		Generate a BUY signal with the 'buy()' method of the Strategy object.
		"""
		# Buy 1 of BTC over one transactions
		self.strategy.buy('SOLUSDT', 40, 50)

		# Retrive the signal from the queue
		event: SignalEvent = self.queue.get(False)

		# Assert the event in the queue
		self.assertIsInstance(event, SignalEvent)
		self.assertEqual(event.strategy_id, 1)
		self.assertEqual(event.action, 'BUY')
		self.assertEqual(event.ticker, self.ticker)
		self.assertEqual(event.stop_loss, 40)
		self.assertEqual(event.take_profit, 50)

	def test_sell_signal(self):
		"""
		Generate a SELL signal with the 'buy()' method of the Strategy object.
		"""
		# Buy 1 of BTC over one transactions
		self.strategy.sell('SOLUSDT', 40, 50)

		# Retrive the signal from the queue
		event: SignalEvent = self.queue.get(False)

		# Assert the event in the queue
		self.assertIsInstance(event, SignalEvent)
		self.assertEqual(event.strategy_id, 1)
		self.assertEqual(event.action, 'SELL')
		self.assertEqual(event.ticker, self.ticker)
		self.assertEqual(event.stop_loss, 40)
		self.assertEqual(event.take_profit, 50)



if __name__ == "__main__":
	unittest.main()