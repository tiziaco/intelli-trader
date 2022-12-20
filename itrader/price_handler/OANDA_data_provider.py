import functools
import os
import datetime as dt
from tqdm import tqdm

import numpy as np
import pandas as pd
import pytz
from qstrader import settings

import tpqoa
from qstrader.price_handler import config

from ..price_parser import PriceParser
from .base import AbstractBarPriceHandler
from ..event import BarEvent
from ..event import TickEvent


class OANDA_data_provider(AbstractBarPriceHandler, tpqoa.tpqoa):
    """
    OANDA_data_provider is designed to download data from the
    OANDA server. It contains Open-High-Low-Close-Volume (OHLCV) data
    for each pair and streams those to the provided events queue as BarEvents.


    Parameters
    -----------------------------------------
    
    asset_type : `object`
        The asset type that the price/volume data is for.
        TODO: Unused at this stage
    
    symbols : `list`
            The list of symbols to be downloaded.

    timeframes : 'list'
        The time frame for the analysis

    start_dt : 'DateTime'
        The start date of the analysis
    
    end_dt : 'DateTime'
        The End date of the analysis
    """


    
    def __init__(self, events_queue, symbols, timeframes, start_dt, end_dt='', 
                calc_adj_returns=False, init_tickers=None,
                conf_file = r"C:\Users\tizia\anaconda3\envs\spyder-env\qstrader\price_handler\oanda.cfg",
                bar_length= '5s'):#, asset_type
        # Connect APIs
        super().__init__(conf_file)

        # Live attributes
        self.bar_length = pd.to_timedelta(bar_length) # Pandas Timedelta Object
        self.tick_data = pd.DataFrame()
        self.data = pd.DataFrame()
        self.last_bar = pd.to_datetime(dt.datetime.utcnow()).tz_localize("UTC") # UTC time at instantiation

        # Backtest attributes
        self.events_queue = events_queue
        self.continue_backtest = True
        self.symbols = symbols
        self.tickers = {}
        self.timeframe = timeframes[0]
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.prices = self._load_prices_dict()
        self.bar_stream = self._merge_sort_ticker_data()
        self.calc_adj_returns = calc_adj_returns
        if self.calc_adj_returns:
            self.adj_close_returns = []
        if init_tickers is not None:
            for ticker in symbols:
                self.subscribe_ticker(ticker)
        
    # Live methods
    def on_success(self, time, bid, ask):
        print(self.ticks, end = " ")
        #print("Time: {} | Bid: {} | Ask:{}".format(time, bid, ask))

        # collect and store tick data
        recent_tick = pd.to_datetime(time, utc=True)
        df = pd.DataFrame({"bid":bid, "ask":ask, "mid":(ask + bid)/2}, 
                          index = [pd.to_datetime(time, utc=True)])
        self.tick_data = pd.concat([self.tick_data, df])

        # if a time longer than the bar_lenght has elapsed between last full bar and the most recent tick
        if recent_tick - self.last_bar > self.bar_length:
            self._resample_and_join()
    
    def _resample_and_join(self):
        """
        Resample live tick data in a ordered df with an interval of 5s
        """
        self.data = pd.concat([self.data, self.tick_data.resample(self.bar_length, 
                                                             label="right").last().ffill().iloc[:-1]])
        self.tick_data = self.tick_data.iloc[-1:] # Only keep the latest tick (next bar)
        self.last_bar = self.data.index[-1]


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
        if self.start_dt is not None:
            start = df.index.searchsorted(self.start_dt)
        if self.end_dt is not None:
            end = df.index.searchsorted(self.end_dt)
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


    def _load_data_OANDA(self, symbol):
        """
        Download prices for one ticker and format the data
        """
        # Set current time if not passed
        if self.end_dt == '':
            self.end_dt = dt.datetime.now().strftime("%Y-%m-%d")# %H:%M

        # Download data
        df = self.get_history(symbol, self.start_dt, self.end_dt, self.timeframe, 'B')
        df = df.drop('complete', axis=1)
        df = df.reset_index()
        df = df.rename(columns={'time':'Date', 'o':'Open','h':'High','l':'Low','c':'Close','volume':'Volume'})
        df = df.set_index('Date')
        df['Adj Close'] = df['Close']

        return df
 
    
    def _load_prices_dict(self):
        """
        Downoal data from OANDA and insert them in a dictionary

        Returns
        -------
        `data [DataFrame]`
            Dataframe with Date-OHLCV-Adj.
        """
        asset_frames = {}
        for symbol in tqdm(self.symbols):
            asset_frames[symbol] = self._load_data_OANDA(symbol)
            asset_frames[symbol]["Ticker"] = symbol
        return asset_frames

    
    def subscribe_ticker(self, ticker):
        """
        Subscribes the price handler to a new ticker symbol.
        """
        if ticker not in self.tickers:
            try:
                #self._open_ticker_price_csv(ticker)
                dft = self.prices[ticker]
                row0 = dft.iloc[0]

                close = PriceParser.parse(row0["Close"])
                adj_close = PriceParser.parse(row0["Adj Close"])

                ticker_prices = {
                    "close": close,
                    "adj_close": adj_close,
                    "timestamp": dft.index[0]
                }
                self.tickers[ticker] = ticker_prices
            except OSError:
                print(
                    "Could not subscribe ticker %s "
                    "as no data CSV found for pricing." % ticker
                )
        else:
            print(
                "Could not subscribe ticker %s "
                "as is already subscribed." % ticker
            )

    def get_all_symbols(self):
        """
        !!! DOESN'T WORK

        Obtain the list of all pairs prices available in the
        OANDA server.

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        symbols=self.api.get_instruments()
        
        return symbols
    
    def get_pairs(self):
        """
        !!! DOESN'T WORK

        Obtain the list of all pairs stored in the prices dict.

        Returns
        -------
        `list[str]`
            The list of all pairs.
        """
        return self.prices[0]
        


    def _obtain_coins_SQL_db(self):
        """
        Obtain the list of all Pairs prices in the SQL database.
        
        TODO: Not ready!!!

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        return []


    def get_assets_historical_closes(self, start_dt, end_dt, assets):
        """
        Return a multi-asset historical range of closing prices as a DataFrame,
        indexed by timestamp with asset symbols as columns.

        Parameters
        ----------
        start_dt : `pd.Timestamp`
            The starting datetime of the range to obtain.
        end_dt : `pd.Timestamp`
            The ending datetime of the range to obtain.
        assets : `list[str]`
            The list of asset symbols to obtain closing prices for.

        Returns
        -------
        `pd.DataFrame`
            The multi-asset closing prices DataFrame.
        """
        close_series = []
        for asset in assets:
            if asset in self.prices.keys():
                asset_close_prices = self.prices[asset][['Close']]
                asset_close_prices.columns = [asset]
                close_series.append(asset_close_prices)

        prices_df = pd.concat(close_series, axis=1).dropna(how='all')
        prices_df = prices_df.loc[start_dt:end_dt]
        prices_df = close_series #TEST
        return prices_df


# ******* Event manager ******
    def _create_event(self, index, period, ticker, row):
        """
        Obtain all elements of the bar from a row of dataframe
        and return a BarEvent
        """
        open_price = PriceParser.parse(row["Open"])
        high_price = PriceParser.parse(row["High"])
        low_price = PriceParser.parse(row["Low"])
        close_price = PriceParser.parse(row["Close"])
        adj_close_price = PriceParser.parse(row["Adj Close"])
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
        # If the calc_adj_returns flag is True, then calculate
        # and store the full list of adjusted closing price
        # percentage returns in a list
        # TODO: Make this faster
        if self.calc_adj_returns:
            prev_adj_close = self.tickers[ticker][
                "adj_close"
            ] / float(PriceParser.PRICE_MULTIPLIER)
            cur_adj_close = event.adj_close_price / float(
                PriceParser.PRICE_MULTIPLIER
            )
            self.tickers[ticker][
                "adj_close_ret"
            ] = cur_adj_close / prev_adj_close - 1.0
            self.adj_close_returns.append(self.tickers[ticker]["adj_close_ret"])
        #print(self.tickers) #test
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