import pandas as pd
from pandas_ta import trend
from pandas_ta import overlap
import numpy as np

from ..custom_indicators.custom_ind import SuperSmoother
from  itrader.strategy_handler.custom_indicators.custom_ind import PolynomialReg

class aroon_filter():
	"""
	Aroon attempts to identify if a security is trending and how strong.
	"""
	def calculate(df, window, limit):
		aroon = trend.aroon(df['high'], df['low'], length=window)
		aroon['filter'] = np.where(aroon.iloc[:,2] >= limit, 1, 0)
		aroon['filter'] = np.where(aroon.iloc[:,2] <= -limit, -1, aroon.iloc[:,-1])
		return aroon['filter']

class supertrend_filter():
	"""
	Identify market regime with SuperTrend filter.
	"""
	def calculate(high, low, close, window, multiplier, bt=False):
		"""
		Parameters
		----------
		high: Series
			High prices series
		low: Series
			Low prices series
		close: Series
			Close prices series
		window: int
			Lookback window for SuperTrend
		multiplier: int
			Multiplier for SuperTrend
		"""
		supert = overlap.supertrend(high, low, close, window, multiplier)
		supert['filter'] = supert.iloc[:,1]
		supert.drop(supert.columns[1], axis=1)
		if bt:
			return np.array(supert['filter'])
		else:
			return supert['filter'] 

class supersmoother_filter():
	"""
	Identify market regime with SuperTrend filter.
	"""
	def _calculate_slope(sf):
		pred, slope = PolynomialReg.calculate(sf, 2)
		return slope[-1]

	def calculate(sf, window, pole, limit):
		"""
		Parameters
		----------
		sf: Series
			time_series to be filtered (ex. close)
		window: int
			Lookback window for SuperSmoother
		pole: int
			number of poles for SuperSmoother
		limit: int
			treashold min. slope (0 : 0.5)

		"""
		filter = SuperSmoother.calculate(sf, window, pole)
		filter['slope'] = filter['ss'].rolling(window=window).apply(supersmoother_filter._calculate_slope)

		# Apply filter
		filter['filter'] = np.where(filter['slope'] >= 0, 1, 0)
		filter['filter'] = np.where(filter['slope'] <= 0, -1, filter['filter'])
		filter['filter'] = np.where(abs(filter['slope']) <= limit, 0, filter['filter'])
		
		return filter['filter']

class EMA_filter():
	"""
	Identify market regime with EMA filter.
	When the prices are above the EMA there is an uptrend,
	in the opposute case a downward trend.
	"""
	def calculate(df, lookback, ema_window):
		ema = overlap.ema(df, ema_window).dropna()
		if (df.tail(lookback) > ema.tail(lookback)).all() == True: # Filter
			return 1
		elif (df.tail(lookback) <= ema.tail(lookback)).all() == True:
			return -1
		else:
			return 0

class ADX_filter():
	"""
	Identify market regime with the ADX indicator.
	When the DMP is above the DMN there is an uptrend,
	in the opposute case a downward trend. Also, the ADX
	has to be greather than 20 (momentum condition)
	"""
	def calculate(high, low, close, window = 14, limit = 20):
		filter = trend.adx(high, low, close, length=window)
		filter['mom_component'] = np.where(filter.iloc[:,0] > limit, 1, 0)
		filter['trend_component'] = np.where(filter.iloc[:,1] > filter.iloc[:,2], 1, -1)
		filter['filter'] = filter['mom_component'] * filter['trend_component']
		return filter['filter']