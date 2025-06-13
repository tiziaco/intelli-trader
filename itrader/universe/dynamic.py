from itrader.universe.universe import Universe
from ..events_handler.event import BarEvent

from itrader.logger import get_itrader_logger

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

		self.logger = get_itrader_logger().bind(component="DynamicUniverse")
		self.logger.info('Dynamic Universe initialized')

	@property
	def universe(self):
		"""
		Return the universe coming from both screeners and strategies.
		"""
		return list(set(self.strategies_universe + self.screeners_universe))
	
	def init_universe(self, strategies_universe:list, screeners_universe:list):
		self.strategies_universe = strategies_universe
		self.screeners_universe = screeners_universe

	def get_full_universe(self):
		"""
		Obtain the list of assets in the Universe. 
		This will always return a static list.

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
		bars = {}

		for ticker in self.strategies_universe:
			if ticker in self.price_handler.prices.keys():
				bar = self.price_handler.get_bar(ticker, ping_event.time)
				bars[ticker] = bar
			else:
				self.logger.warning('Dynamic Universe: ticker %s not present in the price handler', ticker)

		bar_event = BarEvent(ping_event.time, bars)
		self.last_bar = bar_event

		if self.global_queue is not None:
			self.global_queue.put(bar_event)
		else:
			return bar_event

