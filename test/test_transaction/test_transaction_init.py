import unittest
from datetime import datetime

from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader.events_handler.event import \
	SignalEvent, OrderEvent, FillEvent

class TestTransaction(unittest.TestCase):
	"""
	Test a portfolio object performing the different actions
	like create a portfolio, process a transaction, update 
	its market value.
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
		self.signal_event = SignalEvent(self.time, self.order_type, self.ticker, self.side, self.action,
										self.price, self.quantity, self.stop_loss, self.take_profit,
										self.strategy_id, self.portfolio_id)
		self.mkt_order_event = OrderEvent.new_order(self.signal_event)
		self.fill_event = FillEvent.new_fill('EXECUTED', self.commission, self.mkt_order_event)

	def test_transaction_initialization(self):
		transaction = Transaction.new_transaction(self.fill_event)
		
		self.assertIsInstance(transaction, Transaction)
		self.assertEqual(transaction.type, TransactionType.BUY)
		self.assertIs(type(transaction.time), datetime)
		self.assertEqual(transaction.ticker, 'BTCUSDT')
		self.assertEqual(transaction.price, 42350.72)
		self.assertEqual(transaction.quantity, 1)
		self.assertEqual(transaction.portfolio_id, 'portfolio_id')

if __name__ == "__main__":
	unittest.main()