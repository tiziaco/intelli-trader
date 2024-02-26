from ..base import OrderBase
from .sltp_models.sltp_models import FixedPercentage
from .sltp_models.sltp_models import Proportional
from .sltp_models.sltp_models import ATRsltp

from itrader.events_handler.event import SignalEvent

from itrader import logger


class RiskManager(OrderBase):
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
	apply_sl : `boolean`
		Specify if apply stop loss
	apply_tp : `boolean`
		Specify if apply take profit
	stop_level : `float`
		Stop level in % (default: 3%)
	"""

	def __init__(self, price_handler):
		self.price_handler = price_handler
		self.apply_sl = None
		self.apply_tp = None
		self.sltp_models = self._initialise_sltp_models()
		self.order_id = 0

		logger.info('   RISK MANAGER: Advanced Risk Manager => OK')


	def refine_orders(self, signal: SignalEvent):
		"""
		Calculate the StopLoss level annd create a OrderEvent.
		"""
		
		### Check if enough cash in the portfolio
		if self.check_cash(signal):
			signal.verified = False
			return
		self.apply_sl = self.strategies_setting[signal.strategy_id]['apply_sl']
		self.apply_tp = self.strategies_setting[signal.strategy_id]['apply_tp']

		### Calculate SL and TP
		if signal.action == 'ENTRY':
			if self.apply_sl:
				sl_setting = self.strategies_setting[signal.strategy_id]['sl_setting']
				# Get bars prices when the sltp model is ATR or probabilistic
				bars = None
				if sl_setting['sl_model'] == 'ATR':
					# Load 100 bars
					start_dt = (signal.time - self.strategies_setting[signal.strategy_id]['tf_delta'] * 100)
					bars = self.price_handler.get_bars(signal.ticker, start_dt, signal.time)
				signal = self.sltp_models[sl_setting['sl_model']].calculate_sl(signal, sl_setting, bars)
			if self.apply_tp:
				tp_setting = self.strategies_setting[signal.strategy_id]['tp_setting']
				bars = None
				if tp_setting['tp_model'] == 'ATR':
					# Load 100 bars
					start_dt = (signal.time - self.strategies_setting[signal.strategy_id]['tf_delta'] * 100)
					bars = self.price_handler.get_bars(signal.ticker, start_dt, signal.time)
				signal = self.sltp_models[tp_setting['tp_model']].calculate_tp(signal, tp_setting, bars)

		logger.info('  RISK MANAGER: Order validated')
		return signal


	def check_cash(self, signal: SignalEvent):
		"""
		Check if enough cash in the selected portfolio.
		If not enough cash the order is refused
		"""
		cash = self.cash[signal.portfolio_id]
		if cash < 30:
			logger.info('  RISK MANAGER: Order REFUSED: Not enough cash to trade')
			return False

	def _initialise_sltp_models(self):
		"""
		Instanciate all the stop loss and take profit models
		in a dictionary.
		"""
		sltp_models = {
			'fixed': FixedPercentage(),
			'proportional': Proportional(),
			'ATR': ATRsltp(),
			'probabilistic': None
		}
		return sltp_models
		
