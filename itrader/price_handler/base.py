from __future__ import print_function
from abc import ABCMeta, abstractmethod

class AbstractPriceHandler(object):
	"""
	PriceHandler is a base class providing an interface for
	all subsequent (inherited) data handlers (both live and historic).

	The goal of a (derived) PriceHandler object is to output a set of
	TickEvents or BarEvents for each financial instrument and place
	them into an event queue.

	This will replicate how a live strategy would function as current
	tick/bar data would be streamed via a brokerage. Thus a historic and live
	system will be treated identically by the rest of the QSTrader suite.
	"""

	__metaclass__ = ABCMeta

	@abstractmethod
	def get_last_close(self, ticker):
		raise NotImplementedError("Should implement get_last_close()")
	
	@abstractmethod
	def get_last_date(self, ticker):
		raise NotImplementedError("Should implement get_last_date()")
	
	@abstractmethod
	def get_last_bar(self, ticker):
		raise NotImplementedError("Should implement get_last_bar()")
	
	@abstractmethod
	def get_bar(self, ticker, time):
		raise NotImplementedError("Should implement get_bar()")
	
	@abstractmethod
	def get_bars(self, ticker, start_dt, end_dt):
		raise NotImplementedError("Should implement get_bars()")
	
	@abstractmethod
	def get_resampled_bars(self, time, ticker, timeframe, window):
		raise NotImplementedError("Should implement get_resampled_bars()")
	
	@abstractmethod
	def load_data(self, ticker):
		raise NotImplementedError("Should implement load_data()")

	@abstractmethod
	def update_data(self, ticker):
		raise NotImplementedError("Should implement update_data()")
