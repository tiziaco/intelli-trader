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

	def __init__(self, portfolio_handler: PortfolioHandler) -> None:
		self.portfolio_handler = portfolio_handler

		self.logger = get_itrader_logger().bind(component="RiskManager")
		self.logger.info('Risk Manager initialized')


	def refine_orders(self, signal: SignalEvent) -> bool:
		"""
		Run the risk checks for the signal and return the typed verdict.

		The signal is never mutated (D-03): the boolean return IS the
		verdict — there is no ``verified`` flag on the event anymore.
		"""
		if self.check_cash(signal):
			self.logger.debug('Order VALIDATED')
			return True
		return False

	def check_cash(self, signal: SignalEvent) -> bool:
		"""
		Check if enough cash in the selected portfolio.

		Returns True when the portfolio can fund the signal; the verdict is
		returned, never written onto the signal (D-03).
		"""
		# TODO: implement check cash in case of position increase
		portfolio_id = signal.portfolio_id
		portfolio = self.portfolio_handler.get_portfolio(portfolio_id)
		open_tickers = list(portfolio.positions.keys())

		# Extract scalar values from signal attributes (an unsized signal —
		# quantity None, D-10 — carries no cost yet).
		quantity = signal.quantity if signal.quantity is not None else 0.0
		price = signal.price

		cost = quantity * price

		if signal.ticker not in open_tickers:
			# New position about to be opened. Check if enough cash.
			# Risk checks stay float-domain until M4 (locked decision); coerce the
			# Decimal cash at this boundary so the comparison does not mix types.
			cash = float(portfolio.cash)

			if cash < 30 or cash <= cost:
				self.logger.info('Order REFUSED: Not enough cash to trade')
				return False
		return True

