import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.order_handler import OrderHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.event import OrderEvent, BarEvent, SignalEvent


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
		# Init test Portfolio
		cls.user_id = 1
		cls.portfolio_name = 'test_ptf'
		cls.exchange = 'default'
		cls.strategy_id = 1
		cls.portfolio_id = 1
		cls.cash = 10000  # Increased from 1000 to 10000 to handle larger orders
		# Init global queue
		cls.queue = Queue()
		# Init Portfolio Handler
		cls.ptf_handler = PortfolioHandler(cls.queue)
		# Init Order Storage
		cls.order_storage = OrderStorageFactory.create('test')
		# Init Order Handler
		cls.order_handler = OrderHandler(cls.queue, cls.ptf_handler, cls.order_storage)


	def setUp(self):
		"""
		For each test: create a new portfolio and generate a portfolio update event.
		"""
		# Add new portfolio
		self.last_ptf_id = self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.exchange, self.cash)
		print(f'TEST:: {self.last_ptf_id}')
		
		# Simulate portfolios update event
		update_event = self.ptf_handler.generate_portfolios_update_event()
		self.order_handler.on_portfolio_update(update_event)
	
	def create_mock_signal(self, action, ticker='BTCUSDT', quantity=100.0, price=40.0, 
	                      order_type='MARKET', stop_loss=0.0, take_profit=0.0):
		"""Create a mock signal with proper quantity for testing."""
		return SignalEvent(
			time=datetime.now(),
			order_type=order_type,
			ticker=ticker,
			action=action,
			price=price,
			quantity=quantity,
			stop_loss=stop_loss,
			take_profit=take_profit,
			strategy_id=self.strategy_id,
			portfolio_id=self.last_ptf_id,
			strategy_setting={}
		)
		
	
	def test_on_signal_buy(self):
		# Create a mock buy signal with proper quantity
		buy_signal = self.create_mock_signal('BUY', quantity=100.0, price=40.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(buy_signal)

		# Retrieve the market order that should have been generated
		order_event: OrderEvent = self.queue.get(False)
		
		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')
		self.assertEqual(order_event.quantity, 100.0)
	
	def test_on_signal_sell(self):
		# Create a mock sell signal with proper quantity
		sell_signal = self.create_mock_signal('SELL', quantity=50.0, price=40.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(sell_signal)

		# Retrieve the market order that should have been generated
		order_event: OrderEvent = self.queue.get(False)
		
		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'SELL')
		self.assertEqual(order_event.quantity, 50.0)
	
	def test_on_signal_buy_with_sl_tp(self):
		# Create a mock buy signal with stop loss and take profit
		buy_signal = self.create_mock_signal('BUY', quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(buy_signal)

		# Retrieve the market order that should have been generated
		order_event: OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event.portfolio_id), {})

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')
		self.assertEqual(order_event.quantity, 100.0)
		# Assert pending orders (should have SL and TP orders)
		self.assertIsInstance(pending_orders, dict)
		self.assertEqual(len(portfolio_orders), 2)  # SL and TP orders
		
	def test_on_signal_sell_with_sl_tp(self):
		# Create a mock sell signal with stop loss and take profit
		sell_signal = self.create_mock_signal('SELL', quantity=50.0, price=40.0, stop_loss=30.0, take_profit=50.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(sell_signal)

		# Retrieve the market order that should have been generated
		order_event: OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event.portfolio_id), {})

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'SELL')
		self.assertEqual(order_event.quantity, 50.0)
		# Assert pending orders (should have SL and TP orders)
		self.assertIsInstance(pending_orders, dict)
		self.assertEqual(len(portfolio_orders), 2)  # SL and TP orders


if __name__ == "__main__":
	unittest.main()