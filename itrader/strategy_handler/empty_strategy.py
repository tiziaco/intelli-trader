import pandas as pd
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
	def __init__(self, name: str, timeframe: str, tickers: list[str]) -> None:
		# Fix: was `super.__init__(self, ...)` (missing parens) — a latent
		# TypeError if Empty_strategy were ever instantiated.
		super().__init__(name, timeframe, tickers)

		self.max_window = 1

	def __str__(self) -> str:
		return "Empty_%s" % self.timeframe

	def __repr__(self) -> str:
		return str(self)


	def calculate_signal(self, ticker: str, bars: pd.DataFrame) -> None:
		return