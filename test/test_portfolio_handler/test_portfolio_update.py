import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

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
		cls.exchange = 'simulated'
		cls.cash = 1000

	def setUp(self):
		"""
		Initialise the Portfolio Handler and add a new portfolio.
		"""
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.portfolio_id = self.ptf_handler.add_portfolio(self.user_id, self.portfolio_name, self.exchange, self.cash)

	def test_update_portfolios_market(self):
		# Open 2 positions, 1 long and 1 short
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'BUY', 40, 1, 0, self.portfolio_id)
		sell_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'ETHUSDT', 'SELL', 20, 1, 0, self.portfolio_id)
		self.ptf_handler.on_fill(buy_fill)
		self.ptf_handler.on_fill(sell_fill)
		# Create a simulated BarEvent
		bars_dict = {
			'BTCUSDT': pd.DataFrame(
				{'open': [30], 'high': [60], 'low': [20], 'close': [50], 'volume': [1000]}),
			'ETHUSDT': pd.DataFrame(
				{'open': [20], 'high': [50], 'low': [10], 'close': [40], 'volume': [500]}),
			}
		bar_event = BarEvent(time=datetime.now(), bars=bars_dict)

		# Update portfolios market value
		self.ptf_handler.update_portfolios_market_value(bar_event)
		portfolio = self.ptf_handler.get_portfolio(self.portfolio_id)

		# Assert if the portfolio has been created
		self.assertEqual(self.ptf_handler.get_portfolio_count(), 1)
		# Assert the portfolio's metrics - Updated to reflect correct financial logic
		self.assertEqual(portfolio.cash, 980)  # $1000 - $40 (BTC buy) + $20 (ETH short) = $980
		self.assertEqual(portfolio.total_market_value, 10)  # BTC: $50 (long), ETH: -$40 (short) = $10
		self.assertEqual(portfolio.total_equity, 990)  # $980 cash + $10 market value = $990
		self.assertEqual(portfolio.total_pnl, -10)  # Total P&L
		self.assertEqual(portfolio.total_realised_pnl, 0)
		self.assertEqual(portfolio.total_unrealised_pnl, -10)  # BTC: +$10, ETH: -$20 = -$10
		#TODO: the short position is not correctly updated. To be fixed!
	
	def test_generate_portfolios_update_event(self):
		# Open 1 long positions
		buy_fill = FillEvent(datetime.now(), FillStatus.EXECUTED,
							'BTCUSDT', 'BUY', 40, 1, 0, self.portfolio_id)
		self.ptf_handler.on_fill(buy_fill)

		update_event = self.ptf_handler.generate_portfolios_update_event()
		portfolios = update_event.portfolios
		portfolios_id = list(portfolios.keys())

		self.assertIsInstance(update_event, PortfolioUpdateEvent)
		self.assertIsInstance(portfolios, dict)
		self.assertEqual(len(portfolios), 1)
		self.assertEqual(portfolios_id, [str(self.portfolio_id)])
		# Assert the portfolio's metrics
		self.assertEqual(portfolios.get(str(self.portfolio_id)).get('available_cash'), 960)

if __name__ == "__main__":
	unittest.main()