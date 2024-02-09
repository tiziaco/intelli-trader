import unittest
from datetime import datetime
from itrader.events_handler.event import EventType, OrderType
from itrader.events_handler.event import \
	PingEvent, BarEvent, SignalEvent, OrderEvent, FillEvent


class TestEvents(unittest.TestCase):
	"""
	Test all the events that can be handled by the trading system.
	"""

	def setUp(self):
		"""
		Set up the Portfolio object that will store the
		collection of Position objects, supplying it with
		$500,000.00 USD in initial cash.
		"""
		time = datetime.now()
		ticker = 'BTCUSDT'
		side = 'LONG'
		action = 'BUY'
		price = 42350.72
		stop_loss = 42000
		take_profit = 45000
		strategy_id = 'test_strategy'
		portfolio_id = 'portfolio_id'
		order_type = 'MARKET'

		self.ping_event = PingEvent(time)
		self.bar_event = BarEvent(time, {})
		self.signal_event = SignalEvent(time, order_type, ticker, side, action,
								price, stop_loss, take_profit,
								strategy_id, portfolio_id)
		self.mkt_order_event = OrderEvent.new_order(self.signal_event)
		self.fill_event = FillEvent

	def test_ping_event_initialization(self):
		self.assertIsNotNone(self.ping_event)
	
	def test_bar_event_initialization(self):
		self.assertIsNotNone(self.bar_event)
	
	def test_signal_event_initialization(self):
		self.assertIsNotNone(self.signal_event)
		self.assertEqual(self.signal_event.ticker, 'BTCUSDT')
		self.assertEqual(self.signal_event.side, 'LONG')
		self.assertEqual(self.signal_event.action, 'BUY')
		self.assertEqual(self.signal_event.price, 42350.72)
	
	def test_order_event_initialization(self):
		self.assertIsNotNone(self.mkt_order_event)
		# Add more specific assertions here if necessary
	
	def test_fill_event_initialization(self):
		self.assertIsNotNone(self.fill_event)
		# Add more specific assertions here if necessary


if __name__ == "__main__":
	unittest.main()