from queue import Queue
import unittest
from datetime import datetime, UTC


from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.events_handler.event import SignalEvent


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


if __name__ == "__main__":
	unittest.main()