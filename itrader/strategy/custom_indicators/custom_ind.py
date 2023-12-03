import numpy as np
import pandas as pd
import pandas_ta as ta

from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from pykalman import KalmanFilter

### Noise indicators

class pdensity():
	"""
	Calculate the Price Density of a time series
	"""
	def _calculate_pdensity(df):
		sum_hl = np.sum(df['high'].to_numpy() - df['low'].to_numpy())
		pdensity = np.divide(sum_hl,(max(df['high'] - min(df['low']))))
		return pdensity
	
	def calculate(df, window):
		temp = list(map(pdensity._calculate_pdensity, df.loc[:,['high','low']].rolling(window)))
		df.insert(2, 'pdensity',temp)
		df.iloc[:window,-1] = np.nan
		return df.iloc[:,-1]

class efficiency_ratio():
	"""
	Calculate the Kaufman Efficency Ratio
	"""
	def _calculate_kratio(df):
		up = np.absolute(df[0] - df[-1])
		down = np.sum(np.absolute(np.diff(df.to_numpy())))
		return (up / down)*100

	def calculate(df, window):
		return df.rolling(window).apply(efficiency_ratio._calculate_kratio)
	



###Smoothers

class SuperSmoother():
	"""
	Calculate the smoothed line of a time-series
	"""
	def calculate(sf, window, pole):
		"""
		Parameters:
		-----------
		sf: 'Series'
			Time series to filter
		window: 'int'
			Loockback window
		pole: 'int'
			Poles of the SS filter (2 or 3)
		"""
		ss = ta.ssf(sf, window, pole).to_frame('ss')
		ss['sdev'] = ss.rolling(window=window).std()
		ss['hband'] = ss.iloc[:,0] + ss.loc[:,'sdev']
		ss['lband'] = ss.iloc[:,0] - ss.loc[:,'sdev']
		# Slope
		return ss

class PolynomialReg():
	"""
	Calculate the polinomial regression of a time series
	"""
	def calculate (sf, order):
		x = np.arange(0,len(sf))
		y = sf.values
		poly_reg = PolynomialFeatures(degree=order, include_bias=False)
		X_poly = poly_reg.fit_transform(x.reshape(-1,1))
		pol_reg = LinearRegression()
		pol_reg.fit(X_poly, y)
		poly = pd.Series(pol_reg.predict(X_poly), sf.index)
		return poly, pol_reg.coef_

def kalman_filter(data: pd.Series, covariance:float = 0.001):
	"""
	Apply Kalman filter to smooth the data.

	Parameters:
		data (pd.Series): The input data to be filtered.
		covariance (float): The covariance value for the transition matrix.

	Returns:
		pd.Series: The filtered data.

	Raises:
		None
	"""
	kf = KalmanFilter(transition_matrices = [1],
					observation_matrices = [1],
					initial_state_mean = data[0],
					initial_state_covariance = 1,
					observation_covariance = 1,
					transition_covariance = covariance)
	mean, cov = kf.filter(data.values)
	mean, std = mean.squeeze(), np.std(cov.squeeze())
	kf_mean = pd.Series(mean, index=data.index)
	return kf_mean

def tii(close, major_length=60, minor_length=30):
	"""
	Function to calculate Trend Intensity Index (TII)
	"""
	# Calculate SMA
	sma = ta.sma(close, major_length)

	# Calculate positive and negative sums using rolling windows
	price_above_avg = (close > sma)
	price_below_avg = (close < sma)
	positive_sum = price_above_avg.mask(price_above_avg, close - sma).rolling(window=minor_length).sum()
	negative_sum = price_below_avg.mask(price_below_avg, sma - close).rolling(window=minor_length).sum()

	# Calculate TII
	tii = 100 * positive_sum / (positive_sum + negative_sum)
	return tii