from abc import ABC, abstractmethod

from itrader.events_handler.event import ScreenerEvent, BarEvent
from itrader.outils.time_parser import to_timedelta
from itrader import logger, idgen

class Screener(object):
	"""
	AbstractScreener is an abstract base class providing an interface for
	all subsequent (inherited) screener handling objects.

	The goal of a (derived) Screener object is to analyse the market and
	propose the most suitable instument to be traded.

	This is designed to work both with historic and live data as
	the Screener object is agnostic to data location.
	"""
	def __init__(self, name, timeframe, frequency, universe,
				global_queue = None) -> None:
		self.screener_id = idgen.generate_screener_id()
		self.name = name
		self.is_active = True
		self.timeframe = to_timedelta(timeframe)
		self.frequency = to_timedelta(frequency) #TODO: da testare
		self.universe = universe
		self.subscribed_strategies = []
		self.last_event: BarEvent = None
		self.global_queue = global_queue

	def to_dict(self):
		return {
			"screener_id" : self.screener_id,
			"screener_name": self.name,
			"is_active" : self.is_active,
		}
	
	def screener_signal(self, tickers: list):
		"""
		Add a buy signal from the strategy to the global queue 
		of the trading system.
		"""
		signal = ScreenerEvent(
					time = self.last_event.time,
					screener_id = self.screener_id,
					screener_name = self.name,
					subscribed_strategies = self.subscribed_strategies,
					tickers = tickers
					)
		self.global_queue.put(signal)
		#logger.debug('Screener signal (%s - %s)', self.screener_id, self.name)
	
	def subscribe_strategy(self, strategy_id: int):
		self.subscribed_strategies.append(strategy_id)
	
	def unsubscribe_strategy(self, strategy_id:int):
		self.subscribed_strategies.remove(strategy_id)
	
	@abstractmethod
	def screen_market():
		logger.warning("SCREENER: please define a screen market method.")