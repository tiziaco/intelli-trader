from datetime import timedelta
from queue import Queue
import pytz

from itrader.price_handler.data_provider import PriceHandler
from itrader.screeners_handler.screeners.base import Screener
from itrader.events_handler.event import BarEvent
from itrader.outils.time_parser import check_timeframe, get_timenow_awere, get_last_available_timestamp

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
		self.last_results: dict = {}

		logger.info('SCREENER HANDLER: Default => OK')
	
	def init_screeners(self):
		logger.info('SCREENER HANDLER: Initialise screeners')
		time_now = get_timenow_awere()
		event = BarEvent(time_now, {})

		for screener in self.screeners:
			last_timestamp = get_last_available_timestamp(time_now, screener.frequency)
			# Screen the market with all active screeners
			proposed = screener.screen_market(
				self.price_handler.to_megaframe(last_timestamp, screener.timeframe, screener.max_window),
				event
			)
			self.last_results = {event.time : proposed}

			logger.info('SCREENER HANDLER: Screener updated - %s', screener.name)
			if proposed:
				logger.info('   Proposed symbols: ' + str(proposed))
	
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
		current_res = {}
		self.last_results.clear()
		for screener in self.screeners:
			
			# Check if the screener's timeframe is a multiple of the bar event time
			if not check_timeframe(event.time, screener.frequency):
				continue

			# Screen the market with all active screeners
			proposed = screener.screen_market(
				self.price_handler.to_megaframe(event.time, screener.timeframe, screener.max_window),
				event
			)
			 # Initialize the dictionary for the current event time if not already present
			if event.time not in self.last_results:
				self.last_results[event.time] = {}

			# Save the results for each screener under the same timestamp
			current_res[screener.name] = proposed
			logger.info('SCREENER HANDLER: Screener updated - %s', screener.name)
			if proposed:
				logger.info('   Proposed symbols: ' + str(proposed))
		self.last_results = {event.time: current_res}
		

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

	def activate_screener(self, screener_index: int):
		"""
		Activate a screener by index
		"""
		if 0 <= screener_index <= len(self.screeners):
			self.screeners[screener_index-1].is_active = True
			logger.info(f"SCREENER HANDLER: Screener {screener_index} activated.")
			return True
		else:
			logger.warning("SCREENER HANDLER:Invalid screener index.")
			return False

	def deactivate_screener(self, screener_index: int):
		"""
		Deactivate a screener by index
		"""
		length = len(self.screeners)
		if 0 <= screener_index <= len(self.screeners):
			self.screeners[screener_index-1].is_active = False
			logger.info(f"SCREENER HANDLER: Screener {screener_index} deactivated.")
			return True
		else:
			logger.warning("SCREENER HANDLER: Invalid screener index.")
			return False

	def get_screeners_universe(self):
		"""
		Return the list with the universe to be screened
		"""
		screener_universe = []
		for screener in self.screeners:
			screener_universe += screener.universe
		unique_assetts = list(set(screener_universe))
		return unique_assetts
	
	def to_dict(self):
		"""
		Retrive all portfolio metrics in a dictionary
		with portfolio id as keys and metrics as value.

		Returns
		-------
		`dict`
			The portfolio metrics.
		"""
		screeners = {}
		for screener in self.screeners:
			screeners[screener.id] = screener.to_dict()
		return screeners
