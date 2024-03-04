import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.portfolio_handler.portfolio import Portfolio, Position, PositionSide
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.events_handler.event import SignalEvent,OrderEvent, BarEvent, PortfolioUpdateEvent, FillStatus


class TestOrderHandlerUpdates(unittest.TestCase):
	"""
	Test a order handler object performing different actions
	like create create a new order, manage portfolio updates,
	check pending order and managing the risk of new orders.
	"""

	@classmethod
	def setUpClass(cls):
		"""
		Set up the test data that will be used across all test methods.
		"""
		cls.user_id = 1
		cls.portfolio_name = 'test_ptf'
		cls.strategy_id = 1
		cls.portfolio_id = 1
		cls.cash = 1000
		cls.queue = Queue()
		cls.ptf_handler = PortfolioHandler()
		cls.ptf_handler.add_portfolio(cls.user_id, cls.portfolio_name, cls.cash)
		cls.order_handler = OrderHandler(cls.queue)

	def setUp(self):
		"""
		Set up the Portfolio object that will store the
		collection of Position objects, supplying it with
		$500,000.00 USD in initial cash.
		"""
		buy_signal = SignalEvent(
							time = datetime.utcnow(),
							order_type = 'market',
							ticker = 'BTCUSDT',
							action = 'BUY',
							price = 40,
							quantity = 0,
							stop_loss = 0,
							take_profit = 0,
							strategy_id = self.strategy_id,
							portfolio_id = self.portfolio_id
		)
		sell_signal = SignalEvent(
							time = datetime.utcnow(),
							order_type = 'market',
							ticker = 'BTCUSDT',
							action = 'SELL',
							price = 40,
							quantity = 0,
							stop_loss = 0,
							take_profit = 0,
							strategy_id = self.strategy_id,
							portfolio_id = self.portfolio_id
		)
		self.queue.put(buy_signal)
		# self.queue.put(sell_signal)

	def test_order_handler_initialization(self):
		self.assertIsInstance(self.order_handler, OrderHandler)
	
	def test_on_portfolio_update(self):
		# Generate a portfolio update event and process it from the order handler
		ptf_update = self.ptf_handler.generate_portfolios_update_event()
		self.order_handler.on_portfolio_update(ptf_update)
		
		# Retrive the updated portfolios dict
		portfolio_dict = self.order_handler.portfolios
		portfolio_ids = list(portfolio_dict.keys())
		self.assertIsInstance(portfolio_dict, dict)
		self.assertEqual(len(portfolio_dict), 1)
		self.assertEqual(portfolio_ids, [1])
		self.assertEqual(portfolio_dict.get(1).get('available_cash'), 1000)
	
	def test_on_signal(self):
		# Generate a portfolio update event and process it from the order handler
		ptf_update = self.ptf_handler.generate_portfolios_update_event()
		self.order_handler.on_portfolio_update(ptf_update)
		# Simulate a buy signal
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)

		# Retrive the market order that should have been generated
		order_event = self.queue.get(False)
		
		# Retrive the updated portfolios dict
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')


if __name__ == "__main__":
	unittest.main()