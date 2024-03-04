import unittest
import pandas as pd
from datetime import datetime

from itrader.portfolio_handler.portfolio import Portfolio, Position, PositionSide
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import FillEvent, BarEvent, PortfolioUpdateEvent, FillStatus


class TestPortfolioHandlerUpdates(unittest.TestCase):
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
		cls.portfolio_name = 'test_ptf'
		cls.cash = 1000
		cls.ptf_handler = PortfolioHandler()
		cls.ptf_handler.add_portfolio(cls.user_id, cls.portfolio_name, cls.cash)

	def setUp(self):
		"""
		Set up the Portfolio object that will store the
		collection of Position objects, supplying it with
		$500,000.00 USD in initial cash.
		"""
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'BUY', 40, 1, 0, 1)
		sell_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'ETHUSDT', 'SELL', 20, 1, 0, 1)
		self.ptf_handler.on_fill(buy_fill)
		#self.ptf_handler.on_fill(sell_fill)

	def test_update_portfolios_market(self):
		# Create a simulated BarEvent
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'Open': [30], 'High': [60], 'Low': [20], 'Close': [50], 'Volume': [1000]}),
			'ETHUSDT': pd.DataFrame(
				{'Open': [20], 'High': [50], 'Low': [10], 'Close': [10], 'Volume': [500]}),
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)

		# Update portfolios market value
		self.ptf_handler.update_portfolios_market_value(bar_event)
		portfolio = self.ptf_handler.get_portfolio(1)

		# Assert if the portfolio has been created
		self.assertEqual(len(self.ptf_handler.portfolios), 1)
		# Assert the portfolio's metrics
		self.assertEqual(portfolio.cash, 960) #TODO: problem with the cash update
		self.assertEqual(portfolio.total_equity, 1030)
		self.assertEqual(portfolio.total_market_value, 80)
		self.assertEqual(portfolio.total_pnl, 0)
		self.assertEqual(portfolio.total_realised_pnl, 0)
		self.assertEqual(portfolio.total_unrealised_pnl, 20)
		#TODO: the short position is not correctly updated. To be fixed!
	
	def test_portfolios_update_event(self):
		update_event = self.ptf_handler.generate_portfolios_update_event()
		portfolios = update_event.portfolios
		portfolios_id = list(portfolios.keys())

		self.assertIsInstance(update_event, PortfolioUpdateEvent)
		self.assertIsInstance(portfolios, dict)
		self.assertEqual(len(portfolios), 1)
		self.assertEqual(portfolios_id, [1])
		# Assert the portfolio's metrics
		self.assertEqual(portfolios.get(1).get('available_cash'), 960)

if __name__ == "__main__":
	unittest.main()