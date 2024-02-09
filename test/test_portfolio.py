import unittest

from itrader.portfolio_handler.portfolio import Portfolio


class TestPortfolio(unittest.TestCase):
	"""
	Test a portfolio object performing the different actions
	like create a portfolio, process a transaction, update 
	its market value.
	"""

	def setUp(self):
		"""
		Set up the Portfolio object that will store the
		collection of Position objects, supplying it with
		$500,000.00 USD in initial cash.
		"""

		self.portfolio = Portfolio('test_user', 'test_pf', 10000, '2024-02-10')

	def test_calculate_round_trip(self):
		"""
		Purchase/sell multiple lots of BTC and ETH
		at various prices/commissions to check the
		logic handling of the portfolio.
		"""
		# Buy 300 of AMZN over two transactions
		self.portfolio.transact_position(
			"BOT", "AMZN", 100, 566.56, 1.00)

		self.portfolio.transact_position(
			"BOT", "AMZN", 200, 566.395, 1.00)

		# Buy 200 GOOG over one transaction
		self.portfolio.transact_position(
			"BOT", "GOOG", 200, 707.50, 1.00)

		# Add to the AMZN position by 100 shares
		self.portfolio.transact_position(
			"SLD", "AMZN", 100, 565.83, 1.00)

		# Add to the GOOG position by 200 shares
		self.portfolio.transact_position(
			"BOT", "GOOG", 200, 705.545, 1.00)

		# Sell 200 of the AMZN shares
		self.portfolio.transact_position(
			"SLD", "AMZN", 200, 565.59, 1.00)

		# Multiple transactions bundled into one (in IB)
		# Sell 300 GOOG from the portfolio
		self.portfolio.transact_position(
			"SLD", "GOOG", 100, 704.92, 1.00)

		self.portfolio.transact_position(
			"SLD", "GOOG", 100, 704.90, 0.00)

		self.portfolio.transact_position(
			"SLD", "GOOG", 100, 704.92, 0.50)
		
		# Finally, sell the remaining GOOG 100 shares
		self.portfolio.transact_position(
			"SLD", "GOOG", 100, 704.78, 1.00)

		# Assert the result after processing the transactions
		self.assertEqual(len(self.portfolio.positions), 0)
		self.assertEqual(len(self.portfolio.closed_positions), 2)
		self.assertEqual(self.portfolio.cur_cash, 499100.50)
		self.assertEqual(self.portfolio.equity, 499100.50)
		self.assertEqual(self.portfolio.unrealised_pnl, 0.00)
		self.assertEqual(self.portfolio.realised_pnl, -899.50)


if __name__ == "__main__":
	unittest.main()