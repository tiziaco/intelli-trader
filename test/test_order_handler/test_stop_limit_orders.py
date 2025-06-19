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
		cls.exchange = 'default'  # Changed from 'simulated' to 'default'
		cls.strategy_id = 1
		cls.portfolio_id = 1
		cls.cash = 10000  # Increased from 1000 to handle larger orders
		# Init global queue
		cls.queue = Queue()
		# Init Portfolio Handler
		cls.ptf_handler = PortfolioHandler(cls.queue)
		# Init Order Storage (In-Memory for testing)
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
		
		# Create mock bar event for testing
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [40], 'volume': [1000]}),
		}
		self.bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		
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
		self.assertEqual(len(portfolio_orders), 2)

	def test_on_signal_sell_with_sl_tp(self):
		# Create a mock sell signal with stop loss and take profit
		sell_signal = self.create_mock_signal('SELL', quantity=50.0, price=40.0, stop_loss=50.0, take_profit=30.0)
		
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
		self.assertEqual(len(portfolio_orders), 2)
		self.assertIsInstance(pending_orders, dict)
		self.assertEqual(len(portfolio_orders), 2)
	
	def test_fill_stop_loss_order_long(self):
		# Define Bar Event at a lower price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [20], 'volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		
		# Create a mock buy signal with stop loss
		buy_signal = self.create_mock_signal('BUY', quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(buy_signal)
		
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrieve the market orders that should have been generated
		order_event1: OrderEvent = self.queue.get(False)  # Initial buy order
		order_event2: OrderEvent = self.queue.get(False)  # Stop loss triggered order
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event2.portfolio_id), {})

		# Assert Order Event from queue (stop loss sell order)
		self.assertIsInstance(order_event2, OrderEvent)
		self.assertEqual(order_event2.ticker, 'BTCUSDT')
		self.assertEqual(order_event2.action, 'SELL')
		self.assertEqual(order_event2.price, 30.0)
		# Assert pending orders (stop loss triggered, so should be empty or reduced)
		self.assertEqual(len(portfolio_orders), 0)
	
	def test_fill_stop_loss_order_short(self):
		# Define Bar Event at a higher price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [55], 'volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		
		# Create a mock sell signal with stop loss
		sell_signal = self.create_mock_signal('SELL', quantity=50.0, price=40.0, stop_loss=50.0, take_profit=20.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(sell_signal)
		
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrieve the market orders that should have been generated
		order_event1: OrderEvent = self.queue.get(False)  # Initial sell order
		order_event2: OrderEvent = self.queue.get(False)  # Stop loss triggered order
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event2.portfolio_id), {})

		# Assert Order Event from queue (stop loss buy order)
		self.assertIsInstance(order_event2, OrderEvent)
		self.assertEqual(order_event2.ticker, 'BTCUSDT')
		self.assertEqual(order_event2.action, 'BUY')
		self.assertEqual(order_event2.price, 50.0)
		# Assert pending orders (stop loss triggered, so should be empty or reduced)
		self.assertEqual(len(portfolio_orders), 0)
	
	def test_fill_take_profit_order_long(self):
		# Define Bar Event at a higher price than the take profit
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [60], 'volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		
		# Create a mock buy signal with take profit
		buy_signal = self.create_mock_signal('BUY', quantity=100.0, price=40.0, stop_loss=30.0, take_profit=50.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(buy_signal)
		
		# Check if take profit order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrieve the market orders that should have been generated
		order_event1: OrderEvent = self.queue.get(False)  # Initial buy order
		order_event2: OrderEvent = self.queue.get(False)  # Take profit triggered order
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event2.portfolio_id), {})

		# Assert Order Event from queue (take profit sell order)
		self.assertIsInstance(order_event2, OrderEvent)
		self.assertEqual(order_event2.ticker, 'BTCUSDT')
		self.assertEqual(order_event2.action, 'SELL')
		self.assertEqual(order_event2.price, 50.0)
		# Assert pending orders (take profit triggered, so should be empty or reduced)
		self.assertEqual(len(portfolio_orders), 0)
	
	def test_fill_take_profit_order_short(self):
		# Define Bar Event at a lower price than the take profit
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [15], 'volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		
		# Create a mock sell signal with take profit
		sell_signal = self.create_mock_signal('SELL', quantity=50.0, price=40.0, stop_loss=50.0, take_profit=20.0)
		
		# Process the signal through the order handler
		self.order_handler.on_signal(sell_signal)
		
		# Check if take profit order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrieve the market orders that should have been generated
		order_event1: OrderEvent = self.queue.get(False)  # Initial sell order
		order_event2: OrderEvent = self.queue.get(False)  # Take profit triggered order
		pending_orders = self.order_handler.order_storage.get_pending_orders()
		portfolio_orders = pending_orders.get(str(order_event2.portfolio_id), {})

		# Assert Order Event from queue (take profit buy order)
		self.assertIsInstance(order_event2, OrderEvent)
		self.assertEqual(order_event2.ticker, 'BTCUSDT')
		self.assertEqual(order_event2.action, 'BUY')
		self.assertEqual(order_event2.price, 20.0)
		# Assert pending orders (take profit triggered, so should be empty or reduced)
		self.assertEqual(len(portfolio_orders), 0)
		self.assertEqual(len(portfolio_orders), 0)

if __name__ == "__main__":
	unittest.main()