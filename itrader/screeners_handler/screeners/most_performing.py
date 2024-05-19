import pandas as pd
import numpy as np

from itrader.outils.time_parser import to_timedelta, timedelta_to_str

from itrader.screeners_handler.screeners.base import Screener
from itrader.events_handler.event import BarEvent

class MostPerformingScreener(Screener):
	def __init__(self, tickers = ['all'], frequency = '1h', window = 26,timeframe = '1h'):
		super().__init__("MostPerforming", timeframe, frequency, tickers)
		self.window = window
		self.max_window = window
		self.last_proposed = []

		self.screener_id = "MostPerforming"
	
	def __str__(self):
		return self.screener_id

	def __repr__(self):
		return str(self)


	def screen_market(self, prices: pd.DataFrame, event: BarEvent):
		self.last_event = event

		if len(prices) >= self.max_window:

			# Calculate the return of the last row
			last_open = prices.xs('open', level=1, axis=1).tail(1)
			last_close = prices.xs('close', level=1, axis=1).tail(1)
			pct_return = (last_close.tail(1) - last_open.tail(1)) / last_close.tail(1)

			positive_ret = list(pct_return[pct_return>0].dropna(axis=1).columns)

			# Slice MegaFrame selecting only the 'close' columns for every symbol
			close = prices.xs('close', level=1, axis=1)

			# Calculate the return in the last 24h
			ret_24h = (close.tail(1) - close.tail(-1)) / close.tail(1)
			best_24h = list(ret_24h[ret_24h>0].iloc[-1].nlargest(10).index)

			ret_12h = (close.tail(1) - close.iloc[-12,:]) / close.tail(1)
			best_12h = list(ret_12h[ret_12h>0].iloc[-1].nlargest(10).index)

			# ret_4h = (close.tail(1) - close.iloc[-12,:]) / close.tail(1)
			# best_4h = list(ret_4h[ret_4h>0].iloc[-1].nlargest(10).index)

			ret_1h = pct_return.tail(1)
			best_1h = list(ret_1h[ret_1h>0].iloc[-1].nlargest(10).index)


			# Filter only tickers that are overperforming in every timefrime
			proposed = list(set(best_1h).intersection( best_12h, best_1h))#best_24h,
			self.last_proposed = proposed
			if (proposed):
				self.screener_signal(proposed)
			return proposed #['gainers']