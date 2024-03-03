from itrader.events_handler.event import SignalEvent

from itrader import logger


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

	def __init__(self, portfolios = {}):
		self.portfolios = portfolios

		logger.info('   RISK MANAGER: Risk Manager => OK')


	def refine_orders(self, signal: SignalEvent):
		"""
		Calculate the StopLoss level annd create a OrderEvent.
		"""

		if self.check_cash(signal):
			signal.verified = False
		return signal


	def check_cash(self, signal: SignalEvent):
		"""
		Check if enough cash in the selected portfolio.
		If not enough cash the order is refused
		"""
		cash = self.portfolios[signal.portfolio_id]['cash']
		if cash < 30:
			logger.info('  RISK MANAGER: Order REFUSED: Not enough cash to trade')
			return False
		
