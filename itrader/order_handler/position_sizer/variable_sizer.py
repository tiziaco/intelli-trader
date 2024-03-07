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
		strategy_setting = signal.strategy_setting
		max_positions = strategy_setting.get('max_positions')
		max_allocation = strategy_setting.get('max_allocation')
		open_tickers = list(self.portfolios.get(portfolio_id, {}).get('open_positions', {}).keys())

		if ticker in open_tickers:
			# The position is already open and will be closed, assign 100% of the quantity
			quantity = self.portfolios.get(portfolio_id, {}).get('open_positions', {})[ticker]['quantity']
		else:
			# New position, assign 80% of the cash
			cash = self.portfolios.get(portfolio_id, {}).get('available_cash', 0)
			last_price = signal.price

			available_pos = (max_positions - len(open_tickers))
			quantity = (cash * (max_allocation * (1 / available_pos))) / last_price

		# Define or not an integer value for the position size
		#TODO
		
		# Assign the calculated size to the ordr event
		signal.quantity = round(quantity,5)
		logger.debug('  POSITION SIZER: Order sized %s %s', signal.quantity, signal.ticker)
