from decimal import Decimal

import pandas as pd
# import numpy as np

from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection
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
		tickers: list[str] | None = None,
		short_window: int = 50,
		long_window: int = 100,
		FAST: int = 6,
		SLOW: int = 12,
		WIN: int = 3,
	) -> None:
		# Golden declarations (D-03/D-08/D-10): FractionOfCash(Decimal("0.95"))
		# is the string-path literal (Pitfall 1) reproducing the legacy M1
		# sizing expression byte-exact once 07-05 wires the resolver;
		# LONG_ONLY + allow_increase=False declare the admission settings —
		# enforcement comes later.
		# WR-05: never share a mutable default list across instances — default
		# to None and build a fresh per-instance list so a future tickers
		# mutation cannot bleed across instances or into derive_membership.
		super().__init__(
			"SMA_MACD", timeframe, list(tickers or []),
			sizing_policy=FractionOfCash(Decimal("0.95")),
			direction=TradingDirection.LONG_ONLY,
			allow_increase=False,
		)

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



	def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
		# Check if enough bars to calculate the signal

		if len(bars) < self.max_window:
			return None
		# A2 (RESEARCH Pattern 4): bars.index[-1] replaces the legacy
		# self.last_time() — value-identical on the golden run (the feed
		# window's last completed bar at tick T is stamped T when
		# timeframe == base timeframe).
		last_time = bars.index[-1]
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
				return self.buy(ticker)
		# Exit
			elif ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
				#Sell trigger
				return self.sell(ticker)


		### SHORT signals
		# Entry
		# if short_sma[-1] <= long_sma[-1]: # Filter
		# 	if ((MACDhist[-1] <= 0) and (MACDhist[-2] > 0)): # Short trigger
		# 		self.sell(ticker)

		# # Exit
		# 	elif ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
		# 		self.buy(ticker)

		return None

