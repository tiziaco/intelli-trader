from datetime import datetime, timedelta
import pytz

from tqdm import tqdm
import tpqoa

import numpy as np
import pandas as pd

from itrader.config import FORBIDDEN_SYMBOLS, TIMEZONE
from itrader.outils.time_parser import to_timedelta
from .base import AbstractExchange


class OANDA_exchange(AbstractExchange):
	"""
	OANDA_data_provider is designed to download data from the defined
	exchange. It contains Open-High-Low-Close-Volume (OHLCV) data
	for each pair and streams those to the provided events queue as BarEvents.

	Parameters
	----------
	symbols: `list`
			The list of symbols to be downloaded.
	timeframes: `str`
		The time frame for the analysis
	start_dt: `str`
		The start date of the analysis
	end_dt: `str`
		The End date of the analysis
	global_queue: 'object'
		The global queue of the trading system
	base_currency: `str`
		The base currency for the downloaded data
	"""
   # self.exchange = tpqoa.tpqoa('oanda.cfg') 
	def __init__(self, name: str, currency: str):
		self.exchange = tpqoa.tpqoa('oanda.cfg')
		self.currency = currency
		self.markets = self.exchange.load_markets() #TODO: da modificare


	def get_all_symbols(self):
		"""
		Obtain the list of all pairs prices available in the
		exchange defined for CCXT.

		Returns
		-------
		`list[str]`
			The list of all coins.
		"""
		# Download all the symbols available in the defined exchange
		symbols_all = self.exchange.get_instruments()

		# Create two lists from tuple values
		instrument = [item[0] for item in symbols_all]
		symbols = [item[1] for item in symbols_all]

		return symbols

	@staticmethod
	def _format_data(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
		"""
		Clean and format the data downloaded from CCXT.

		Returns
		-------
		data: `DataFrame`
			Dataframe with Date-OHLCV.
		"""
		data = data.drop('complete', axis=1)
		data = data.reset_index()
		data = data.rename(columns={'time':'date', 'o':'open','h':'high','l':'low','c':'close','volume':'volume'})
		data = data.set_index('date')

		data.columns=['date','open','high','low','close','volume']
		# TODO: da vedere se serve. In origine non c'era
		# data.index = data.index.tz_convert('Europe/Paris')

		# change data type and deal with NaN values or duplicates
		data = data.astype(float)
		data = data.drop_duplicates()
		data.fillna(method='ffill', inplace=True)

		# Resample index for missing data
		df_resampled = data.resample(to_timedelta(timeframe)).ffill()
		#df_resampled['volume'] = data['volume']
		#df_resampled['volume'] = df_resampled['volume'].fillna(0)
		df_resampled

		return df_resampled

	def download_data(self, symbol: str, timeframe: str,
			start_date: pd.Timestamp,
			end_date: pd.Timestamp = None
			):
		"""
		Download and format the data for the defined tickers.

		Parameters
		----------
		symbol: `str`
			The ticker symbol, e.g. 'BTCUSDT'
		timeframe: `str`
			The timeframe of the data, e.g. '15m', '1h', '1d'
		start_date: `Timestamp`
			Start date since when to download the price data
		end_date: `Timestamp`
			End date of the price data period
		"""
		# Set end date
		if end_date == None:
			end_date = datetime.now().strftime("%Y-%m-%d %H:%M")

		# Download data
		raw_data = self.exchange.get_history(symbol, start_date, end_date, timeframe, 'B')
		# Format and return the data
		if len(raw_data) > 0 :
			data = self._format_data(raw_data, timeframe)
			return data