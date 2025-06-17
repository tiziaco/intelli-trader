import unittest
from datetime import datetime
from itrader.events_handler.event import EventType, FillStatus
from itrader.order_handler.order import OrderType, OrderStatus
from itrader.events_handler.event import \
	PingEvent, BarEvent, SignalEvent, OrderEvent, FillEvent


class TestEvents(unittest.TestCase):
	"""
	Test all the events that can be handled by the trading system.
	"""

	@classmethod
	def setUpClass(cls):
		"""
		Set up the test data that will be used across all test methods.
		"""
		cls.time = datetime.now()
		cls.ticker = 'BTCUSDT'
		cls.side = 'LONG'
		cls.action = 'BUY'
		cls.price = 42350.72
		cls.quantity = 1
		cls.commission = 1.5
		cls.stop_loss = 42000
		cls.take_profit = 45000
		cls.strategy_id = 'test_strategy'
		cls.portfolio_id = 'portfolio_id'
		cls.order_type = 'MARKET'

	def setUp(self):
		"""
		Set up the test data that will be used in each test method.
		"""
		self.ping_event = PingEvent(self.time)
		self.bar_event = BarEvent(self.time, {})
		self.signal_event = SignalEvent(self.time, self.order_type, self.ticker, self.side, self.action,
										self.price, self.quantity, self.stop_loss, self.take_profit,
										self.strategy_id, self.portfolio_id)
		self.mkt_order_event = OrderEvent.new_order(self.signal_event)
		self.fill_event = FillEvent.new_fill('EXECUTED', self.commission, self.mkt_order_event)

	def test_ping_event_initialization(self):
		self.assertIsInstance(self.ping_event, PingEvent)

	def test_bar_event_initialization(self):
		self.assertIsInstance(self.bar_event, BarEvent)

	def test_signal_event_initialization(self):
		self.assertIsInstance(self.signal_event, SignalEvent)
		self.assertIs(type(self.mkt_order_event.time), datetime)
		self.assertEqual(self.signal_event.ticker, 'BTCUSDT')
		self.assertEqual(self.signal_event.side, 'LONG')
		self.assertEqual(self.signal_event.action, 'BUY')
		self.assertEqual(self.signal_event.price, 42350.72)
		self.assertEqual(self.signal_event.quantity, 1)
		self.assertEqual(self.signal_event.stop_loss, 42000)
		self.assertEqual(self.signal_event.take_profit, 45000)
		self.assertEqual(self.signal_event.strategy_id, 'test_strategy')
		self.assertEqual(self.signal_event.portfolio_id, 'portfolio_id')
		self.assertEqual(self.signal_event.verified, False)

	def test_order_event_initialization(self):
		self.assertIsInstance(self.mkt_order_event, OrderEvent)
		self.assertIs(type(self.mkt_order_event.time), datetime)
		self.assertEqual(self.mkt_order_event.order_type, OrderType.MARKET)
		self.assertEqual(self.mkt_order_event.status, OrderStatus.PENDING)
		self.assertEqual(self.mkt_order_event.ticker, 'BTCUSDT')
		self.assertEqual(self.mkt_order_event.side, 'LONG')
		self.assertEqual(self.mkt_order_event.action, 'BUY')
		self.assertEqual(self.mkt_order_event.price, 42350.72)
		self.assertEqual(self.mkt_order_event.quantity, 1)
		self.assertEqual(self.mkt_order_event.strategy_id, 'test_strategy')
		self.assertEqual(self.mkt_order_event.portfolio_id, 'portfolio_id')

	def test_fill_event_initialization(self):
		self.assertIsInstance(self.fill_event, FillEvent)
		self.assertIs(type(self.mkt_order_event.time), datetime)
		self.assertEqual(self.fill_event.status, FillStatus.EXECUTED)
		self.assertEqual(self.fill_event.ticker, 'BTCUSDT')
		self.assertEqual(self.fill_event.side, 'LONG')
		self.assertEqual(self.fill_event.action, 'BUY')
		self.assertEqual(self.fill_event.price, 42350.72)
		self.assertEqual(self.fill_event.quantity, 1)
		self.assertEqual(self.fill_event.commission, 1.5)
		self.assertEqual(self.fill_event.portfolio_id, 'portfolio_id')


if __name__ == "__main__":
	unittest.main()