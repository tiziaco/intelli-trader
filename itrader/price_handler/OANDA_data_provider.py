#from datetime import datetime
from datetime import datetime, timedelta
import pytz

from tqdm import tqdm

import tpqoa

import numpy as np
import pandas as pd

from .base import PriceHandler
from .base import SqlHandler

import logging
logger = logging.getLogger('TradingSystem')


class OANDA_data_provider(PriceHandler):
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
    
    def __init__(self, exchange, symbols=[], timeframe=None, start_dt='', end_dt='',
                global_queue = None, base_currency='USD'):

        self.base_currency = base_currency
        
        self.exchange = tpqoa.tpqoa('oanda.cfg')
        self.set_symbols(symbols)
        self.set_timeframe(timeframe)
        self.start_date = start_dt
        self.end_date = end_dt

        self.sql_handler = SqlHandler()
        #self.live_data = BINANCELiveStreamer(global_queue)
        
        logger.info('PRICE HANDLER: OANDA => OK')

    
    def download_data(self):
        """
        Download price data with CCXT and store them in a dict with
        the following format: {'ticker' : DataFrame}
        """
        logger.info('PRICE HANDLER: Downoalding data')

        PriceHandler.prices={}
        # Read the list of coins stored in the db
        sql_symblos = self.sql_handler.get_symbols_SQL()
        symbols = list(map(lambda x: x.lower(), PriceHandler.symbols))

        for symbol in tqdm(symbols):
            if symbol in sql_symblos:
                # Symbol already present in the SQL db
                PriceHandler.prices[symbol.upper()] = self.sql_handler.read_prices(symbol)
            else:
                # Symbol not present in the SQL db. Download them with CCXT
                self._get_data_OANDA(symbol, self.start_date)
    
        # Update data to tha last available date
        #self.update_data()
    
    def update_data(self):
        """
        Update the price data
        """
        logger.info('PRICE HANDLER: Updating data...')
        timezone = pytz.timezone('Europe/Paris')

        while True: # repeat until we get all historical bars
            update=0
            for ticker in self.prices.keys():
                # Get the current UTC time
                now = pd.to_datetime(datetime.utcnow())

                # Make it timezone aware
                now = now.replace(tzinfo=pytz.utc).astimezone(timezone)

                # Calculate the bar expiration time
                now = now - timedelta(microseconds = now.microsecond)
                last_date = self.prices[ticker].index[-1]

                if now - last_date > self.tf_delta :
                    update += 1
                    self._get_data_OANDA(ticker, self.start_date, replace=False)
            if update == 0:
                logger.info('PRICE HANDLER: Price updated')
                break
        

    def set_symbols(self, tickers: list):
        """
        Recive the tickers to be downloaded from the Strategy Handler
        when a static universe is used

        Parameters
        ----------
        symbols: `list`
            The list of symbols to be downloaded.
        """
        symbols = np.unique(tickers)

        if 'all' in symbols:
            PriceHandler.symbols = self.get_all_symbols()
        else:
            PriceHandler.symbols = symbols


    def set_timeframe(self, timeframe: str):
        """
        Set the timeframe as a string and timedelta object in the 
        parent class.

        Parameters
        ----------
        timeframe: `str`
            The timeframe of the price data.
        """
        if timeframe is not None:
            PriceHandler.timeframe = timeframe
            PriceHandler.tf_delta = self._get_delta(timeframe)


    
 
#******* Data Manipulation ***************

    def resample_price(self, df: pd.DataFrame, timedelta: timedelta):
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
        return df.resample(timedelta).agg(
            {'open':'first',
            'high':'max',
            'low':'min',
            'close':'last',
            'volume': 'sum'})
    
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
        if ticker in PriceHandler.prices.keys():
            try:
                last_prices = PriceHandler.prices[ticker].loc[time]
                return last_prices
            except:
                logger.error('PRICE HANDLER: data for %s at time %s not found', ticker, str(time))
                return None
        else:
            logger.error('PRICE HANDLER: data for %s not found', ticker)
    
    def get_bars(self, ticker, start_dt, end_dt):
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
        if ticker in PriceHandler.prices.keys():
            return PriceHandler.prices[ticker].loc[start_dt : end_dt]
        else:
            logger.error('PRICE HANDLER: data for %s not found', ticker)
    
    def get_and_resample_bars(self, time, ticker, tf_delta, window) -> pd.DataFrame:
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
        # Check if the requested timeframe is the same of the stored data
        if tf_delta != PriceHandler.tf_delta:
            ratio = tf_delta / PriceHandler.tf_delta
            start_dt = (time - PriceHandler.tf_delta * window * ratio)
            return self.resample_price(self.get_bars(ticker, start_dt+tf_delta, time+tf_delta), tf_delta).head(window)
        else:
            start_dt = time - tf_delta * window
            return self.get_bars(ticker, start_dt+tf_delta, time)
    
    def get_megaframe(self, time, tf_delta, window):
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
        frame: 'DataFrame'
            DataFrame with prices data of all the stored symbols
        """
        df_list=[]
        for symbol in self.prices.keys():
            df = self.get_and_resample_bars(time, symbol, tf_delta, window)
            df.name = symbol
            if df.index.tz is not None:
                df_list.append(df)
        frame = pd.concat(df_list, axis=1, keys=self.prices.keys())
        return frame


# ******* OANDA methods ******

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


    def _transform_data(self, data: pd.DataFrame):
        """
        Clean and format the data downloaded from CCXT.

        Returns
        -------
        df: `DataFrame`
            Dataframe with Date-OHLCV.
        """
        data.columns=['date','open','high','low','close','volume']
        data = data.set_index('date') 
        data.index = pd.to_datetime(data.index, unit='ms', utc=True)# + timedelta(hours=1)
        data.index = data.index.tz_convert('Europe/Paris')

        # change data type and deal with NaN values or duplicates
        data = data.astype(float)
        data = data.drop_duplicates()
        data.fillna(method='ffill', inplace=True)

        # Resample index for missing data
        df_resampled = data.iloc[:, :4].resample(self.tf_delta).ffill()
        df_resampled['volume'] = data['volume']
        df_resampled['volume'] = df_resampled['volume'].fillna(0)
        df_resampled

        #data.index.freq = data.index.inferred_freq
        return df_resampled

    def _get_data_OANDA(self, symbol: str, start_date: str, end_date: str, replace=True):
        """
        Download and format the data for the defined tickers.

        Parameters
        ----------
        symbol: `str`
            The ticker symbol, e.g. 'EUR_USD'
        start_date, end_date: `str`
            Start and end date since when to download the price data
        replace: `bool`
            Define if replace the old data or not
        """
        # Set current time if not passed
        if end_date == '':
            end_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Download data
        df = self.exchange.get_history(symbol, start_date, end_date, self.timeframe, 'B')
        df = df.drop('complete', axis=1)
        df = df.reset_index()
        df = df.rename(columns={'time':'date', 'o':'open','h':'high','l':'low','c':'close','volume':'volume'})
        df = df.set_index('Date')

        if len(df) > 0 :
            # Format and clean the DataFrame
            #PriceHandler.prices[symbol.upper()] = self._transform_data(data)

            # Store the df in the sql database
            self.sql_handler.to_database(symbol, PriceHandler.prices[symbol.upper()], replace)