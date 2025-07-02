import unittest
from datetime import datetime

from itrader.portfolio_handler.portfolio import Portfolio
from itrader.portfolio_handler.transaction import Transaction, TransactionType
from itrader import idgen


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
		cls.exchange = 'simulated'
		cls.cash = 150000

	def setUp(self):
		"""
		Initialise a portfolio object.
		"""

		self.portfolio = Portfolio(self.user_id, self.portfolio_name, self.exchange, self.cash, datetime.now())

	def test_long_position(self):
		"""
		Purchase/sell multiple lots of BTC and ETH
		at various prices/commissions to check the
		logic handling of the portfolio.
		"""
		# Buy 1 of BTC over one transactions
		buy_txn = Transaction(datetime.now(), TransactionType.BUY,
							'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn)

		# Sell 1 of BTC over one transactions
		sell_txn = Transaction(datetime.now(), TransactionType.SELL,
							'BTCUSDT', 42000, 1, 0, None, idgen.generate_transaction_id())
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
							'BTCUSDT', 42000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn)

		# Buy 1 of BTC over one transactions
		buy_txn = Transaction(datetime.now(), TransactionType.BUY,
							'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)
		self.assertEqual(len(self.portfolio.closed_positions), 1)
		self.assertEqual(self.portfolio.cash, 152000)
		self.assertEqual(self.portfolio.total_equity, 152000)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)
	
	def test_multiple_buys_followed_by_sell(self):
		# Buy 2 units of BTC at $38000
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn1)

		# Buy 1 unit of BTC at $40000
		buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn2)

		# Sell 1 unit of BTC at $45000
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 45000, 3, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # No position remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 169000)  # Cash after transactions
		self.assertEqual(self.portfolio.total_equity, 169000)  # Total equity after transactions
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)  # Total unrealized P&L
		self.assertAlmostEqual(self.portfolio.total_realised_pnl, 19000, 2)  # Total realized P&L

	def test_sell_followed_by_multiple_buys(self):
		# Sell 3 unit of BTC at $45000
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 45000, 3, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn)

		# Buy 1 units of BTC at $40000
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn1)

		# Buy 2 unit of BTC at $38000
		buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn2)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # No positions remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 169000)  # Cash after transactions
		self.assertEqual(self.portfolio.total_equity, 169000)  # Total equity after transactions
		self.assertEqual(self.portfolio.total_unrealised_pnl, 0)  # Total unrealized P&L
		self.assertAlmostEqual(self.portfolio.total_realised_pnl, 19000, 2)  # Total realized P&L

	def test_transaction_with_commission(self):

		# Buy 2 units of BTC at $38000 with $100 commission
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 100, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn1)

		# Sell 2 units of BTC at $40000 with $100 commission
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 40000, 2, 100, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # No position remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 154000 - 200)  # Cash after transactions considering commissions
		self.assertEqual(self.portfolio.total_realised_pnl, 4000 - 200)  # Realized P&L after commissions

	def test_partial_closure(self):
	
		# Buy 3 units of BTC at $40000 (total: $120,000 - within $150,000 budget)
		buy_txn = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 3, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn)

		# Sell 2 units of BTC at $45000 (partial closure)
		sell_txn = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 45000, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 1)  # One position remaining
		self.assertEqual(self.portfolio.positions['BTCUSDT'].net_quantity, 1)  # 1 unit remaining
		self.assertEqual(self.portfolio.cash, 150000 - (40000 * 3) + (45000 * 2))  # Cash after transactions
		self.assertEqual(self.portfolio.total_realised_pnl, 10000)  # Realized P&L for the closed portion (2 * $5000)

	def test_multiple_assets(self):
    
		# Buy 1 unit of BTC at $40000
		buy_btc = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_btc)

		# Buy 2 units of ETH at $2500
		buy_eth = Transaction(datetime.now(), TransactionType.BUY, 'ETHUSDT', 2500, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_eth)

		# Sell 1 unit of BTC at $42000
		sell_btc = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 42000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_btc)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 1)  # One position remaining (ETH)
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTC) closed
		self.assertEqual(self.portfolio.positions['ETHUSDT'].net_quantity, 2)  # 2 units of ETH remaining
		self.assertEqual(self.portfolio.cash, 150000 - 40000 + 42000 - 2500 * 2)  # Cash after transactions
		self.assertEqual(self.portfolio.total_realised_pnl, 2000)  # Realized P&L for BTC

	def test_mixed_buy_sell_transactions(self):
		
		# Buy 2 units of BTC at $38000
		buy_txn1 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 38000, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn1)

		# Sell 1 unit of BTC at $40000
		sell_txn1 = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 40000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn1)

		# Buy 1 unit of BTC at $37000
		buy_txn2 = Transaction(datetime.now(), TransactionType.BUY, 'BTCUSDT', 37000, 1, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(buy_txn2)

		# Sell 2 units of BTC at $39000
		sell_txn2 = Transaction(datetime.now(), TransactionType.SELL, 'BTCUSDT', 39000, 2, 0, None, idgen.generate_transaction_id())
		self.portfolio.process_transaction(sell_txn2)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)  # No position remaining
		self.assertEqual(len(self.portfolio.closed_positions), 1)  # One position (BTCUSDT) closed
		self.assertEqual(self.portfolio.cash, 155000)  # Cash after transactions
		self.assertAlmostEqual(self.portfolio.total_realised_pnl, 5000, 2)  # Realized P&L


if __name__ == "__main__":
	unittest.main()