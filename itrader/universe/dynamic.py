import queue
from typing import Optional

from itrader.price_handler.feed.base import BarFeed
from itrader.universe.universe import Universe
from ..events_handler.events import BarEvent, TimeEvent

from itrader.logger import get_itrader_logger

class DynamicUniverse(Universe):
	"""
	An Asset Universe that allows additions of assets
	beyond a certain datetime.

	TODO: This does not currently support removal of assets
	or sequences of additions/removals.

	Parameters
	----------
	feed : `BarFeed`
		The market-data read model the per-tick Bar facts come from (D-15).
	"""

	def __init__(self, feed: BarFeed, global_queue: "Optional[queue.Queue[object]]" = None, uni_type: str = 'static') -> None:
		self.uni_type = uni_type
		self.feed = feed
		self.global_queue = global_queue
		self.strategies_universe: list[str] = []
		self.screeners_universe: list[str] = []
		self.assets: list[str] = []
		self.last_bar: Optional[BarEvent] = None

		self.logger = get_itrader_logger().bind(component="DynamicUniverse")
		self.logger.info('Dynamic Universe initialized')

	@property
	def universe(self) -> list[str]:
		"""
		Return the universe coming from both screeners and strategies.
		"""
		return list(set(self.strategies_universe + self.screeners_universe))

	def init_universe(self, strategies_universe: list[str], screeners_universe: list[str]) -> None:
		self.strategies_universe = strategies_universe
		self.screeners_universe = screeners_universe

	def get_full_universe(self) -> list[str]:
		"""
		Obtain the list of assets in the Universe. 
		This will always return a static list.

		Returns
		-------
		`list[str]`
			The list of Asset tickers in the Universe.
		"""
		return self.universe
	
	def generate_bar_event(self, time_event: TimeEvent) -> Optional[BarEvent]:
		"""
		Generate a bar event with the last price data of all the
		traded symbol from the different strategies.

		Parameters
		----------
		time_event: `TimeEvent`
			Simulation-clock event carrying the last closed bar time.
		"""
		# Per-tick fact lookup (D-15): the feed returns the Bar facts stamped
		# exactly at the tick; tickers with no bar at this time are ABSENT
		# from the dict (sparse universe). The bare-except -> None accessor
		# path is gone — store/feed accessors raise loudly (FR7, T-06-19).
		bars = self.feed.current_bars(time_event.time)

		for ticker in self.strategies_universe:
			if ticker not in bars:
				self.logger.warning('Dynamic Universe: no bar for ticker %s at %s in the feed', ticker, str(time_event.time))

		bar_event = BarEvent(time=time_event.time, bars=bars)
		self.last_bar = bar_event

		if self.global_queue is not None:
			self.global_queue.put(bar_event)
			return None
		else:
			return bar_event

