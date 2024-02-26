from ..base import OrderBase
from itrader.events_handler.event import SignalEvent

from itrader import logger

class DynamicSizer(OrderBase):
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
	def __init__(self, integer_size=False):
		self.integer_size = integer_size #define only integer sizes
		self.max_allocation = None
		self.max_positions = None

		logger.info('   POSITION SIZER: Dynamic Sizer => OK')
	

	def size_order(self, signal: SignalEvent):#TODO: portfolio_id da parametrizzare
		"""
		Calculate the size of the order (80% of the available cash).
		"""
		if not signal.verified:
			signal.quantity = 0
			return

		ticker = signal.ticker
		portfolio_id = signal.portfolio_id
		self.max_positions=self.strategies_setting[signal.strategy_id]['max_positions']
		self.max_allocation=self.strategies_setting[signal.strategy_id]['max_allocation']

		if ticker in self.open_positions[portfolio_id].keys():
			# The position is already open and will be closed, assign 100% of the quantity
			quantity = self.open_positions[portfolio_id][ticker]['quantity']
			quantity = round(quantity, 5)
		else:
			# New position, assign 80% of the cash
			cash = self.cash[portfolio_id]
			last_price = signal.price

			available_pos = (self.max_positions-len(self.open_positions[portfolio_id].keys()))
			quantity = (cash * (self.max_allocation * (1 / available_pos))) / last_price

		# Define or not an integer value for the position size
		if self.integer_size:
			quantity = int(quantity)
		
		# Assign the calculated size to the ordr event
		signal.quantity = round(quantity,5)
		logger.info('  POSITION SIZER: Order sized %s %s', signal.quantity, signal.ticker)
