import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy_utils import database_exists, create_database

from itrader import config
from itrader.logger import get_itrader_logger

class SqlHandler(object):

	def __init__(self):
		self.engine = self.init_engine()
		self.inspector = inspect(self.engine)

		self.logger = get_itrader_logger().bind(component="SQLHandler")
		self.logger.info('Price Database connected')

	def init_engine(self):
		engine = create_engine('postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices')
		if not database_exists(engine.url):
			create_database(engine.url)
		return engine

	def stop_engine(self):
		"""
		Close the SQL connection
		"""
		self.engine.dispose() # Close all checked in sessions
	
	def delete_all_tables(self):
		"""
		Delete all the tables in the prices database.
		"""
		symbols = self.get_symbols_SQL()
		connection = self.engine.connect()
		for sym in symbols:
			qry_str = text(f'DROP TABLE IF EXISTS {"%s"};'%sym)
			connection.execute(qry_str)
		connection.commit()
		connection.close()
		self.logger.info('All tables deleted.')

	def to_database(self, symbol: str, prices: pd.DataFrame, replace: bool):
		"""
		Store the downloaded prices in a SQL database

		Parameters
		----------
		symbol: `str`
			Ticker of the price data
		prices: `DataFrame`
			The DataFrame with the OHLC prices already downloaded.
		replace: `bool`
			Define if replace the old data or not
		"""
		# CHeck if replace or append the data
		if replace:
			prices.to_sql(symbol.lower(), self.engine, index = True, if_exists='replace')
		else:
			prices.to_sql(symbol.lower(), self.engine, index = True, if_exists='append')
	   
	def read_prices(self, symbol: str):
		"""
		Read prices from a SQL database

		Return
		------
			df: `DataFrame`
		"""
		with self.engine.connect() as connection:
			df = pd.read_sql(symbol, connection, index_col='date')
		df.index = pd.to_datetime(df.index, utc=True).tz_convert('Europe/Paris')
		df.index.freq = df.index.inferred_freq
		return df
	
	def get_symbols_SQL(self):
		"""
		Obtain the list of all Pairs prices in the SQL database.

		Returns
		-------
		list`[str]`
			The list of all coins.
		"""
		self.inspector.clear_cache()
		return self.inspector.get_table_names()