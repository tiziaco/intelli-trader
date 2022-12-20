from __future__ import print_function
from abc import ABCMeta

from tqdm import tqdm
import pandas as pd
import datetime as dt

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


class AbstractTickPriceHandler(AbstractPriceHandler):
    def istick(self):
        return True

    def isbar(self):
        return False

    def _store_event(self, event):
        """
        Store price event for bid/ask
        """
        ticker = event.ticker
        self.tickers[ticker]["bid"] = event.bid
        self.tickers[ticker]["ask"] = event.ask
        self.tickers[ticker]["timestamp"] = event.time

    def get_best_bid_ask(self, ticker):
        """
        Returns the most recent bid/ask price for a ticker.
        """
        if ticker in self.tickers:
            bid = self.tickers[ticker]["bid"]
            ask = self.tickers[ticker]["ask"]
            return bid, ask
        else:
            print(
                "Bid/ask values for ticker %s are not "
                "available from the PriceHandler." % ticker
            )
            return None, None


class AbstractBarPriceHandler(AbstractPriceHandler):
    def istick(self):
        return False

    def isbar(self):
        return True

    def _store_event(self, event):
        """
        Store price event for closing price and adjusted closing price
        """
        ticker = event.ticker
        self.tickers[ticker]["close"] = event.close_price
        self.tickers[ticker]["adj_close"] = event.adj_close_price
        self.tickers[ticker]["timestamp"] = event.time

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


class SqlHandler(object):
    engine = create_engine('postgresql+psycopg2://postgres:1234@localhost:5432/trading_system/prices')
    if not database_exists(engine.url):
        create_database(engine.url)

    # Close the SQL connection
    def stop_engine(self):
        self.engine.dispose() # Close all checked in sessions
    
    def delete_all_tables(self):
        symbols = self.get_symbols_SQL()
        for sym in symbols:
            qry_str = f'DROP TABLE IF EXISTS %s;'%sym
            self.engine.execute(qry_str)
    
    def read_last_date(engine, symbol):
        """
        Get most recent Date stored in prices SQL database. 

        Used in "_load_prices_sql"

        Return:
            Timestamp
        """
        # TODO: importare tutte le colonne, non solo data
        qry_str = f"""SELECT Date FROM {symbol} ORDER BY Date DESC LIMIT 1""" 
        df = pd.read_sql(qry_str, engine, index_col='Date')
        df.index = pd.to_datetime(df.index)
        return df.index[0]

    def _check_last(self):
        """
            Check if the download prices stored in the SQL database are updated
            to the last available bar

            Used in "_load_prices_sql"
            #TODO: implementare data provider più veloce
            Return:
                Timestamp
        """
        while True: # repeat until we get all historical bars
            update=0
            for symbol in tqdm(self.symbol_def):
                now = pd.to_datetime(dt.datetime.utcnow())
                now = now - dt.timedelta(microseconds = now.microsecond)
                last_bar = self.read_last_date(self.engine, symbol)

                if now - last_bar > self.bar_length :
                    update += 1
                    df = self._load_data_binance(symbol, last_bar.strftime("%Y-%m-%d %H:%M"), '')
                    df.to_sql(symbol, self.engine, index = True, if_exists='append')
            print(update)
            if update == 0:
                break

    def to_database(self, prices):
        """
        Store the downloaded prices in a SQL database
        Parameters
        ----------
        prices : `dict`
            The dictionary with the OHLC prices already downloaded.
        """

        for symbol in tqdm(prices):
            df = prices[symbol]
            if len(df) > 0 :
                #TEST (20/12/2022): salvo il ticker in minuscolo
                df.to_sql(symbol.lower(), self.engine, index = True, if_exists='replace')

       
    def read_prices(self, symbol):
        """
        Read prices from a SQL database
        Return:
            df DataFrame
        """
        qry_str = f"""SELECT * FROM {symbol}""" 
        df = pd.read_sql(qry_str, self.engine, index_col='Date')
        df.index = pd.to_datetime(df.index)
        return df

    
    def resample_SQL(self, symbols, timeframe):
        """
        # TODO: da testare resample da query SQL

        Obtain the list of all Pairs prices in the SQL database.
        
        Parameters
        -------
        `symbols[str]`
            The list of coins to be loaded.

        Returns
        -------
        `prices {'ticker' : [DataFrame]}`
            Dictionary with a df Date-OHLCV-Adj for each symbol.
        """
        prices = {}
        for symbol in symbols:
            df = self.read_prices(symbol)
            # Resample
            prices[symbol] = df.resample(timeframe).agg({'Open':'first',
                                                         'High':'max',
                                                         'Low':'min',
                                                         'Close':'last'})
            # Add column 'Ticker'
            #prices[symbol]['Ticker'] = symbol
        return prices

    def get_symbols_SQL(self):
        """
        Obtain the list of all Pairs prices in the SQL database.

        Returns
        -------
        list`[str]`
            The list of all coins.
        """
        return self.engine.table_names()