from ..base import OrderBase
from itrader.events_handler.event import SignalEvent

from itrader import logger

class BasicComplianceManager(OrderBase):
	"""
	The Compliance class manage the signal event coming from the 
	strategy class.

	It verify that all the entering rules are compliant with the 
	defined conditions. It verifies if a position is already open 
	and if the number of opened positions in a portfolio reached 
	the defined limit
	"""
	def __init__(self, long_only = False):
		self.max_position = None
		self.long_only = long_only
		#TODO: allow or not partial buy/sell
		logger.info('   COMPLIANCE MANAGER: Default => OK')


	
	def check_compliance(self, signal: SignalEvent):
		"""
		Check if there's already an opened position in the portfolio
		and if the max. number of positions is reached.

		Parameters
		----------
		signal: `Order object`
			The initial order generated from a signal event
		portfolio_id: `str`
			The portfolio id where to check the compliance
		"""
		portfolio_id = signal.portfolio_id
		self.max_position = self.strategies_setting[signal.strategy_id]['max_positions']

		if signal.ticker in self.open_positions[portfolio_id]:
			if signal.action == self.open_positions[portfolio_id][signal.ticker]['action']:
				signal.verified = False
				logger.warning('COMPLIANCE: Position already opened. Order refused')
				return
		elif (len(self.open_positions[portfolio_id]) >= self.max_position):
			signal.verified = False
			logger.debug('COMPLIANCE: Max. positions reached. Order refused')
			return
		signal.verified = True
		logger.debug('COMPLIANCE: Order validated')
		return
