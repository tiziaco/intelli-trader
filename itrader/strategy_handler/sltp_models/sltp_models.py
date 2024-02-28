import pandas_ta as ta
import pandas as pd

from itrader.events_handler.event import SignalEvent

import logging
logger = logging.getLogger('TradingSystem')


class FixedPercentage():
	"""
	This class calculate the sttop loss and take profit price.
	The limit prices are based on a fixed percentage of the 
	last price.
	"""

	def calculate_sl(signal: SignalEvent, sl_level = 0.03):
		"""
		Define stopLoss level at a % of the last close.

		Parameters
		----------
		signal:
			Signal instance
		tp_level: `float`
			Take profit pct distance from close (between 0 and 1)
		"""
		last_close = signal.price

		if signal.action == 'BUY':
			# LONG direction: sl lower
			signal.stop_loss = round(last_close * (1 - sl_level), 5)
		elif signal.action == 'SELL':
			# SHORT direction: sl higher
			signal.stop_loss  = round(last_close * (1 + sl_level), 5)


	def calculate_tp(signal: SignalEvent, tp_level = 0.03):
		"""
		Define stopLoss level at a % of the last close

		Parameters
		----------
		signal:
			Signal instance
		tp_level: `float`
			Take profit pct distance from close (between 0 and 1)
		"""
		last_close = signal.price

		if signal.action == 'BUY':
			# LONG direction: tp higher
			signal.take_profit = last_close * (1 + tp_level)
		elif signal.action == 'SELL':
			# SHORT direction: tp lower
			signal.take_profit = last_close * (1 - tp_level)
		
class Proportional():
	"""
	This class calculate the take profit price.
	The limit price is proportional to the defined 
	stop loss price.
	"""

	def calculate_tp(signal: SignalEvent, multiplier = 0.03):
		"""
		Define stopLoss level at a % of the last close

		Parameters
		----------
		signal:
			Signal instance
		multiplier: `float`
			ATR multiplier (between 1 and 3)
		"""
		last_close = signal.price
		sl = signal.stop_loss

		if signal.action == 'BUY':
			# LONG direction: tp higher
			delta = last_close - sl
			signal.take_profit = last_close + multiplier * delta
		elif signal.action == 'SELL':
			# SHORT direction: tp lower
			delta = sl - last_close
			signal.take_profit = last_close - multiplier * delta


class ATRsltp():
	"""
	This class calculate the stop loss and take profit price.
	The limit prices are based on the ATR indicator
	"""

	def calculate_sl(signal: SignalEvent, bars: pd.DataFrame, multiplier = 2, lookback = 20):
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
		"""
		atr = ta.atr(bars.high, bars.low, bars.close, lookback, mamode='rma', drift=1)

		if signal.action == 'BUY':
			# LONG direction: sl lower
			signal.stop_loss = bars.open.iloc[-1] - atr.iloc[-1] * multiplier
		elif signal.action == 'SELL':
			# SHORT direction: sl higher
			signal.stop_loss  = bars.close.iloc[-1] + atr.iloc[-1] * multiplier


	def calculate_tp(signal: SignalEvent, bars: pd.DataFrame, multiplier = 2, lookback = 20):
		"""
		Define stopLoss level based on the ATR value.
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
		"""
		atr = ta.atr(bars.high, bars.low, bars.close, lookback, mamode='rma', drift=1)

		if signal.action == 'BUY':
			# LONG direction: tp higher
			signal.take_profit = bars.close.iloc[-1] + atr.iloc[-1] * multiplier
		elif signal.action == 'SELL':
			# SHORT direction: tp lower
			signal.take_profit = bars.open.iloc[-1] - atr.iloc[-1] * multiplier
