from pandas_ta import momentum
import pandas as pd
import numpy as np

from itrader.strategy.custom_indicators.custom_ind import kalman_filter


class momentum_filter():
	"""
	Identify market momentum with relative momentum filter.
	"""
	def _relative_momentum(close):
		"""Relative momentum filter implementation
		:param data: list of price data
		:type data: list
		:return: list of boolean values indicating if the price is up in the last 24h, 12h, 4h and 1h
		:rtype: list
		"""
		# Convert data to numpy array for easier manipulation
		data = np.array(close)
		#print(data)
		
		# Compute the percentage change of the close price for each time step
		pct_change = np.diff(data) / data[:-1]
		
		# Compute the cumulative percentage change over different time periods
		cum_pct_change_24h = np.prod(1 + pct_change[-24:])
		cum_pct_change_12h = np.prod(1 + pct_change[-12:])
		cum_pct_change_4h = np.prod(1 + pct_change[-4:])
		cum_pct_change_1h = np.prod(1 + pct_change[-1:])
		
		# Check if the price is up in each time period
		is_up_24h = cum_pct_change_24h > 1
		is_up_12h = cum_pct_change_12h > 1
		is_up_4h = cum_pct_change_4h > 1
		is_up_1h = cum_pct_change_1h > 1
		
		# Return a list of boolean values indicating if the price is up in each time period
		if all([is_up_12h, is_up_4h, is_up_1h]):
			return True
		else:
			return False
		
	def calculate(close: pd.Series) -> pd.Series:
		"""
		Parameters
		----------
		close: Series
			Close prices 1h data
		
		Return
		------
		mom_filter: Series
			Momentum filter(1 if high momentum)
		"""
		# Check if the input data is a pd.Series type
		if not isinstance(close, pd.Series):
			raise TypeError("Input must be a Pandas series")

		mom_filter = close.rolling(window=26).apply(momentum_filter._relative_momentum).rename('filter')
		return mom_filter

class SlopeFilter():
	def calculate(data: pd.Series, limit: 20):
		filter = pd.DataFrame()
		filter['data_kf'] = kalman_filter(data, 0.001).to_frame()
		filter['slope'] = momentum.slope(filter['data_kf']).fillna(0)

		# Define the desired range (0 to 100)
		desired_min, desired_max = -100, 100

		# Scale the data between the desired range
		scaling_factor = (desired_max - desired_min) / (filter['slope'].max() - filter['slope'].min())
		scaled_values = scaling_factor * (filter['slope'] - filter['slope'].min()) + desired_min

		# Convert the scaled values back to a pandas Series
		filter['scaled_slope'] = pd.Series(scaled_values, index=filter.index)

		#Smooth the data with the kalman filter
		filter['slope_kf'] = kalman_filter(filter['scaled_slope'], 0.01)
		
		filter['direction'] =  np.where(filter['scaled_slope'] > filter['slope_kf'], 1, 0)
		filter['direction'] =  np.where(filter['scaled_slope'] < filter['slope_kf'], -1, filter['direction'])
		filter['inclination'] =  np.where(abs(filter['slope_kf']) > limit, 1, 0)
		filter['filter'] = filter['direction'] * filter['inclination']
		return filter['filter']