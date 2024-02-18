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
	def __init__(self, name, timeframe, tickers, settings) -> None:
		self.strategy_id = idgen.generate_strategy_id()
		self.strategy_name = name
		self.timeframe = to_timedelta(timeframe)
		self.tickers = tickers
		self.settings = settings
		self.open_positions = {}
		self.subscribed_portfolio = []
		self.is_active = True
		self.last_event: BarEvent = None
		self.global_queue = None

	def buy(self, ticker: str, sl: float = 0, tp: float = 0):
		"""
		Add a buy signal from the strategy to the global queue 
		of the trading system.
		"""
		for portfolio_id in self.subscribed_portfolio:
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = self.settings.get("order_type"),
							ticker = ticker,
							action = 'BUY',
							price = self.last_event.bars[ticker][-1].close,
							quantity = 0,
							stop_loss = sl,
							take_profit = tp,
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id              
						)
			self.global_queue.put(signal)
		logger.debug('Strategy signal (%s - %s %s,%s $', signal.strategy_id,
					signal.ticker, signal.action, signal.price)
	
	def sell(self, ticker: str, sl: float = 0, tp: float = 0):
		"""
		Add a buy signal from the strategy to the global queue 
		of the trading system.
		"""
		for portfolio_id in self.subscribed_portfolio:
			signal = SignalEvent(
							time = self.last_event.time,
							order_type = self.settings.get("order_type"),
							ticker = ticker,
							action = 'SELL',
							price = self.last_event.bars[ticker][-1].close,
							quantity = 0,
							stop_loss = sl,
							take_profit = tp,
							strategy_id = self.strategy_id,
							portfolio_id = portfolio_id              
						)
			self.global_queue.put(signal)
		logger.debug('Strategy signal (%s - %s %s,%s $', signal.strategy_id,
					signal.ticker, signal.action, signal.price)

