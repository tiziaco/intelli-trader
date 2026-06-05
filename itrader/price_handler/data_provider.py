#from datetime import datetime
import pytz
import numpy as np
import pandas as pd

from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
from tqdm import tqdm

from .base import AbstractPriceHandler
from .sql_handler import SqlHandler
from .exchange.CCXT import CCXT_exchange

from itrader.outils.time_parser import to_timedelta, timedelta_to_str
from itrader.outils.data_outils import resample_ohlcv

from itrader.config import TIMEZONE
from itrader.core.exceptions import MalformedDataError, MissingPriceDataError
from itrader.logger import get_itrader_logger


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
	
	# Default golden dataset for the offline/csv backtest feed (D-01).
	CSV_DEFAULT_PATH = 'data/BTCUSD_1d_ohlcv_2018_2026.csv'
	# Explicit date window for the offline oracle (D-02). Pinned on the feed
	# side so the oracle is insulated if the CSV is ever regenerated.
	CSV_START_DATE = '2018-01-01'
	CSV_END_DATE = '2026-06-03'
	# Fixed ticker for the offline feed (D-03/D-06).
	CSV_TICKER = 'BTCUSD'

	def __init__(self, exchange: str,
				symbols: list[str], timeframe: str,
				start_dt: str, end_dt: Optional[str] = None,
				base_currency: str = 'USDT',
				csv_path: Optional[str] = None) -> None:

		self.timeframe = timeframe
		self.start_date = start_dt
		self.end_date = end_dt
		self.base_currency = base_currency
		self.prices: Dict[str, pd.DataFrame] = {}

		# D-07: offline/csv feed branch lives INSIDE PriceHandler. On the csv
		# path we construct neither SqlHandler (no PostgreSQL) nor a CCXT
		# exchange (no network) — the backtest reads the committed golden CSV.
		# The SQL/CCXT attrs are deferred subsystems (D-sql/D-oanda) typed Any so
		# the dormant non-csv branches stay type-clean without widening scope.
		self.is_csv = (exchange is not None and exchange.lower() == 'csv')
		self.csv_path: Optional[str]
		self.exchange: Any
		self.sql_handler: Any
		if self.is_csv:
			self.csv_path = csv_path if csv_path is not None else self.CSV_DEFAULT_PATH
			self.exchange = None
			self.sql_handler = None
			self.symbols = self._init_symbols(symbols)
		else:
			self.csv_path = None
			self.exchange = self._init_exchange(exchange)
			self.symbols = self._init_symbols(symbols)
			# SqlHandler is a deferred subsystem (D-sql, ignore_errors override) so
			# its constructor is untyped to the gate; this non-csv branch is dormant
			# on the golden backtest path.
			self.sql_handler = SqlHandler()  # type: ignore[no-untyped-call]

		self.logger = get_itrader_logger().bind(component="PriceHandler")
		self.logger.info('Price Handler initialized')

	@property
	def available_symbols(self) -> list[str]:
		return list(self.prices.keys())


	def load_data(self) -> None:
		"""
		Load price data from the data provider or sql database and
		store it in a dictionary
		"""

		# D-07: offline/csv feed reads the committed golden CSV into
		# self.prices in the EXACT CCXT frame shape and returns without ever
		# touching SqlHandler or the CCXT exchange.
		if self.is_csv:
			self._load_csv_data()
			return

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
		
		self.logger.info('Price data loaded')

	def _load_csv_data(self) -> None:
		"""
		Load the golden CSV into self.prices in the EXACT frame shape the
		CCXT path produces (see CCXT._format_data): lowercase OHLCV columns
		and a tz-aware DatetimeIndex named 'date' converted to TIMEZONE.

		Pitfall 6: the ping clock is derived from this same frame index
		(backtest_trading_system.py: set_dates(self.prices[...].index)), so the
		index tz is the ping tz by construction — one tz, no double-convert.

		V5 / T-02-01: the committed CSV is trusted-but-verified — a malformed
		header or empty frame raises loudly instead of silently yielding empty
		bars (which would produce a silently-wrong oracle / zero trades).
		"""
		# Trusted-but-verify: validate the Binance-kline header before mapping.
		expected_cols = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']
		raw = pd.read_csv(self.csv_path)
		missing = [col for col in expected_cols if col not in raw.columns]
		if missing:
			raise MalformedDataError(
				str(self.csv_path), f"missing columns {missing}")

		# Map Open time->date, Open/High/Low/Close/Volume->lowercase, drop the
		# trailing Binance-kline columns (Close time, Quote asset volume,
		# Number of trades, Taker buy base/quote, Ignore).
		data = raw[expected_cols].copy()
		data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']

		# Format index exactly like CCXT._format_data: tz-aware then convert to
		# the configured timezone so it matches the ping clock by construction.
		data = data.set_index('date')
		data.index = pd.to_datetime(data.index, utc=True)
		data.index = data.index.tz_convert(TIMEZONE)
		data.index.name = 'date'
		data = data.astype(float)

		# D-02: pin the date window explicitly (2018-01-01 -> 2026-06-03) on the
		# feed side so the oracle is insulated if the CSV is regenerated. The
		# slice bounds are localized to the index tz to match correctly.
		start = pd.Timestamp(self.CSV_START_DATE, tz=TIMEZONE)
		end = pd.Timestamp(self.CSV_END_DATE, tz=TIMEZONE) \
			+ pd.Timedelta(days=1)
		data = data.loc[start:end]

		if data.empty:
			raise MissingPriceDataError(
				str(self.csv_path),
				f"empty frame after the {self.CSV_START_DATE} -> "
				f"{self.CSV_END_DATE} window slice")

		self.prices[self.CSV_TICKER.upper()] = data
		self.logger.info('Price data loaded from csv (%d bars)', len(data))

	def update_data(self) -> None:
		"""
		Update the price data
		"""
		time_zone = pytz.timezone(TIMEZONE)

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
				self.logger.info('Price updated')
				break

	# Minimal-conformance stubs (D-07): the AbstractPriceHandler Protocol declares
	# these but the backtest path never calls them (live/streaming concern). Provide
	# concrete NotImplementedError bodies so PriceHandler is not implicitly abstract.
	def get_last_bar(self, ticker: str) -> Any:
		raise NotImplementedError("get_last_bar is not used on the backtest path")

	def get_last_date(self, ticker: str) -> Any:
		raise NotImplementedError("get_last_date is not used on the backtest path")

	#******* Data Manipulation ***************
	def get_last_close(self, ticker: str) -> Any:
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
				self.logger.error('Price data for %s at not found', ticker)
				return None
		else:
			self.logger.error('Price data for %s not found', ticker)

	def get_bar(self, ticker: str, time: Any) -> Any:
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
				self.logger.error('Price data for %s at time %s not found', ticker, str(time))
				return None
		else:
			self.logger.error('Price data for %s not found', ticker)

	def get_bars(self, ticker: str,
			start_dt: Optional[pd.Timestamp] = None,
			end_dt: Optional[pd.Timestamp] = None) -> Any:
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
			self.logger.error('Price data for %s not found', ticker)
			return None
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
			# resample_ohlcv takes a pandas offset string, not a timedelta.
			resample_rule = timedelta_to_str(timeframe) or self.timeframe
			return resample_ohlcv(self.get_bars(ticker, start_dt, time+timeframe),
						resample_rule).head(window)
		else:
			start_dt = time - (timeframe * window) + timeframe
			return self.get_bars(ticker, start_dt, time)

	def to_megaframe(self, time: pd.Timestamp, tf_delta: Any, window: int) -> Any:
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
		df_list: list[Any] = []
		for symbol in self.available_symbols:
			df = self.get_resampled_bars(time, symbol, tf_delta, window)
			df.name = symbol

			if df.index.tz is not None:
				df_list.append(df)

		megaframe = pd.concat(df_list, axis=1, keys=self.prices.keys())
		return megaframe

	## Setters

	def set_symbols(self, tickers: list[str]) -> None:
		if 'all' in tickers:
			self.symbols = self.exchange.get_tradable_symbols()
		else:
			self.symbols = tickers

	def set_timeframe(self, timeframe_strat: timedelta, timeframe_scr: timedelta) -> None:
		min_timeframe = min([timeframe_strat, timeframe_scr])
		new_timeframe = timedelta_to_str(min_timeframe)
		if new_timeframe is not None:
			self.timeframe = new_timeframe

	## Init methods
	def _init_symbols(self, symbols: list[str]) -> Any:
		"""
		Initialise the symbols

		Parameters
		----------
		symbols: `list`
			The list of symbols to be downloaded.
		"""
		# Delete duplicated symbols
		unique_symbols = np.unique(symbols)

		if 'all' in unique_symbols:
			return self.exchange.get_tradable_symbols()
		return unique_symbols

	def _init_exchange(self, exchange: str) -> Any:
		"""
		Factory method to initialise the correct exchange
		"""
		exchange_name = exchange.lower()
		if exchange_name == 'binance':
			# CCXT_exchange is a deferred subsystem (D-oanda override); its abstract
			# completeness is out of M2a scope and this branch is dormant on the csv path.
			return CCXT_exchange(exchange_name, self.base_currency)  # type: ignore[abstract]
		# elif exchange_name == 'kraken':
		# 	return CCXTKrakenExchange()
		else:
			raise NotImplementedError(f"Exchange '{exchange_name}' not implemented")
			
