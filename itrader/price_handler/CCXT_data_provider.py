import datetime as dt
from tqdm import tqdm

import ccxt

import numpy as np
import pandas as pd


from ..outils.price_parser import PriceParser
from .base import AbstractBarPriceHandler
from .base import SqlHandler
from ..instances.event import BarEvent


class CCXT_data_provider(AbstractBarPriceHandler):
    """
    CCXT_data_provider is designed to download data from the defined
    exchange. It contains Open-High-Low-Close-Volume (OHLCV) data
    for each pair and streams those to the provided events queue as BarEvents.


    Parameters
    -----------------------------------------
    
    exchange : `str`
        Exchange from where download datas.
    
    symbols : `list`
            The list of symbols to be downloaded.

    timeframes : 'str'
        The time frame for the analysis

    start_dt : 'str'
        The start date of the analysis
    
    end_dt : 'str'
        The End date of the analysis

    events_queue : 'object'
    """
    
    def __init__(self, exchange, symbols, timeframe='1d', start_dt='', end_dt='',
                events_queue = None):

        self.exchange = self._set_exchange(exchange)
        self.symbols = self._define_symbols(symbols)
        self.timeframe = timeframe
        self.start_date = start_dt
        self.end_date = end_dt
        self.prices = {}
        self.sql_handler = SqlHandler()
        #self.download_data()
        #self.bar_stream = self._merge_sort_ticker_data()

        self.tickers = self._initialize_tickers()
        self.continue_backtest = True
        self.events_queue = events_queue
        
        



    # Backtest Methods

    def download_data(self):
        """
        Download price data with CCXT and store them in a dict

        Returns
        -------
        `prices {'ticker' : DataFrame}`
            Dataframe with Date-OHLCV-Symbol.
        """
        sym = self.sql_handler.get_symbols_SQL()

        if sym == self.symbols:
            # Symbol already present in the SQL db
            print('Data already downloaded')
            for symbol in tqdm(self.symbols):
                self.prices[symbol] = self.sql_handler.read_prices(symbol.lower()) #
        else:
            print('Data not present')
            for symbol in tqdm(self.symbols):
                ccxt_symbol = symbol[:-4] + '/' + symbol[-4:]
                self.prices[symbol] = self._get_data_CCXT(ccxt_symbol)
                self.prices[symbol]['Ticker'] = symbol
            self.sql_handler.to_database(self.prices)
    
    def _define_symbols(self, symbols):
        """
        Define the symbols to be traded
        """
        if symbols[0]=='all':
            tickers = self.get_all_symbols()
        else:
            tickers = symbols
        return tickers

    def _transform_data(self, data):
        """
        Clean and format the data downloaded from CCXT.

        Returns
        -------
        `data [DataFrame]`
            Dataframe with Date-OHLCV-Adj.
        """
        #data = data.iloc[:,:6]
        data.columns=['Date','Open','High','Low','Close', 'Volume']
        data = data.set_index('Date') 
        data.index = pd.to_datetime(data.index, unit='ms', utc=True)
        data = data.astype(float)
        return data


    def _get_data_CCXT(self, symbol):
        start_dt = self.exchange.parse8601(self.start_date + ' 00:00:00')
            
        if self.end_date == '':
            ohlcv_list = []
            if self.exchange.has['fetchOHLCV']:
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, since=start_dt, limit=1000)
                ohlcv_list.extend(ohlcv)
                while(len(ohlcv)==1000):
                    last_ts = ohlcv[-1][0]
                    #time.sleep(1)
                    ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, since=last_ts, limit=1000)
                    ohlcv_list.extend(ohlcv)
        else:
            print('To be implemented')
        data = pd.DataFrame(ohlcv_list)
        if len(data) > 0 :
            data = self._transform_data(data)
        return data
 

    def _initialize_tickers(self):
        ticker_prices={}
        for ticker in self.symbols:
            ticker_prices[ticker]= {
                'open': None,
                'high': None,
                'low' : None,
                "close": None,
                "adj_close": None,
                "timestamp": None}
        return ticker_prices


    def resample_prices(self, symbols, timeframe):
        """
        Obtain the list of all Pairs prices in the SQL database.
        
        Parameters
        -------
        symbols ['str']
            The list of coins to be resampled.
        timeframe 'str'
            The new timeframe after resample.

        Returns
        -------
        `prices {'ticker' : [DataFrame]}`
            Dictionary with a df Date-OHLCV for each symbol.
        """
        prices_res = {}
        for symbol in symbols:
            df = self.prices[symbol]
            # Resample
            prices_res[symbol] = df.resample(timeframe).agg({'Open':'first',
                                                         'High':'max',
                                                         'Low':'min',
                                                         'Close':'last'})
            # Add column 'Ticker'
            #prices[symbol]['Ticker'] = symbol
        return prices_res


# ******* CCXT methods ******
    def _set_exchange(self, exchange):
        """
        Set the exchange from where download the data
        """
        exchange = getattr(ccxt, exchange)()
        test = exchange.fetch_ticker('ETH/BTC')
        #markets = exchange.load_markets()
        return exchange

    def get_all_symbols(self):
        """
        Obtain the list of all pairs prices available in the
        exchange defined for CCXT.

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        symbols = self.exchange.symbols
        exclude = ['UP', 'DOWN','BEAR','BULL','BUSDUSDT','TUSDUSDT','GBPUSDT',
                'USDPUSDT','USDCUSDT','PAXUSDT','USDSUSDT','USDSBUSDT','USTUSDT',
                '1INCHUSDT', 'TUSDT', 'PAXGUSDT']

        relevant = [symbol for symbol in symbols if symbol.endswith('USDT')]
        relevant = [symbol for symbol in relevant if all(excludes not in symbol for excludes in exclude)]
        return relevant


# ******* Event manager ******
    def _merge_sort_ticker_data(self):
        """
        Concatenates all of the separate equities DataFrames
        into a single DataFrame that is time ordered, allowing tick
        data events to be added to the queue in a chronological fashion.

        Note that this is an idealised situation, utilised solely for
        backtesting. In live trading ticks may arrive "out of order".
        """
        df = pd.concat(self.prices.values()).sort_index()
        start = None
        end = None
        if self.start_date is not None:
            start = df.index.searchsorted(self.start_date)
        if self.end_date is not None:
            end = df.index.searchsorted(self.end_date)
        # This is added so that the ticker events are
        # always deterministic, otherwise unit test values
        # will differ
        df['colFromIndex'] = df.index
        df = df.sort_values(by=["colFromIndex", "Ticker"])

        if start is None and end is None:
            return df.iterrows()
        elif start is not None and end is None:
            return df.iloc[start:].iterrows()
        elif start is None and end is not None:
            return df.iloc[:end].iterrows()
        else:
            return df.iloc[start:end].iterrows()


    def _create_event(self, index, period, ticker, row):
        """
        Obtain all elements of the bar from a row of dataframe
        and return a BarEvent
        """
        open_price = PriceParser.parse(row["Open"])
        high_price = PriceParser.parse(row["High"])
        low_price = PriceParser.parse(row["Low"])
        close_price = PriceParser.parse(row["Close"])
        adj_close_price = PriceParser.parse(row["Close"])
        volume = int(row["Volume"])
        bev = BarEvent(
            ticker, index, period, open_price,
            high_price, low_price, close_price,
            volume, adj_close_price
        )
        return bev
    

    def _store_event(self, event):
        """
        Store price event for closing price and adjusted closing price
        """
        ticker = event.ticker
        self.tickers[ticker]["open"] = event.open_price
        self.tickers[ticker]["high"] = event.high_price
        self.tickers[ticker]["low"] = event.low_price
        self.tickers[ticker]["close"] = event.close_price
        self.tickers[ticker]["adj_close"] = event.adj_close_price
        self.tickers[ticker]["timestamp"] = event.time


    def stream_next(self):
        """
        Place the next BarEvent onto the event queue.
        """
        try:
            index, row = next(self.bar_stream)
        except StopIteration:
            self.continue_backtest = False
            return
        # Obtain all elements of the bar from the dataframe
        ticker = row["Ticker"]
        period = 86400  # Seconds in a day
        # Create the tick event for the queue
        bev = self._create_event(index, period, ticker, row)
        # Store event
        self._store_event(bev)
        # Send event to queue
        self.events_queue.put(bev)