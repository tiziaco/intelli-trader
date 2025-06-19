import unittest
import pandas as pd
from datetime import datetime, UTC
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
		cls.exchange = 'default'  # Changed from 'simulated' to 'default' - supported exchange
		cls.strategy_id = 1
		cls.portfolio_id = 1
		cls.cash = 10000  # Increased from 1000 to handle larger orders
		cls.queue = Queue()
		cls.ptf_handler = PortfolioHandler(cls.queue)
		cls.ptf_handler.add_portfolio(cls.user_id, cls.portfolio_name, cls.exchange, cls.cash)
		cls.order_handler = OrderHandler(cls.queue, cls.ptf_handler)

	def setUp(self):
		"""
		Generate a buy and sell signal and add them to the queue.
		"""
		buy_signal = SignalEvent(
							time = datetime.now(UTC),
							order_type = 'MARKET',
							ticker = 'BTCUSDT',
							action = 'BUY',
							price = 40.0,
							quantity = 100.0,  # Changed from 0 to 100
							stop_loss = 0.0,
							take_profit = 0.0,
							strategy_id = self.strategy_id,
							portfolio_id = self.portfolio_id,
							strategy_setting={}
		)
		sell_signal = SignalEvent(
							time = datetime.now(UTC),
							order_type = 'MARKET',
							ticker = 'BTCUSDT',
							action = 'SELL',
							price = 40.0,
							quantity = 50.0,  # Changed from 0 to 50
							stop_loss = 0.0,
							take_profit = 0.0,
							strategy_id = self.strategy_id,
							portfolio_id = self.portfolio_id,
							strategy_setting={}
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
		actual_portfolio_id = portfolio_ids[0]  # Get the actual portfolio ID
		self.assertIsInstance(portfolio_dict, dict)
		self.assertEqual(len(portfolio_dict), 1)
		self.assertEqual(len(portfolio_ids), 1)  # Check we have exactly one portfolio
		self.assertEqual(portfolio_dict.get(actual_portfolio_id).get('available_cash'), 10000)  # Updated from 1000 to 10000


if __name__ == "__main__":
	unittest.main()