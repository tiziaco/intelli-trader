import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.strategy_handler.base import Strategy
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
		# Init test Portfolio
		cls.user_id = 1
		cls.portfolio_name = 'test_ptf'
		cls.exchange = 'simulated'
		cls.strategy_id = 1
		cls.portfolio_id = 1
		cls.cash = 1000
		# Init global queue
		cls.queue = Queue()
		# Init Portfolio Handler
		cls.ptf_handler = PortfolioHandler()
		# Init Order Handler
		cls.order_handler = OrderHandler(cls.queue)


	def setUp(self):
		"""
		For each test: create a new portfolio, initialise a strategy
		and generate a portfolio update event.
		"""
		# Add new portfolio
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.exchange, self.cash)
		last_ptf_id = list(self.ptf_handler.portfolios.keys())[-1]
		print(f'TEST:: {last_ptf_id}')
		# Init new Strategy
		self.strategy = Strategy('test_strategy', '1h', ['BTCUSDT'],
						  		global_queue=self.queue)
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [40], 'Volume': [1000]}),
			'ETHUSDT': pd.DataFrame(
				{'Open': [20], 'High': [50], 'Low': [10], 'Close': [40], 'Volume': [500]}),
			}
		self.bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		self.strategy.last_event = self.bar_event
		self.strategy.subscribe_portfolio(last_ptf_id)
		# Simulate portfolios update event
		update_event = self.ptf_handler.generate_portfolios_update_event()
		self.order_handler.on_portfolio_update(update_event)
		
	
	def test_on_signal_buy_with_sl_tp(self):
		# Send signal from the strategy to the global queue
		self.strategy.buy('BTCUSDT', sl = 30, tp = 50)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')
		# Assert pending orders
		self.assertIsInstance(pending_orders, dict)
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 2)

	def test_on_signal_sell_with_sl_tp(self):
		# Send signal from the strategy to the global queue
		self.strategy.sell('BTCUSDT', sl = 50, tp = 30)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'SELL')
		# Assert pending orders
		self.assertIsInstance(pending_orders, dict)
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 2)
	
	def test_fill_stop_loss_order_long(self):
		# Define Bar Event at a lower price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [20], 'Volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		# Send signal from the strategy to the global queue
		self.strategy.buy('BTCUSDT', sl = 30, tp = 50)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'SELL')
		self.assertEqual(order_event.price, 30)
		# Assert pending orders
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 0)
	
	def test_fill_stop_loss_order_short(self):
		# Define Bar Event at a lower price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [55], 'Volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		# Send signal from the strategy to the global queue
		self.strategy.sell('BTCUSDT', sl = 50, tp = 20)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')
		self.assertEqual(order_event.price, 50)
		# Assert pending orders
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 0)
	
	def test_fill_take_profit_order_long(self):
		# Define Bar Event at a lower price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [60], 'Volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		# Send signal from the strategy to the global queue
		self.strategy.buy('BTCUSDT', sl = 30, tp = 50)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'SELL')
		self.assertEqual(order_event.price, 50)
		# Assert pending orders
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 0)
	
	def test_fill_take_profit_order_short(self):
		# Define Bar Event at a lower price than the stop loss
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [15], 'Volume': [1000]})
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)
		# Send signal from the strategy to the global queue
		self.strategy.sell('BTCUSDT', sl = 50, tp = 20)
		# Get the signal from the global queue
		buy_signal = self.queue.get(False)
		self.order_handler.on_signal(buy_signal)
		# Check if stop loss order is reached
		self.order_handler.check_pending_orders(bar_event)

		# Retrive the market order that should have been generated
		order_event:OrderEvent = self.queue.get(False)
		order_event:OrderEvent = self.queue.get(False)
		pending_orders = self.order_handler.pending_orders

		# Assert Order Event from queue
		self.assertIsInstance(order_event, OrderEvent)
		self.assertEqual(order_event.ticker, 'BTCUSDT')
		self.assertEqual(order_event.action, 'BUY')
		self.assertEqual(order_event.price, 20)
		# Assert pending orders
		self.assertEqual(len(pending_orders.get(order_event.portfolio_id)), 0)

if __name__ == "__main__":
	unittest.main()