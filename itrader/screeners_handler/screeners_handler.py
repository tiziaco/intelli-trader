from datetime import timedelta
from queue import Queue
import pytz

from itrader.price_handler.data_provider import PriceHandler
from itrader.screeners_handler.screeners.base import Screener
from itrader.events_handler.event import BarEvent
from itrader.outils.time_parser import check_timeframe

from itrader import logger


class ScreenersHandler(object):
	"""
	Manage all the screeners of the trading system.
	"""

	def __init__(self, global_queue, price_handler):
		"""
		Parameters
		----------
		events_queue: `Queue object`
			The events queue of the trading system
		"""
		self.global_queue: Queue = global_queue
		self.price_handler: PriceHandler = price_handler
		self.min_timeframe: timedelta = timedelta(weeks=100)
		self.screeners: list[Screener]= []

		logger.info('SCREENER HANDLER: Default => OK')

	def screen_markets(self, event: BarEvent):
		"""
		Calculate the signal for every strategy to be traded.

		Before generating the signal check if the actual time 
		is a multiple of the strategy's timeframe.

		Also, it get the prices data from the PriceHandler and 
		resample them according to the strategy's timeframe.

		Parameters
		----------
		event: `BarEvent object`
			The bar event of the trading system
		"""
		for screener in self.screeners:
			
			# Check if the screener's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, screener.frequency):
				continue

			# Screen the market with all active screeners
			proposed = screener.screen_market(
				self.price_handler.to_megaframe(event.time, screener.timeframe, screener.max_window),
				event
			)
			self.last_results = {event.time : proposed}

			logger.info('SCREENER HANDLER: Screener updated - %s', screener.name)
			# Print the new proposed symbols
			if proposed:
				logger.info('   Proposed symbols: ' + str(proposed))

	def add_screener(self, screener: Screener):
		"""
		Add a new screener in the list of screeners.
		At the same time, calculate the minimum timeframe among 
		the different screeners to be applied. 
		This timeframe will be used from the price handler to 
		download historical prices.

		Parameters
		----------
		screener: `Screener object`
			Screener to be applied to the system's assets
		"""
		# Add the strategy in the strategies list
		screener.global_queue = self.global_queue
		self.screeners.append(screener)

		# Find the minimum timeframe
		self.min_timeframe = min([self.min_timeframe, screener.timeframe])

		logger.info(f'SCREENER HANDLER: New screener added: {screener.name}')

	def get_screeners_universe(self):
		"""
		Return the list with the universe to be screened
		"""
		screener_universe = []
		for screener in self.screeners:
			screener_universe += screener.universe
		unique_assetts = list(set(screener_universe))
		return unique_assetts
	
