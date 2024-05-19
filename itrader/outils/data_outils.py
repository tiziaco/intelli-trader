import numpy as np
import pandas as pd

from .time_parser import to_timedelta

def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
		"""
		Resample the prices in another timeframe
		
		Parameters
		----------
		df: `DataFrime`
			The DataFrame to be resampled.
		timeframe: `timedelta`
			The new timeframe after resample.

		Returns
		-------
		prices: `DataFrame`
			DataFrame with Date-OHLCV bars.
		"""
		#return df.resample(to_timedelta(timeframe), label='right').agg(
		return df.resample(timeframe, label='right').agg(
			{'open':'first',
			'high':'max',
			'low':'min',
			'close':'last',
			'volume': 'sum'})