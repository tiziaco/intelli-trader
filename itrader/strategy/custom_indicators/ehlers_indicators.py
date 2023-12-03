import numpy as np
import pandas as pd
from legitindicators import super_smoother

#---- General functions -----
def hp_filter(x: pd.Series, hp_length: int, multiplier:float):
	"""Applies high pass filter to a given time series.

	Parameters
	----------
		data: list of price data
		hp_length: High pass length
		multiplier: multiplier

	Returns
	-------
		hp (pd.Series) High pass filter applied price data
	"""
	data = np.array(x, dtype=float)  # Convert data to a NumPy array
	alpha_arg = 2 * np.pi / (multiplier * hp_length * np.sqrt(2))
	alpha1 = (np.cos(alpha_arg) + np.sin(alpha_arg) - 1) / np.cos(alpha_arg)

	hpf = np.zeros(len(data), dtype=float)  # Initialize hpf as a NumPy array
	hpf[:2] = [0, 0]

	for i in range(2, len(data)):
		hpf[i] = (1.0 - alpha1 / 2.0)**2 * (data[i] - 2 * data[i - 1] + data[i - 2]) + 2 * (1 - alpha1) * hpf[i - 1] - (1 - alpha1)**2 * hpf[i - 2]

	return pd.Series(hpf, index=x.index)

def AGC(loCutoff=10, hiCutoff=48, slope=1.5):
	"""
	This function calculates the AGC factor based on the given cutoff frequencies and slope.
	
	Parameters
	----------
		loCutoff (int): The lower cutoff frequency.
		hiCutoff (int): The higher cutoff frequency.
		slope (float): The slope in dB.
		
	Returns
	-------
		float: The AGC factor.
	"""
	accSlope = -slope # acceptableSlope = 1.5 dB
	ratio = 10 ** (accSlope / 20)
	if (hiCutoff - loCutoff) > 0:
		factor = ratio ** (2 / (hiCutoff - loCutoff))
	else:
		factor = 1
	return factor

def pearson_corr(data, min_lag = 3, max_lag = 48):
	"""
	Calculate the Pearson correlation for each value of lag.
	
	Parameters
	----------
		data (np.array): The input data.
		AvgLength (int): The average length.
		max_lag (int): The maximum lag value.
	
	Returns
	-------
		np.ndarray: The autocorrelation matrix.
	"""
	autocorr = np.zeros((max_lag, len(data)))
	lags = np.arange(min_lag, max_lag + 1)
	avglength = 3
	Avg_Corr_Out = np.zeros((len(data), max_lag))
	for j in lags:
		lagged = np.concatenate((np.zeros(j), data[:len(data) - j]))  # Lag series
		for i in range(max_lag, len(data)):
			Avg_Corr_Out[i, j - min_lag] = np.corrcoef(lagged[i - avglength + 1:i + 1], data[i - avglength + 1:i + 1])[0, 1]
	return autocorr


def autocorr_periodgram(x, LPPeriod=3, HPPeriod=48):
	"""
	This function calculates the dominant cycle of a time series using 
	the autocorrelation periodogram method.

	Parameters
	----------
		data (Series): The input time series.
		LPPeriod (int): The low pass filter period.
		HPPeriod (int): The high pass filter period.
	
	Returns
	-------
		(pd.Series) the autocorrelation periodgram.
	"""
	min_lag=3
	max_lag=48
	if not (max_lag < len(x) and max_lag > 0):
		raise ValueError("Argument max_lag out of bounds.")

	# Calculate HP (High-pass filter)
	HP = hp_filter(x, HPPeriod, 1)
	
	# Calculate Super Smoother Filter
	Filt = super_smoother(HP, LPPeriod)

	# Pearson correlation for each value of lag
	lags = np.arange(min_lag, max_lag + 1)
	avglength = 3
	Avg_Corr_Out = np.zeros((len(x), max_lag))
	for j in lags:
		lagged = np.concatenate((np.zeros(j), Filt[:len(Filt) - j]))  # Lag series
		for i in range(max_lag, len(x)):
			Avg_Corr_Out[i, j - min_lag] = np.corrcoef(lagged[i - avglength + 1:i + 1], Filt[i - avglength + 1:i + 1])[0, 1]

	# Calculate sine and cosine part
	cosinePart = np.zeros((len(x), max_lag))
	sinePart = np.zeros((len(x), max_lag))
	sqSum = np.zeros((len(x), max_lag))
	for j in range(min_lag, max_lag + 1):
		for k in range(3, 49):
			angle = np.deg2rad(360 * k / j)
			cosinePart[:, j - min_lag] += Avg_Corr_Out[:, k - 3] * np.cos(angle)
			sinePart[:, j - min_lag] += Avg_Corr_Out[:, k - 3] * np.sin(angle)
		sqSum[:, j - min_lag] = cosinePart[:, j - min_lag] ** 2 + sinePart[:, j - min_lag] ** 2
	sqSum = np.nan_to_num(sqSum, nan=0)
	
	# Iterate over every i in j and smooth R by the 0.2 and 0.8 factors
	R = np.zeros((len(x), max_lag))
	for j in range(min_lag, max_lag + 1):
		for i in range(1, len(x)):
			R[i, j - min_lag] = (0.2 * sqSum[i, j - min_lag]) * sqSum[i, j - min_lag] + (0.8 * R[i - 1, j - min_lag])

	# Find Maximum Power Level for Normalization
	MaxPwr = np.zeros((len(x), max_lag))
	for j in range(min_lag, max_lag + 1):
		for i in range(1, len(x)):
			MaxPwr[i, j - min_lag] = 0.995 * MaxPwr[i - 1, j - min_lag]
			if R[i, j - min_lag] > MaxPwr[i, j - min_lag]:
				MaxPwr[i, j - min_lag] = R[i, j - min_lag]
	
	# Calculate Pwr
	Pwr = np.zeros((len(x), max_lag))
	for j in range(min_lag, max_lag + 1):
		for i in range(len(x)):
			Pwr[i, j - min_lag] = R[i, j - min_lag] / MaxPwr[i, j - min_lag]
	Pwr = np.nan_to_num(Pwr, nan=0)
	
	# Compute the dominant cycle using the CG of the spectrum
	Spx = np.zeros(len(x))
	Sp = np.zeros(len(x))
	for j in range(min_lag, max_lag + 1):
		Spx = np.where(Pwr[:, j - min_lag] >= 0.5, Spx + j * Pwr[:, j - min_lag], Spx)
		Sp = np.where(Pwr[:, j - min_lag] >= 0.5, Sp + Pwr[:, j - min_lag], Sp)

	DominantCycle = np.zeros(len(x))    
	for i in range(len(x)):
		if Sp[i] != 0:
			DominantCycle[i] = Spx[i] / Sp[i]
		if DominantCycle[i] < 10:
			DominantCycle[i] = 10
		if DominantCycle[i] > HPPeriod:
			DominantCycle[i] = HPPeriod

	return pd.Series(DominantCycle, index=x.index)

def autocorr_reversal(data: pd.Series, LPPeriod=20, HPPeriod=48):
	"""
	This function calculates the reverse points of a time series using 
	the autocorrelation periodogram.

	Parameters
	----------
		data (Series): The input time series.
		LPPeriod (int): The low pass filter period.
		HPPeriod (int): The high pass filter period.
	
	Returns
	-------
		(pd.Series) The reversal points series.
	"""
	min_lag = 3
	max_lag = 48
	AvgLength = 3
	
	# high pass filter
	hp = hp_filter(data, HPPeriod, 1)

	# Super Smoother
	Filt = super_smoother(hp, LPPeriod)

	# Pearson correlation for each value of lag
	lags = np.arange(min_lag, max_lag + 1)
	Avg_Corr_Rev_Out = np.zeros((len(data), max_lag))

	for j in lags:
		# Lag series
		lagged = np.concatenate((np.zeros(j), Filt[:len(Filt) - j]))

		for i in range(AvgLength, len(data)):
			Avg_Corr_Rev_Out[i, j - min_lag] = np.corrcoef(lagged[i - AvgLength + 1:i + 1], Filt[i - AvgLength + 1:i + 1])[0, 1]
			# Scale each correlation to range between 0 and 1
			Avg_Corr_Rev_Out[i, j - min_lag] = 0.5 * (Avg_Corr_Rev_Out[i, j - min_lag] + 1)

	# Mark all > 0.5 and < 0.5 crossings
	SumDeltas = np.zeros((len(data), max_lag))

	for j in lags:
		for i in range(AvgLength, len(data)):
			if ((Avg_Corr_Rev_Out[i, j - min_lag] > 0.5) and (Avg_Corr_Rev_Out[i - 1, j - min_lag] < 0.5)) or ((Avg_Corr_Rev_Out[i, j - min_lag] < 0.5) and (Avg_Corr_Rev_Out[i - 1, j - min_lag] > 0.5)):
				SumDeltas[i, j - min_lag] = 1.0
			else:
				SumDeltas[i, j - min_lag] = 0.0

	# Sum across the matrix of all correlation 0.5 crossings
	Reversal = np.zeros(len(data))
	test_sum = np.zeros(len(data))

	for i in range(len(data)):
		test_sum[i] = np.sum(SumDeltas[i, :])
		if test_sum[i] > 24:
			Reversal[i] = 1
		else:
			Reversal[i] = 0

	return Reversal

def hilbert_indicator(data: pd.Series, LPPeriod=10, HPPeriod=48):
	"""
	This function calculates the Hilbert Transform of a time series.
	TODO: to be tested.

	Parameters
	----------
		data (Series): The input time series.
		LPPeriod (int): The low pass filter period.
		HPPeriod (int): The high pass filter period.
	
	Returns
	-------
		(pd.DataFrame) The Hilbert indicator with
		the real and imaginary components
	"""
	# High Pass filter
	hp = hp_filter(data, HPPeriod, 1)

	# Super Smoother
	filt = super_smoother(hp, LPPeriod)

	# Calculate IPeak and update it
	IPeak = np.zeros_like(filt)
	IPeak[0] = 0.991 * 1
	for i in range(1, len(filt)):
		if abs(filt[i]) > IPeak[i - 1]:
			IPeak[i] = abs(filt[i])
		else:
			IPeak[i] = IPeak[i - 1]
	
	# Normalize Real
	Real = filt / IPeak

	# Calculate Quadrature and update QPeak
	Quadrature = Real - np.roll(Real, 1)
	QPeak = np.zeros_like(filt)
	QPeak[0] = 0.991 * 1
	for i in range(1, len(Quadrature)):
		if abs(Quadrature[i]) > QPeak[i - 1]:
			QPeak[i] = abs(Quadrature[i])
		else:
			QPeak[i] = QPeak[i - 1]

	# Normalize Quadrature
	Quadrature = Quadrature / QPeak
		
	# Calculate imaginary component	
	Imag = super_smoother(Quadrature, LPPeriod)

	return pd.DataFrame({'real': Real, 'imag': Imag}, index=data.index)

def adaptive_stoch(x, LPPeriod, HPPeriod):
	"""
	Calculate the adaptive stochastic indicator for a given time series 
	according to the autocorellation periodgram.

	Parameters
	----------
		data (Series): The input time series.
		LPPeriod (int): The low pass filter period.
		HPPeriod (int): The high pass filter period.
	
	Returns
	-------
		(pd.Series) The adaptive stochastic indicator.
	"""
	dominant_cycle = autocorr_periodgram(x, LPPeriod, HPPeriod)
	hp = hp_filter(x, HPPeriod, 1)
	filt = super_smoother(hp, LPPeriod)

	# Calculate the integer value of dominant_cycle and ensure it's rounded
	n = np.round(dominant_cycle).astype(int)

	# Initialize arrays for HighestC, LowestC, Stoc, and adaptive_stochastic
	HighestC = np.zeros_like(x)
	LowestC = np.zeros_like(x)
	Stoc = np.zeros_like(x)

	# Iterate through the data
	for i in range(HPPeriod, len(x)):
		k = n[i]
		HighestC[i] = np.max(filt[i - k + 1:i])
		LowestC[i] = np.min(filt[i - k + 1:i])
		
		if HighestC[i] == LowestC[i]:
			Stoc[i] = 0.5  # Avoid division by zero
		else:
			Stoc[i] = (filt[i] - LowestC[i]) / (HighestC[i] - LowestC[i])

	adaptive_stochastic = super_smoother(Stoc, LPPeriod)
	return pd.Series(adaptive_stochastic, index=x.index)

def inverse_fisher_transform(data: pd.Series):
	"""
	This function calculates the inverse Fisher transform of 
	a given dataset and returns a DataFrame containing the 
	transformed values.

	Parameters
	----------
		data (Series): The input time series.
	
	Returns
	-------
		(pd.DataFrame) The components of the Fisher transform.
	"""
	# Calculate IFish
	Value1 = 2 * (data - 0.5)
	Value2 = np.exp(2 * 3 * Value1)
	IFish = (Value2 - 1) / (Value2 + 1)

	# Calculate 0.9*IFish[1]
	IFish_1 = np.roll(IFish, 1)
	IFish_1[0] = 0  # Handle the first element
	IFish_1 *= 0.9

	# Create a DataFrame
	return pd.DataFrame({'ifish': IFish, 'ifish_1': IFish_1})