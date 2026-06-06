from itrader.events_handler.events import SignalEvent
from typing import cast

from itrader.core.ids import PortfolioId
from itrader.core.portfolio_read_model import PortfolioReadModel

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

	def __init__(self, portfolio_handler: PortfolioReadModel) -> None:
		# D-17: the risk manager is part of the admission path — it reads
		# through the narrow PortfolioReadModel Protocol (D-16, structural).
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
		# 02-05 carry-over: events declare portfolio_id as int; runtime is UUID.
		portfolio_id = cast(PortfolioId, signal.portfolio_id)

		# Extract scalar values from signal attributes (an unsized signal —
		# quantity None, D-10 — carries no cost yet). D-22: signal money is
		# Decimal — coerce at this float risk-check boundary.
		quantity = float(signal.quantity) if signal.quantity is not None else 0.0
		price = float(signal.price)

		cost = quantity * price

		# Per-ticker membership composes from get_position (OQ1, D-15).
		if self.portfolio_handler.get_position(portfolio_id, signal.ticker) is None:
			# New position about to be opened. Check if enough cash.
			# Risk checks stay float-domain until M4 (locked decision); coerce
			# the Decimal cash at this boundary so the comparison does not mix
			# types. available_cash is the single trading-decision figure
			# (D-14; available == total until 05-06 wires reservations).
			cash = float(self.portfolio_handler.available_cash(portfolio_id))

			if cash < 30 or cash <= cost:
				self.logger.info('Order REFUSED: Not enough cash to trade')
				return False
		return True

