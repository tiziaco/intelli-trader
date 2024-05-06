from itrader.universe.universe import Universe
from ..events_handler.event import BarEvent

import logging
logger = logging.getLogger('TradingSystem')

class DynamicUniverse(Universe):
	"""
	An Asset Universe that allows additions of assets
	beyond a certain datetime.

	TODO: This does not currently support removal of assets
	or sequences of additions/removals.

	Parameters
	----------
	assets : `list[str]`
		List of assets and their entry date.
	"""

	def __init__(self, price_handler, global_queue = None, uni_type = 'static'):
		self.uni_type = uni_type
		self.price_handler = price_handler
		self.global_queue = global_queue
		self.strategies_universe = []
		self.screeners_universe = []
		self.assets = []
		self.last_bar = None

		logger.info('UNIVERSE: %s => OK', self.uni_type)
	
	@property
	def universe(self):
		return list(set(self.strategies_universe + self.screeners_universe))
	
	def init_universe(self, strategies_universe:list, screeners_universe:list):
		self.strategies_universe = strategies_universe
		self.screeners_universe = screeners_universe

	def get_full_universe(self):
		"""
		Obtain the list of assets in the Universe at a particular
		point in time. This will always return a static list
		independent of the timestamp provided.

		Returns
		-------
		`list[str]`
			The list of Asset tickers in the Universe.
		"""
		return self.universe
	
	def generate_bar_event(self, ping_event):
		"""
		Generate a bar event with the last price data of all the 
		traded symbol from the different strategies.

		Parameters
		----------
		ping_event: `Ping event object`
			Ping object with the last closed bar time.
		"""
		bar_event = BarEvent(ping_event.time)

		for ticker in self.assets:
			if ticker in self.price_handler.prices.keys():
				bar = self.price_handler.get_bar(ticker, ping_event.time)
				bar_event.bars[ticker] = {
					'open' : bar.open,
					'high' : bar.high,
					'low' : bar.low,
					'close' : bar.close,
					'volume' : bar.volume
				}
				self.last_bar = bar_event
			else:
				logger.warning('UNIVERSE: ticker %s not present in the price handler', ticker)
		if self.global_queue is not None:
			self.global_queue.put(bar_event)
		else:
			return bar_event

