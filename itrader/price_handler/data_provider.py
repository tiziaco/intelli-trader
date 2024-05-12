#from datetime import datetime
import pytz
import numpy as np
import pandas as pd

from typing import Dict
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

from .base import AbstractPriceHandler
from .sql_handler import SqlHandler
from .exchange.CCXT import CCXT_exchange

from itrader.outils.time_parser import to_timedelta, timedelta_to_str
from itrader.outils.data_outils import resample_ohlcv

from itrader import config
from itrader import logger


class PriceHandler(AbstractPriceHandler):
	"""
	data_provider class is designed to load the data from the defined
	exchange. It contains Open-High-Low-Close-Volume (OHLCV) data
	for each pair and streams those to the provided events queue as BarEvents.

	Parameters
	----------
	exchange: `str`
		Exchange from where download datas.
	symbols: `list`
			The list of symbols to be downloaded.
	timeframes: `str`
		The time frame for the analysis
	start_dt: `str`
		The start date of the analysis
	end_dt: `str`
		The End date of the analysis
	base_currency: `str`
		The base currency for the downloaded data
	"""
	
	def __init__(self, exchange: str,
				symbols: list, timeframe: str,
				start_dt: str, end_dt: str = None,
				base_currency: str = 'USDT'):
		
		self.timeframe = timeframe
		self.start_date = start_dt
		self.end_date = end_dt
		self.base_currency = base_currency
		self.prices: Dict[str, pd.DataFrame] = {}
		self.exchange = self._init_exchange(exchange)
		self.symbols = self._init_symbols(symbols)
		self.sql_handler = SqlHandler()
		
		logger.info('PRICE HANDLER => OK')
	@property
	def available_symbols(self) -> list:
		return self.prices.keys()

	
	def load_data(self):
		"""
		Load price data from the data provider or sql database and 
		store it in a dictionary 
		"""

		# Read the list of coins stored in the db
		sql_symblos = self.sql_handler.get_symbols_SQL()
		symbols = list(map(lambda x: x.lower(), self.symbols))

		for symbol in tqdm(symbols):
			if symbol in sql_symblos:
				# Symbol already present in the SQL db
				self.prices[symbol.upper()] = self.sql_handler.read_prices(symbol)
			else:
				# Symbol not present in the SQL db. Download them with CCXT
				price = self.exchange.download_data(symbol, 
															self.timeframe,
															self.start_date,
															self.end_date)
				# Check if the data have been correctly downloaded
				if price is None:
					continue
				self.prices[symbol.upper()] = price
				self.sql_handler.to_database(symbol, price, True)
		
		logger.info('PRICE HANDLER: Data loaded')
	
	def update_data(self):
		"""
		Update the price data
		"""
		time_zone = pytz.timezone(config.TIMEZONE)

		while True: # repeat until we get all historical bars
			update_counter = 0
			for ticker in tqdm(self.prices.keys()):
				# Get the current UTC time
				now = pd.to_datetime(datetime.now(tz=timezone.utc))

				# Make it timezone aware
				now = now.replace(tzinfo=pytz.utc).astimezone(time_zone)

				# Calculate the bar expiration time
				now = now - timedelta(microseconds = now.microsecond)
				last_date = self.prices[ticker].index[-1]

				if now - last_date > to_timedelta(self.timeframe):
					update_counter += 1
					remaining_prices = self.exchange.download_data(ticker, self.timeframe, last_date)
					# Concatenate remaining_prices with existing DataFrame
					self.prices[ticker] = pd.concat([self.prices[ticker], remaining_prices])
					# Remove duplicate index values, keeping only the last value
					self.prices[ticker] = self.prices[ticker][~self.prices[ticker].index.duplicated(keep='last')]
					#TODO: delete last db row befor adding remaining data
					# Update SQL database with remaining_prices
					self.sql_handler.to_database(ticker, remaining_prices, False)
			if update_counter == 0:
				logger.info('PRICE HANDLER: Price updated')
				break

	#******* Data Manipulation ***************
	def get_last_close(self, ticker: str):
		"""
		Get the last close price for a ticker.

		Parameters
		----------
		ticker: `str`
			The ticker symbol, e.g. 'BTCUSD'.

		Returns
		-------
		price: `float`
			The last price for the symbol
		"""
		if ticker in self.available_symbols:
			try:
				last_prices = self.prices[ticker].iloc[-1]['close']
				return last_prices
			except:
				logger.error('PRICE HANDLER: data for %s at not found', ticker)
				return None
		else:
			logger.error('PRICE HANDLER: data for %s not found', ticker)
	
	def get_bar(self, ticker: str, time: pd.Timestamp):
		"""
		Get a specific bar at a specified time in the time series.

		Parameters
		----------
		ticker: `str`
			The ticker symbol, e.g. 'BTCUSD'.
		time: `timestamp`
			Time of the bar to get

		Returns
		-------
		prices: `DataFrame`
			DataFrame with  Date-OHLCV bars for the requested symbol
		"""
		if ticker in self.available_symbols:
			try:
				last_prices = self.prices[ticker].loc[time]
				return last_prices
			except:
				logger.error('PRICE HANDLER: data for %s at time %s not found', ticker, str(time))
				return None
		else:
			logger.error('PRICE HANDLER: data for %s not found', ticker)
	
	def get_bars(self, ticker: str, 
			start_dt: pd.Timestamp = None,
			end_dt: pd.Timestamp = None) -> pd.DataFrame:
		"""
		Slice the dataframe for a defined tickerbetwen the start 
		and the end date.

		Parameters
		----------
		ticker: `str`
			The ticker symbol, e.g. 'BTCUSD'.
		start_dt: `timestamp`
			Time for the dataframe slice
		end_dt: `timestamp`
			Time for the dataframe slice

		Returns
		-------
		prices: `DataFrame`
			DataFrame with  Date-OHLCV for the requested symbol
		"""
		if ticker not in self.available_symbols:
			logger.error('PRICE HANDLER: data for %s not found', ticker)
			return
		if start_dt is not None and end_dt is not None:
			return self.prices[ticker].loc[start_dt : end_dt]
		elif start_dt is not None and end_dt is None:
			return self.prices[ticker].loc[start_dt : ]
		elif start_dt is None and end_dt is not None:
			return self.prices[ticker].loc[ : end_dt]
		else:
			return self.prices[ticker]

	def get_resampled_bars(self, time: pd.Timestamp, 
						ticker:str, timeframe: timedelta, 
						window: int) -> pd.DataFrame:
		"""
		Load the price data from the price handler before to execute
		the strategy.
		If the timeframe of the stored data is different from the 
		strategy's timeframe, resample the data.

		Parameters
		----------
		time: `timestamp`
			Event time
		ticker: `str`
			The ticker symbol, e.g. 'BTCUSD'.
		tf_delta: `timedelta object`
			Timeframe of the strategy
		window: `int`
			Number of bars to loock back in the resampled timeframe
		
		Returns
		-------
		prices: `DataFrame`
			The resampled dataframe
		"""
		current_timeframe = to_timedelta(self.timeframe)
		# Check if the requested timeframe is the same of the stored data
		if timeframe != current_timeframe:
			ratio = timeframe / current_timeframe
			start_dt = (time - current_timeframe * window * ratio) + timeframe
			return resample_ohlcv(self.get_bars(ticker, start_dt, time+timeframe), 
						timeframe).head(window)
		else:
			start_dt = time - (timeframe * window) + timeframe
			return self.get_bars(ticker, start_dt, time)

	def to_megaframe(self, time: pd.Timestamp, tf_delta: pd.Timedelta, window: int):
		"""
		Put all the price data in a MultiIndex DataFrame with 2 levels
		columns: 1st = symbol and 2nd = OHLCV data.
		If the timeframe of the stored data is different from the 
		screener's timeframe, resample the data.

		Parameters
		----------
		time: `timestamp`
			Event time
		tf_delta: `timedelta object`
			Timeframe of the strategy
		window: `int`
			Number of bars to loock back in the resampled timeframe

		Returns
		-------
		megaframe: 'DataFrame'
			DataFrame with prices data of all the stored symbols
		"""
		df_list=[]
		for symbol in self.available_symbols:
			df = self.get_resampled_bars(time, symbol, tf_delta, window)
			df.name = symbol

			if df.index.tz is not None:
				df_list.append(df)

		megaframe = pd.concat(df_list, axis=1, keys=self.prices.keys())
		return megaframe

	## Setters

	def set_symbols(self, tickers: list[str]):
		if 'all' in tickers:
			self.symbols = self.exchange.get_tradable_symbols()
		else:
			self.symbols = tickers
	
	def set_timeframe(self, timeframe_strat: timedelta, timeframe_scr: timedelta):
		min_timeframe = min([timeframe_strat, timeframe_scr])
		self.timeframe = timedelta_to_str(min_timeframe)

	## Init methods
	def _init_symbols(self, symbols: list):
		"""
		Initialise the symbols

		Parameters
		----------
		symbols: `list`
			The list of symbols to be downloaded.
		"""
		# Delete duplicated symbols
		symbols = np.unique(symbols)

		if 'all' in symbols:
			return self.exchange.get_tradable_symbols()
		return symbols

	def _init_exchange(self, exchange: str):
		"""
		Factory method to initialise the correct exchange
		"""
		exchange_name = exchange.lower()
		if exchange_name == 'binance':
			return CCXT_exchange(exchange_name, self.base_currency)
		# elif exchange_name == 'kraken':
		# 	return CCXTKrakenExchange()
		else:
			raise NotImplementedError(f"Exchange '{exchange_name}' not implemented")
			
