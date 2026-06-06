import pandas_ta as ta
import pandas as pd

from itrader.core.enums import Side
from itrader.events_handler.events import SignalEvent

from itrader.logger import get_itrader_logger
logger = get_itrader_logger().bind(component="SltpModels")


class FixedPercentage():
	"""
	This class calculate the stop loss and take profit price.
	The limit prices are based on a fixed percentage of the
	last price.

	M3-01: events are frozen facts — the models RETURN the computed
	level instead of mutating the signal; the caller threads the value
	into the signal it constructs.
	"""

	@staticmethod
	def calculate_sl(signal: SignalEvent, sl_level: float = 0.03) -> float:
		"""
		Define stopLoss level at a % of the last close.

		Parameters
		----------
		signal:
			Signal instance
		sl_level: `float`
			Stop loss pct distance from close (between 0 and 1)

		Returns
		-------
		`float`
			The computed stop-loss price (0.0 for an unknown side).
		"""
		# D-22: signal money is Decimal — the SL/TP models compute in float
		# (pre-signal domain); coerce at this boundary.
		last_close = float(signal.price)

		if signal.action is Side.BUY:
			# LONG direction: sl lower
			return round(last_close * (1 - sl_level), 5)
		elif signal.action is Side.SELL:
			# SHORT direction: sl higher
			return round(last_close * (1 + sl_level), 5)
		return 0.0


	@staticmethod
	def calculate_tp(signal: SignalEvent, tp_level: float = 0.03) -> float:
		"""
		Define take profit level at a % of the last close

		Parameters
		----------
		signal:
			Signal instance
		tp_level: `float`
			Take profit pct distance from close (between 0 and 1)

		Returns
		-------
		`float`
			The computed take-profit price (0.0 for an unknown side).
		"""
		# D-22: signal money is Decimal — coerce at this float boundary.
		last_close = float(signal.price)

		if signal.action is Side.BUY:
			# LONG direction: tp higher
			return last_close * (1 + tp_level)
		elif signal.action is Side.SELL:
			# SHORT direction: tp lower
			return last_close * (1 - tp_level)
		return 0.0

class Proportional():
	"""
	This class calculate the take profit price.
	The limit price is proportional to the defined
	stop loss price.
	"""

	@staticmethod
	def calculate_tp(signal: SignalEvent, multiplier: float = 0.03) -> float:
		"""
		Define take profit level proportional to the stop loss distance

		Parameters
		----------
		signal:
			Signal instance
		multiplier: `float`
			ATR multiplier (between 1 and 3)

		Returns
		-------
		`float`
			The computed take-profit price (0.0 for an unknown side).
		"""
		# D-22: signal money is Decimal — coerce at this float boundary.
		last_close = float(signal.price)
		sl = float(signal.stop_loss)

		if signal.action is Side.BUY:
			# LONG direction: tp higher
			delta = last_close - sl
			return last_close + multiplier * delta
		elif signal.action is Side.SELL:
			# SHORT direction: tp lower
			delta = sl - last_close
			return last_close - multiplier * delta
		return 0.0


class ATRsltp():
	"""
	This class calculate the stop loss and take profit price.
	The limit prices are based on the ATR indicator
	"""

	@staticmethod
	def calculate_sl(signal: SignalEvent, bars: pd.DataFrame, multiplier: float = 2, lookback: int = 20) -> float:
		"""
		Define stopLoss level based on the ATR value.
		It is calculated on the open or close price of the bar,
		according to the direction of the trade.

		Parameters
		----------
		signal:
			Signal instance
		bars: `DataFrame`
			Data prices
		multiplier: `float`
			ATR multiplier (between 1 and 3)
		lookback: `int`
			ATR lookback (between 1 and 20)

		Returns
		-------
		`float`
			The computed stop-loss price (0.0 for an unknown side).
		"""
		atr = ta.atr(bars.high, bars.low, bars.close, lookback, mamode='rma', drift=1)

		if signal.action is Side.BUY:
			# LONG direction: sl lower
			return float(bars.open.iloc[-1] - atr.iloc[-1] * multiplier)
		elif signal.action is Side.SELL:
			# SHORT direction: sl higher
			return float(bars.close.iloc[-1] + atr.iloc[-1] * multiplier)
		return 0.0


	@staticmethod
	def calculate_tp(signal: SignalEvent, bars: pd.DataFrame, multiplier: float = 2, lookback: int = 20) -> float:
		"""
		Define take profit level based on the ATR value.
		It is calculated on the open or close price of the bar,
		according to the direction of the trade.

		signal:
			Signal instance
		bars: `DataFrame`
			Data prices
		multiplier: `float`
			ATR multiplier (between 1 and 3)
		lookback: `int`
			ATR lookback (between 1 and 20)

		Returns
		-------
		`float`
			The computed take-profit price (0.0 for an unknown side).
		"""
		atr = ta.atr(bars.high, bars.low, bars.close, lookback, mamode='rma', drift=1)

		if signal.action is Side.BUY:
			# LONG direction: tp higher
			return float(bars.close.iloc[-1] + atr.iloc[-1] * multiplier)
		elif signal.action is Side.SELL:
			# SHORT direction: tp lower
			return float(bars.open.iloc[-1] - atr.iloc[-1] * multiplier)
		return 0.0
