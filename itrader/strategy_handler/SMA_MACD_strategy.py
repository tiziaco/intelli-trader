import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import Strategy

from ta import trend

from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="SMA_MACD_strategy")

class SMA_MACD_strategy(Strategy):
	"""
	Requires:
	ticker - The ticker symbol being used for moving averages
	short_window - Lookback period for short moving average
	long_window - Lookback period for long moving average
	"""
	def __init__(
		self,
		timeframe: str,
		tickers: list[str] = [],
		short_window: int = 50,
		long_window: int = 100,
		FAST: int = 6,
		SLOW: int = 12,
		WIN: int = 3,
	) -> None:
		super().__init__("SMA_MACD", timeframe, tickers)

		# Strategy parameters
		self.short_window = short_window
		self.long_window = long_window
		self.FAST = FAST
		self.SLOW = SLOW
		self.WIN = WIN

		self.max_window = max([self.long_window, 100])
	
	def __str__(self) -> str:
		return f'{self.name}_{self.timeframe}'

	def __repr__(self) -> str:
		return str(self)



	def calculate_signal(self, ticker: str, bars: pd.DataFrame) -> None:
		# Check if enough bars to calculate the signal

		if len(bars) < self.max_window:
			return
		last_time = self.last_time()
		if last_time is None:
			return
		# Calculate the SMA
		start_dt = last_time - self.timeframe * self.short_window
		short_sma = trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()

		start_dt = last_time - self.timeframe * self.long_window
		long_sma = trend.SMAIndicator(bars[start_dt:].close, self.long_window, True).sma_indicator().dropna()


		# Calculate the MACD
		MACD_Indicator = trend.MACD(bars.close, window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN, fillna=False)
		MACDhist = MACD_Indicator.macd_diff().dropna()


		### LONG signals
		# Entry
		if short_sma.iloc[-1] >= long_sma.iloc[-1]: # Filter
			if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)): # Buy trigger
				self.buy(ticker)
		# Exit
			elif ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
				#Sell trigger
				self.sell(ticker)


		### SHORT signals
		# Entry
		# if short_sma[-1] <= long_sma[-1]: # Filter
		# 	if ((MACDhist[-1] <= 0) and (MACDhist[-2] > 0)): # Short trigger
		# 		self.sell(ticker)

		# # Exit
		# 	elif ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
		# 		self.buy(ticker)

