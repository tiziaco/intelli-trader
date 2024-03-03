import unittest
from datetime import datetime

from itrader.portfolio_handler.portfolio import Portfolio, Position, PositionSide
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import FillEvent, FillStatus


class TestPortfolioHandler(unittest.TestCase):
	"""
	Test a portfolio handler object performing different actions
	like create a portfolio, process a signal, update 
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
		self.ptf_handler = PortfolioHandler()
		#self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)
		#self.portfolio = Portfolio(self.user_id, self.portfolio_name, self.cash, datetime.now())

	def test_add_portfolio(self):
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)

		# Assert if the portfolio has been created
		self.assertEqual(len(self.ptf_handler.portfolios), 1)
	
	def test_get_portfolio(self):
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)
		portfolio = self.ptf_handler.get_portfolio(3)

		# Assert if the portfolio has been created
		self.assertIsInstance(portfolio, Portfolio)
		self.assertEqual(portfolio.portfolio_id, 3)
		self.assertEqual(portfolio.name, self.portfolio_name)
		self.assertEqual(portfolio.cash, self.cash)

	def test_buy_fill(self):
		"""
		Simulate a FillEvent recived from the execution handler.
		"""
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)
		# Bought 1 BTC over one filled event from yhe execution handler
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'BUY', 40000, 1, 0, 2)
		self.ptf_handler.on_fill(buy_fill)
		portfolio = self.ptf_handler.get_portfolio(2)
		position = portfolio.positions['BTCUSDT']

		# Assert the portfolio's positions and transactions
		self.assertEqual(len(portfolio.positions), 1)
		self.assertEqual(len(portfolio.closed_positions), 0)
		self.assertEqual(len(portfolio.transactions), 1)
		# Assert the portfolio's metrics
		self.assertEqual(portfolio.cash, 110000)
		self.assertEqual(portfolio.total_equity, 150000)
		self.assertEqual(portfolio.total_market_value, 40000)
		self.assertEqual(portfolio.total_pnl, 0)
		self.assertEqual(portfolio.total_realised_pnl, 0)
		self.assertEqual(portfolio.total_unrealised_pnl, 0)
		# Assert the open position
		self.assertIsInstance(position, Position)
		self.assertEqual(position.ticker, 'BTCUSDT')
		self.assertEqual(position.portfolio_id, 2)
		self.assertEqual(position.is_open, True)
		self.assertEqual(position.side, PositionSide.LONG)

	def test_sell_fill(self):
		"""
		Simulate a FillEvent recived from the execution handler.
		"""
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)
		# Bought 1 BTC over one filled event from yhe execution handler
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'SELL', 40000, 1, 0, 5)
		self.ptf_handler.on_fill(buy_fill)
		portfolio = self.ptf_handler.get_portfolio(5)
		position = portfolio.positions['BTCUSDT']

		# Assert the portfolio's positions and transactions
		self.assertEqual(len(portfolio.positions), 1)
		self.assertEqual(len(portfolio.closed_positions), 0)
		self.assertEqual(len(portfolio.transactions), 1)
		# Assert the portfolio's metrics
		self.assertEqual(portfolio.cash, 110000)
		self.assertEqual(portfolio.total_equity, 150000)
		self.assertEqual(portfolio.total_market_value, 40000)
		self.assertEqual(portfolio.total_pnl, 0)
		self.assertEqual(portfolio.total_realised_pnl, 0)
		self.assertEqual(portfolio.total_unrealised_pnl, 0)
		# Assert the open position
		self.assertIsInstance(position, Position)
		self.assertEqual(position.ticker, 'BTCUSDT')
		self.assertEqual(position.portfolio_id, 5)
		self.assertEqual(position.is_open, True)
		self.assertEqual(position.side, PositionSide.SHORT)

	def test_portfolios_to_dict(self):
		"""
		Simulate a FillEvent recived from the execution handler.
		"""
		self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.cash)
		# Bought 1 BTC over one filled event from yhe execution handler
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'SELL', 40000, 1, 0, 4)
		self.ptf_handler.on_fill(buy_fill)

		portfolios_dict = self.ptf_handler.portfolios_to_dict()

		# Assert the portfolio's dictionary
		self.assertIsInstance(portfolios_dict, dict)
		self.assertEqual(len(portfolios_dict), 1)


if __name__ == "__main__":
	unittest.main()