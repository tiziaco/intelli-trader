from __future__ import print_function
from abc import ABCMeta

from tqdm import tqdm
import pandas as pd
from datetime import datetime, timedelta
import re

from sqlalchemy import create_engine
from sqlalchemy_utils import database_exists, create_database

class AbstractPriceHandler(object):
    """
    PriceHandler is a base class providing an interface for
    all subsequent (inherited) data handlers (both live and historic).

    The goal of a (derived) PriceHandler object is to output a set of
    TickEvents or BarEvents for each financial instrument and place
    them into an event queue.

    This will replicate how a live strategy would function as current
    tick/bar data would be streamed via a brokerage. Thus a historic and live
    system will be treated identically by the rest of the QSTrader suite.
    """

    __metaclass__ = ABCMeta

    def unsubscribe_ticker(self, ticker):
        """
        Unsubscribes the price handler from a current ticker symbol.
        """
        try:
            self.tickers.pop(ticker, None)
            self.tickers_data.pop(ticker, None)
        except KeyError:
            print(
                "Could not unsubscribe ticker %s "
                "as it was never subscribed." % ticker
            )

    def get_last_timestamp(self, ticker):
        """
        Returns the most recent actual timestamp for a given ticker
        """
        if ticker in self.tickers:
            timestamp = self.tickers[ticker]["timestamp"]
            return timestamp
        else:
            print(
                "Timestamp for ticker %s is not "
                "available from the %s." % (ticker, self.__class__.__name__)
            )
            return None



class PriceHandler(AbstractPriceHandler):

    # Define global class variables 
    prices = {}
    symbols = []
    timeframe = None
    tf_delta = None

    def get_last_close(self, ticker):
        """
        Returns the most recent actual (unadjusted) closing price.
        """
        if ticker in self.tickers:
            close_price = self.tickers[ticker]["close"]
            return close_price
        else:
            print("Close price for ticker %s is not available")
            return None
    
    def get_last_bar(self, ticker):
        """
        Returns the most recent actual (unadjusted) closing price.
        """
        if ticker in self.tickers:
            last_bar = self.tickers[ticker]
            return last_bar
        else:
            print("Bar data for ticker %s is not available")
            return None
    
    @staticmethod
    def _adjust_timeframe(timeframe):
        # Splitting text and number in string
        temp = re.compile("([0-9]+)([a-zA-Z]+)")
        res = temp.match(timeframe).groups()
        if res[1] == 'm':
            temp = 'min'
            return (res[0] + temp)
        else:
            return timeframe
    

    @staticmethod
    def _get_delta(timeframe):
        """
        Transform the str timeframe in a `timedelta` object.

        Parameters
        ----------
        timeframe: `str`
            Timeframe of the strategy

        Returns
        -------
        delta: `TimeDelta` object
            The time delta corresponding to the timeframe.
        """
        
        # Splitting text and number in string
        temp = re.compile("([0-9]+)([a-zA-Z]+)")
        res = temp.match(timeframe).groups()
        if res[1] == 'd':
            delta = eval(f'timedelta(days={res[0]})')
        elif res[1] == 'h':
            delta = eval(f'timedelta(hours={res[0]})')
        elif res[1] == 'm':
            delta = eval(f'timedelta(minutes={res[0]})')
        else:
            print('WARNING: timeframe not suppoerted') #TODO implementare log ERROR
        return delta
    
    


class SqlHandler(object):

    # Define the database's engine
    engine = create_engine('postgresql+psycopg2://postgres:1234@localhost:5432/trading_system_prices')
    if not database_exists(engine.url):
        create_database(engine.url)


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
        for sym in symbols:
            qry_str = f'DROP TABLE IF EXISTS "%s";'%sym
            self.engine.execute(qry_str)
        # TODO: da sostituire con logger
        print(' price table deleted')


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
        if replace:
            # Storing new data, replace de old one
            prices.to_sql(symbol.lower(), self.engine, index = True, if_exists='replace')
        else:
            # Updating the data, append the new one
            prices.to_sql(symbol.lower(), self.engine, index = True, if_exists='append')

       
    def read_prices(self, symbol: str):
        """
        Read prices from a SQL database

        Return
        ------
            df: `DataFrame`
        """
        qry_str = f'SELECT * FROM "{symbol}"'
        df = pd.read_sql(qry_str, self.engine, index_col='date')
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
        return self.engine.table_names()

