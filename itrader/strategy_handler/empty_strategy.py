# import pandas as pd
# import numpy as np
# from ta import trend

from itrader.strategy_handler.base import Strategy

class Empty_strategy(Strategy):
	"""
	Requires:
	ticker - The ticker symbol being used for moving averages
	short_window - Lookback period for short moving average
	long_window - Lookback period for long moving average
	"""
	def __init__(self, name, timeframe, tickers, settings):
		super.__init__(self, name, timeframe, tickers, settings)

		self.max_window = 1
	
	def __str__(self):
		return "Empty_%s" % self.timeframe

	def __repr__(self):
		return str(self)


	def calculate_signal(self, bars, ticker, time):
		return