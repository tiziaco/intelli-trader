from datetime import timedelta

from itrader.events_handler.event import SignalEvent, BarEvent
from itrader.outils.time_parser import to_timedelta
from itrader import logger, idgen

class Strategy(object):
	"""
	BaseStrategy is a base class providing an interface for
	all subsequent (inherited) strategy objects.

	The goal of a (derived) Strategy object is to generate Signal
	objects for particular symbols based on the inputs of ticks
	generated from a PriceHandler (derived) object.
	"""
	def __init__(self, name, timeframe, tickers, order_type = "market",
			  	max_positions = 1, max_allocation = 0.80, allow_increase = False,
				global_queue = None) -> None:
		self.strategy_id = idgen.generate_strategy_id()
		self.name = name
		self.is_active = True
		self.timeframe = to_timedelta(timeframe)
		self.tickers = tickers
		self.order_type = order_type
		#self.portfolios = {}
		self.subscribed_portfolios = []
		self.last_event: BarEvent = None
		self.global_queue = global_queue
		# Risk management settings
		self.max_positions = max_positions
		self.max_allocation = max_allocation
		self.allow_increase = allow_increase
	
	def setting_to_dict(self):
		return {
			'max_positions' : self.max_positions,
			'max_allocation' : self.max_allocation,
			'allow_increase' : self.allow_increase,
		}
	
	def to_dict(self):
		return {
			"strategy_id" : self.strategy_id,
			"strategy_name": self.name,
			"subscribed_portfolios" : self.subscribed_portfolios,
			"order_type": self.order_type,
			"is_active" : self.is_active,
			'strategy_setting' : self.setting_to_dict()
		}

	def _generate_signal(self, ticker: str, action: str, sl: float = 0, tp: float = 0):
		"""
		Generate a signal for the given `ticker`, `action`, `stop_loss`, and `take_profit`.
		"""
		last_close = self.last_event.bars[ticker]['Close'].iloc[-1]
		for portfolio_id in self.subscribed_portfolios:
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = self.order_type,
							ticker = ticker,
							action = action,
							price = last_close,
							quantity = 0,
							stop_loss = sl,
							take_profit = tp,
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id,
							strategy_setting=self.setting_to_dict()
						)
			self.global_queue.put(signal)
		logger.debug('Strategy signal (%s - %s %s, %s $)', self.strategy_id,
					ticker, action, round(last_close, 4))

	def buy(self, ticker: str, sl: float = 0, tp: float = 0):
		"""
		Add a buy signal from the strategy to the global queue 
		of the trading system.
		"""
		self._generate_signal(ticker, 'BUY', sl, tp)

	def sell(self, ticker: str, sl: float = 0, tp: float = 0):
		"""
		Add a sell signal from the strategy to the global queue 
		of the trading system.
		"""
		self._generate_signal(ticker, 'SELL', sl, tp)
	
	def subscribe_portfolio(self, portfolio_id:int):
		self.subscribed_portfolios.append(portfolio_id)
	
	def unsubscribe_portfolio(self, portfolio_id:int):
		self.subscribed_portfolios.remove(portfolio_id)
