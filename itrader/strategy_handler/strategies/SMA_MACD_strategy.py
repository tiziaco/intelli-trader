import pandas as pd
# import numpy as np

from pydantic import Field, model_validator

from itrader.config import BaseStrategyConfig
from itrader.core.sizing import SignalIntent
from itrader.strategy_handler.base import Strategy

from ta import trend

from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="SMA_MACD_strategy")


class SMA_MACDConfig(BaseStrategyConfig):
	"""Per-strategy params for the reference SMA_MACD strategy (D-02).

	Golden defaults mirror ``SMA_MACD_strategy.__init__``: short=50, long=100,
	FAST=6, SLOW=12, WIN=3. The ``_short_lt_long`` cross-field rule (HARD-02)
	rejects ``short_window >= long_window`` at construction. Co-located here
	(D-14) and re-indented to TABS (D-15) to match this strategy file.
	"""

	short_window: int = Field(default=50, gt=0)
	long_window: int = Field(default=100, gt=0)
	FAST: int = Field(default=6, gt=0)
	SLOW: int = Field(default=12, gt=0)
	WIN: int = Field(default=3, gt=0)

	@model_validator(mode="after")
	def _short_lt_long(self) -> "SMA_MACDConfig":
		"""HARD-02 cross-field rule: short_window must be strictly < long_window."""
		if self.short_window >= self.long_window:
			raise ValueError("short_window must be < long_window")
		return self


class SMA_MACD_strategy(Strategy):
	"""
	Requires:
	ticker - The ticker symbol being used for moving averages
	short_window - Lookback period for short moving average
	long_window - Lookback period for long moving average
	"""
	def __init__(self, config: SMA_MACDConfig) -> None:
		# D-01: single config-object constructor. The golden declarations
		# (sizing_policy=FractionOfCash(Decimal("0.95")), LONG_ONLY,
		# allow_increase=False) now live on the SMA_MACDConfig the caller
		# builds (RESEARCH Pitfall 1 byte-exact string-path literal).
		super().__init__("SMA_MACD", config)

		# Copy the per-strategy params onto the instance so generate_signal
		# reads self.short_window (NOT self.config) — preserving the pure-alpha
		# contract (D-12): no config reads inside generate_signal.
		self.short_window = config.short_window
		self.long_window = config.long_window
		self.FAST = config.FAST
		self.SLOW = config.SLOW
		self.WIN = config.WIN

		# Fetch width (bars) the handler requests from the feed window.
		self.max_window = max([self.long_window, 100])
		# D-15: warmup threshold = the old in-strategy guard value. The handler
		# short-circuits before generate_signal when len(data) < warmup, so the
		# firing tick is byte-identical to the removed guard (HARD-04).
		self.warmup = max([self.long_window, 100])

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
			MACD_Indicator = trend.MACD(bars.close, window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN, fillna=False)
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

