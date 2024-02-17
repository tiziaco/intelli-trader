import unittest
from datetime import datetime

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType


class TestPortfolio(unittest.TestCase):
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
		cls.user_id = 1
		cls.portfolio_name = 'test_pf'
		cls.cash = 150000

	def setUp(self):
		"""
		Set up the Portfolio object that will store the
		collection of Position objects, supplying it with
		$500,000.00 USD in initial cash.
		"""

		self.portfolio = Portfolio(self.user_id, self.portfolio_name, self.cash, datetime.now())

	def test_long_position(self):
		"""
		Purchase/sell multiple lots of BTC and ETH
		at various prices/commissions to check the
		logic handling of the portfolio.
		"""
		# Buy 1 of BTC over one transactions
		buy_txn = Transaction(datetime.now(), TransactionType.BUY,
							'BTCUSDT', 40000, 1, 0, None)
		self.portfolio.process_transaction(buy_txn)

		# Sell 1 of BTC over one transactions
		sell_txn = Transaction(datetime.now(), TransactionType.SELL,
							'BTCUSDT', 42000, 1, 0, None)
		self.portfolio.process_transaction(sell_txn)


		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)
		self.assertEqual(len(self.portfolio.closed_positions), 1)
		self.assertEqual(self.portfolio.cash, 152000)
		self.assertEqual(self.portfolio.total_equity, 152000)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
	
	def test_short_position(self):
		"""
		Purchase/sell multiple lots of BTC and ETH
		at various prices/commissions to check the
		logic handling of the portfolio.
		"""
		# Sell 1 of BTC over one transactions
		sell_txn = Transaction(datetime.now(), TransactionType.SELL,
							'BTCUSDT', 42000, 1, 0, None)
		self.portfolio.process_transaction(sell_txn)

		# Buy 1 of BTC over one transactions
		buy_txn = Transaction(datetime.now(), TransactionType.BUY,
							'BTCUSDT', 40000, 1, 0, None)
		self.portfolio.process_transaction(buy_txn)


		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)
		self.assertEqual(len(self.portfolio.closed_positions), 1)
		self.assertEqual(self.portfolio.cash, 152000)
		self.assertEqual(self.portfolio.total_equity, 152000)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
	
	def test_multiple_buys_followed_by_sell(self):
		# Buy 2 units of AAPL at $150
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 0, None)
		self.portfolio.process_transaction(buy_txn1)

		# Buy 1 unit of BTC at $40000
		buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 1, 0, None)
		self.portfolio.process_transaction(buy_txn2)

		# Sell 1 unit of BTC at $42000
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 45000, 3, 0, None)
		self.portfolio.process_transaction(sell_txn)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # One position (AAPL) remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 169000)  # Cash after transactions
		self.assertEqual(self.portfolio.total_equity, 169000)  # Total equity after transactions
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)  # Total unrealized P&L
		self.assertEqual(self.portfolio.total_realised_pnl, 0)  # Total realized P&L

	def test_sell_followed_by_multiple_buys(self):
		# Sell 1 unit of BTC at $45000
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 45000, 3, 0, None)
		self.portfolio.process_transaction(sell_txn)

		# Buy 1 units of BTC at $40000
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 1, 0, None)
		self.portfolio.process_transaction(buy_txn1)

		# Buy 2 unit of BTC at $38000
		buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 0, None)
		self.portfolio.process_transaction(buy_txn2)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # Two positions (AAPL and BTCUSDT) remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 169000)  # Cash after transactions
		self.assertEqual(self.portfolio.total_equity, 169000)  # Total equity after transactions
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)  # Total unrealized P&L
		self.assertEqual(self.portfolio.total_realised_pnl, 0)  # Total realized P&L


if __name__ == "__main__":
	unittest.main()