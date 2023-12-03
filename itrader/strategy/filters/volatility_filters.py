from pandas_ta.volatility import atr
from pandas_ta.volatility import bbands
from pandas_ta.overlap import ssf
import numpy as np

from itrader.strategy.custom_indicators.custom_ind import kalman_filter

class ATR_filter():
	"""
	ATR volatility filter.
	"""
	def calculate(high, low, close, window, limit=1, percent=True):
		"""
		Parameters:
		-----------
		high: Series
			High prices series
		low: Series
			Low prices series
		close: Series
			Close prices series
		window: 'int'
			Loockback window for the ATR 
		limit: 'int'
			Treshold value for the ATR amplitude in % (default: 1)
		"""
		vol = atr(high, low, close, length=window, percent=percent).to_frame()
		vol['filter'] = np.where(vol.iloc[:,-1] >= limit, 1, 0)
		return vol['filter']

class ATR_kalman_filter():
	"""
	ATR volatility filter.
	"""
	def calculate(high, low, close, window, covariance=0.0001):
		"""
		Parameters:
		-----------
		high: Series
			High prices series
		low: Series
			Low prices series
		close: Series
			Close prices series
		window: 'int'
			Loockback window for the ATR 
		covariance: 'float'
			level of smoothness of the kalman filter
		"""
		vol = atr(high, low, close, length=window, percent=True).to_frame().fillna(0)
		vol['kf'] = kalman_filter(vol.iloc[:,0], covariance)
		vol['filter'] = np.where(vol.iloc[:,0] > vol['kf'], 1, 0)
		return vol['filter']

class BB_filter():
	"""
	Bollinger Bands volatility filter filtered with SuperSmoother
	"""
	def calculate(df, window, std, limit = 0.3):
		"""
		Parameters:
		-----------
		df: 'DataFrame'
			df with OHLC bars 
		window: 'int'
			Loockback window for the BB bands
		limit: 'int'
			Limit value for the bands amplitude in % (default: 0.3)
		"""
		bb = bbands(df.close, length=window, std=std) # 30 bars
		ss = ssf(bb.iloc[:,-1].dropna(), window/2, 3).to_frame('ss')
		ss['filter'] = np.where(ss.iloc[:,-1] >= limit, 1, -1)
		return ss['filter'] 
