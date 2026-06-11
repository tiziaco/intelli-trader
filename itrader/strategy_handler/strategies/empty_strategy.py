import pandas as pd
# import numpy as np
# from ta import trend

from itrader.config import BaseStrategyConfig
from itrader.core.sizing import SignalIntent
from itrader.strategy_handler.base import Strategy


class EmptyStrategyConfig(BaseStrategyConfig):
	"""No-extra-params config for the relocated EmptyStrategy (co-located, D-14)."""


class EmptyStrategy(Strategy):
	"""
	Minimal no-op strategy: never signals. Used by tests to exercise the
	shared base behaviour (pure-alpha contract, D-12).
	"""
	def __init__(self, name: str, config: EmptyStrategyConfig) -> None:
		# D-01: config-object constructor. The golden declarations
		# (sizing_policy/direction/allow_increase) live on the config.
		super().__init__(name, config)

		# Fetch width (bars); warmup stays 0 (no warmup gating, D-15).
		self.max_window = 1

	def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None:
		return None
