from ..base import OrderBase
from itrader.events_handler.event import SignalEvent

from itrader import logger

class ComplianceManager():
	"""
	The Compliance class manage the signal event coming from the 
	strategy class.

	It verify that all the entering rules are compliant with the 
	defined conditions. It verifies if a position is already open 
	and if the number of opened positions in a portfolio reached 
	the defined limit
	"""
	def __init__(self, portfolios = {}):
		self.portfolios = portfolios
		logger.info('   COMPLIANCE MANAGER: Default => OK')

	
	def check_compliance(self, signal: SignalEvent):
		"""
		Check if there's already an opened position in the portfolio
		and if the max. number of positions is reached.

		Parameters
		----------
		signal: `Event object`
			The Signal event generated by a strategy
		"""
		allow_increase = signal.strategy_setting.get('allow_increase')

		if not allow_increase:
			self.check_position_increase(signal)
		if signal.verified:
			self.check_max_open_positions(signal)
		if signal.verified == True:
			logger.debug('  COMPLIANCE: Order validated')

	def check_max_open_positions(self, signal: SignalEvent):
		portfolio_id = signal.portfolio_id
		n_open_positions = self.portfolios.get(portfolio_id, {}).get('n_open_positions', 0)
		max_position = signal.strategy_setting.get('max_positions')

		if (n_open_positions >= max_position):
			signal.verified = False
		if signal.verified == False:
			logger.warning('  COMPLIANCE: Order refused. Max positions reached.')

	def check_position_increase(self, signal: SignalEvent):
		portfolio_id = signal.portfolio_id
		ticker = signal.ticker
		open_positions = self.portfolios.get(portfolio_id, {}).get('open_positions', {})
		position_side = open_positions.get(ticker, {}).get('side', None)
		if (position_side == 'LONG' and signal.action == 'BUY'):
			signal.verified = False
		elif (position_side == 'SHORT' and signal.action == 'SELL'):
			signal.verified = False
		else:
			signal.verified = True
		if signal.verified == False:
			logger.warning('  COMPLIANCE: Order refused. Position increase not allowed.')
