import ccxt
import pytz
import pandas as pd
from datetime import datetime

from .base import AbstractExchange
from itrader.outils.time_parser import to_timedelta
from itrader.config import FORBIDDEN_SYMBOLS
from itrader import config

class CCXT_exchange(AbstractExchange):
	"""
	This Exchange class allows to fetch data from all
	the exchanges supported by the CCXT library.

	It's mainly used to get crypto data from a defined 
	exchange.
	"""
	def __init__(self, name: str, currency: str):
		self.exchange = getattr(ccxt, name)()
		self.currency = currency
		self.markets = self.exchange.load_markets()


	def get_tradable_symbols(self) -> list:
		"""
		Get a list of all available symbol on the exchange.
		"""
		# Extract symbols from the loaded markets
		try:
			tradable_symbols = list(self.markets.keys())
		except ccxt.NetworkError as e:
			raise RuntimeError(f"Network error: {e}")
		except ccxt.ExchangeError as e:
			raise RuntimeError(f"Exchange error: {e}")
		except Exception as e:
			raise RuntimeError(f"An error occurred: {e}")

		# Define symbols to be excluded
		contains = ['UP', 'DOWN','BEAR','BULL', '1000', ':']
		exclude = FORBIDDEN_SYMBOLS.get(self.currency, [])

		# Filter only tradeble assets
		symbols = [
			symbol.replace('/', '')  # Remove the slash
			for symbol in tradable_symbols
			if symbol.endswith(self.currency) and  # Exclude tickers not in the base currency
			symbol not in exclude and  # Exclude symbols in the 'exclude' list
			not any(substring in symbol for substring in contains) and  # Exclude futures symbols
        	self.markets[symbol]['active']  # Check if the symbol is active
		]
		return symbols

	@staticmethod
	def _format_data(data: pd.DataFrame, timeframe: str) -> pd.DataFrame:
		"""
		Clean and format the data downloaded data from CCXT.
		# TODO: check if this format is valid also for other exchanges

		Returns
		-------
		df: `DataFrame`
			Dataframe with Date-OHLCV.
		"""
		# Name columns
		data.columns=['date','open','high','low','close','volume']

		# Format index
		data = data.set_index('date') 
		data.index = pd.to_datetime(data.index, unit='ms', utc=True)
		data.index = data.index.tz_convert(config.TIMEZONE)

		# Change data type and deal with NaN values or duplicates
		data = data.astype(float)
		data = data.drop_duplicates()
		data.fillna(method='ffill', inplace=True)

		# Resample index for missing data
		df_resampled = data.iloc[:, :5].resample(to_timedelta(timeframe)).ffill()

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
			End date since when to download the price data
		"""
		# Convert start_date to UNIX format
		if isinstance(start_date, str):
			since = round(datetime.strptime(str(start_date), '%Y-%m-%d %H:%M').timestamp()*1000)
		else:
			dt_utc = start_date.astimezone(pytz.UTC)
			since = round(dt_utc.timestamp() * 1000)

		# Format the symbol string in a CCXT compatible format "BTC/USDT"
		ccxt_symbol = symbol.upper()[:-4] + '/' + symbol.upper()[-4:]

		ohlcv_list = []
		if self.exchange.has['fetchOHLCV']:
			ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, since=since, limit=1000)
			ohlcv_list.extend(ohlcv)
			while(len(ohlcv)==1000):
				last_ts = ohlcv[-1][0]
				ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, since=last_ts, limit=1000)
				ohlcv_list.extend(ohlcv)

		# Convert the list to a DataFrame and format the data
		raw_data = pd.DataFrame(ohlcv_list)
		if len(raw_data) > 0 :
			data = self._format_data(raw_data, timeframe)
			return data
		