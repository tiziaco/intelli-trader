from itrader.events_handler.events import SignalEvent
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler

from itrader.logger import get_itrader_logger

class DynamicSizer():
	"""
	Size the order according to the cash available in the
	portfolio and the number of positions already opened.

	By default, it assaign 80% of the available cash at 
	each order.

	Parameters
	----------
	integer_size : `boolean`
		Specify if only int size should be calculated
	max_allocation : `float`
		Allocation percentage (default: 80%)
	"""
	def __init__(self, portfolio_handler: PortfolioHandler) -> None:
		self.portfolio_handler = portfolio_handler

		self.logger = get_itrader_logger().bind(component="DynamicSizer")
		self.logger.info('   POSITION SIZER: Dynamic Sizer => OK')


	def size_order(self, signal: SignalEvent) -> float:
		"""
		Calculate the size of the order (80% of the available cash).

		Returns the computed quantity; the signal is never mutated (D-03 —
		signals are immutable strategy facts, the order layer owns sizing).
		"""
		ticker = signal.ticker
		portfolio_id = signal.portfolio_id
		strategy_setting = signal.strategy_setting
		max_positions = int(strategy_setting.get('max_positions') or 1)
		max_allocation = float(strategy_setting.get('max_allocation') or 0.80)
		open_tickers = list(self.portfolio_handler.get_portfolio(portfolio_id).positions.keys())

		quantity: float
		if ticker in open_tickers:
			# The position is already open and will be closed, assign 100% of the quantity
			quantity = float(self.portfolio_handler.get_portfolio(portfolio_id).get_open_position(ticker).net_quantity)
		else:
			# New position, assign 80% of the cash. Sizing stays in float until M4
			# (locked decision); coerce the Decimal cash at this boundary.
			cash = float(self.portfolio_handler.get_portfolio(portfolio_id).cash)
			last_price = signal.price

			available_pos = (max_positions - len(open_tickers))
			quantity = (cash * (max_allocation * (1 / available_pos))) / last_price

		# Define or not an integer value for the position size
		#TODO

		# Return the calculated size (the signal is never mutated, D-03).
		sized_quantity = round(quantity, 5)
		self.logger.debug('Order sized %s %s', sized_quantity, signal.ticker)
		return sized_quantity
