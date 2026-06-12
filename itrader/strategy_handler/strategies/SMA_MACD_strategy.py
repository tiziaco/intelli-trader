from decimal import Decimal

import pandas as pd
# import numpy as np

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy

from ta import trend

from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="SMA_MACD_strategy")


class SMAMACDStrategy(Strategy):
	"""
	Requires:
	ticker - The ticker symbol being used for moving averages
	short_window - Lookback period for short moving average
	long_window - Lookback period for long moving average

	Class-attr authoring surface (D-02): the golden declarations live as class
	attributes; the base engine applies kwargs over them. These defaults are
	ORACLE-VISIBLE — any drift breaks 134 trades / 46189.87730727451.
	"""

	name = "SMA_MACD"
	# Pitfall 4: Decimal string-path literal only — never the binary-float path.
	sizing_policy = FractionOfCash(Decimal("0.95"))
	direction = TradingDirection.LONG_ONLY
	short_window: int = 50
	long_window: int = 100
	fast_window: int = 6
	slow_window: int = 12
	signal_window: int = 3
	# Fetch width (bars) the handler requests from the feed window, and the
	# warmup threshold the handler short-circuits on — both == max([100, 100]).
	max_window: int = 100
	warmup: int = 100

	def validate(self) -> None:
		# HARD-02 cross-field rule (was the pydantic @model_validator, D-09):
		# short_window must be strictly < long_window.
		if self.short_window >= self.long_window:
			raise ValueError("short_window must be < long_window")

	def init(self) -> None:
		# No-op in Phase 2 (D-10) — indicators stay inline in generate_signal.
		...

	def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
		# Warmup gating now lives in the handler framework short-circuit (D-15);
		# generate_signal assumes it is only called with enough bars.
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


		### LONG signals
		# Entry
		if short_sma.iloc[-1] >= long_sma.iloc[-1]: # Filter
			# Calculate the MACD (W1-12: computed INSIDE the SMA guard — only on
			# ticks where the SMA filter holds. The firing tick is byte-identical
			# (same MACD value, just computed lazily); per D-02 this reorder is
			# proven by code review + the byte-exact oracle ONLY, NO new SMA_MACD test.)
			MACD_Indicator = trend.MACD(bars.close, window_fast=self.fast_window, window_slow=self.slow_window, window_sign=self.signal_window, fillna=False)
			MACDhist = MACD_Indicator.macd_diff().dropna()
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

