from decimal import Decimal

import pandas as pd
# import numpy as np
# from ta import trend

from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection
from itrader.strategy_handler.base import Strategy

class Empty_strategy(Strategy):
	"""
	Minimal no-op strategy: never signals. Used by tests to exercise the
	shared base behaviour (pure-alpha contract, D-12).
	"""
	def __init__(self, name: str, timeframe: str, tickers: list[str]) -> None:
		# Fix: was `super.__init__(self, ...)` (missing parens) — a latent
		# TypeError if Empty_strategy were ever instantiated.
		# Declarations mirror the golden defaults (D-03): sizing_policy is
		# REQUIRED by the pure-alpha base contract.
		super().__init__(
			name, timeframe, tickers,
			sizing_policy=FractionOfCash(Decimal("0.95")),
			direction=TradingDirection.LONG_ONLY,
			allow_increase=False,
		)

		self.max_window = 1

	def __str__(self) -> str:
		return "Empty_%s" % self.timeframe

	def __repr__(self) -> str:
		return str(self)


	def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
		return None
