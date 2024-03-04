from itrader.events_handler.event import SignalEvent

from itrader import logger

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
	def __init__(self, portfolios = {}):
		self.portfolios = portfolios

		logger.info('   POSITION SIZER: Dynamic Sizer => OK')
	

	def size_order(self, signal: SignalEvent):
		"""
		Calculate the size of the order (80% of the available cash).
		"""
		if not signal.verified:
			signal.quantity = 0
			return

		ticker = signal.ticker
		portfolio_id = signal.portfolio_id
		max_positions = self.portfolios[portfolio_id]['max_positions']
		max_allocation = self.portfolios[portfolio_id]['max_allocation']
		open_tickers = self.portfolios[portfolio_id]['open_positions'].keys()

		if ticker in open_tickers:
			# The position is already open and will be closed, assign 100% of the quantity
			quantity = self.portfolios[portfolio_id]['open_positions'][ticker]['quantity']
		else:
			# New position, assign 80% of the cash
			cash = self.portfolios[portfolio_id]['available_cash']
			last_price = signal.price

			available_pos = (max_positions - len(open_tickers))
			quantity = (cash * (max_allocation * (1 / available_pos))) / last_price

		# Define or not an integer value for the position size
		if signal:
			quantity = int(quantity)
		
		# Assign the calculated size to the ordr event
		signal.quantity = round(quantity,5)
		logger.debug('  POSITION SIZER: Order sized %s %s', signal.quantity, signal.ticker)
