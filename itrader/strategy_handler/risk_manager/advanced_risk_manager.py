from itrader.events_handler.event import SignalEvent
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler

from itrader.logger import get_itrader_logger


class RiskManager():
	"""
	This RiskManager class performs different operations on the suggested order:
		- Check if the position is already opened
		- Check available cash
		- Check max position per portfolio
		- Calculate the StopLoss price
		- Calculate the TakeProfit price
	If the order is validated it is sended back to the order manager.

	Parameters
	----------
	portfolios : `dict`
		Portfolio metrics and open positions data
	"""

	def __init__(self, portfolio_handler: PortfolioHandler):
		self.portfolio_handler = portfolio_handler

		self.logger = get_itrader_logger().bind(component="RiskManager")
		self.logger.info('Risk Manager initialized')


	def refine_orders(self, signal: SignalEvent):
		"""
		Calculate the StopLoss level annd create a OrderEvent.
		"""
		if not signal.verified:
			return
		self.check_cash(signal)
		if signal.verified == True:
			self.logger.debug('Order VALIDATED')

	def check_cash(self, signal: SignalEvent):
		"""
		Check if enough cash in the selected portfolio.
		If not enough cash the signal is not verified.
		"""
		# TODO: implement check cash in case of position increase
		portfolio_id = signal.portfolio_id
		portfolio = self.portfolio_handler.get_portfolio(portfolio_id)
		open_tickers = list(portfolio.positions.keys())
		
		# Extract scalar values from signal attributes
		quantity = signal.quantity
		price = signal.price
			
		cost = quantity * price
		
		if signal.ticker not in open_tickers:
			# New position about to be opened. Check if enough cash
			cash = portfolio.cash
			
			if cash < 30 or cash <= cost:
				signal.verified = False
		if signal.verified == False:
			self.logger.info('Order REFUSED: Not enough cash to trade')

