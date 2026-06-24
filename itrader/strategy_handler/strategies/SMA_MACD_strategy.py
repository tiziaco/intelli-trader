from decimal import Decimal

from itrader.core.enums import TradingDirection
from itrader.core.sizing import FractionOfCash, SignalIntent
from itrader.strategy_handler.base import Strategy
from itrader.strategy_handler.indicators import SMA, MACDHist
from itrader.strategy_handler.primitives import crossover, crossunder, is_above

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
	# D-08: max_window/warmup are NO LONGER hand-set — the base auto-derives both
	# from the declared indicators' min_period (max(SMA50->50, SMA100->100,
	# MACDHist->15) == 100), removing the WR-03 footgun.

	def validate(self) -> None:
		# HARD-02 cross-field rule (was the pydantic @model_validator, D-09):
		# short_window must be strictly < long_window.
		if self.short_window >= self.long_window:
			raise ValueError("short_window must be < long_window")

	def init(self) -> None:
		# D-03: declare the indicators as recipes — the base constructs an
		# IndicatorHandle per call, re-populates it each tick (evaluate), and
		# auto-derives warmup/max_window from their min_period (D-08).
		# [BYTE-EXACT] SMA slices `bars[start_dt:][close]` (Pitfall 1, owned by
		# the SMA adapter); MACDHist uses the full window.
		self.short_sma = self.indicator(SMA, "close", self.short_window)
		self.long_sma = self.indicator(SMA, "close", self.long_window)
		self.macd_hist = self.indicator(
			MACDHist, "close", self.fast_window, self.slow_window, self.signal_window
		)

	def generate_signal(self, ticker: str) -> SignalIntent | None:
		# D-06/P5-D14: bars dropped — the handler pushed the latest bar via
		# update(ticker,bar) (driving the per-symbol stateful handles) and gated on
		# is_ready(ticker). D-01: read entirely through handles + primitives.
		# [BYTE-EXACT] both SMAs AND MACDHist advance every tick via the O(1)
		# recurrences; the firing tick reads the same handle values — proven byte-
		# identical by the oracle (134 / 46189.87730727451).

		### LONG signals
		# Entry
		if is_above(self.short_sma, self.long_sma):  # Filter
			if crossover(self.macd_hist, 0):  # Buy trigger
				return self.buy(ticker)
			# Exit
			if crossunder(self.macd_hist, 0):  # Sell trigger
				return self.sell(ticker)

		### SHORT signals (deferred to the margin/shorts milestone)
		# if is_below(self.short_sma, self.long_sma):  # Filter
		# 	if crossunder(self.macd_hist, 0):  # Short trigger
		# 		return self.sell(ticker)
		# 	if crossover(self.macd_hist, 0):  # Exit
		# 		return self.buy(ticker)

		return None

