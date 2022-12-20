import functools
import os
import datetime as dt
from tqdm import tqdm

import websocket, json
from sqlalchemy import create_engine

import numpy as np
import pandas as pd
import pytz
from qstrader import settings

from binance.client import Client
from qstrader.price_handler import config

from ..price_parser import PriceParser
from .base import AbstractBarPriceHandler
from ..event import BarEvent


class BINANCE_data_provider(AbstractBarPriceHandler):
    """
    BINANCE_data_provider is designed to download data from the
    BINANCE server. It contains Open-High-Low-Close-Volume (OHLCV) data
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


    
    def __init__(self, events_queue, symbols=[], timeframes=['1DAY'], start_dt='', end_dt='', 
                calc_adj_returns=False, init_tickers=None, bar_length='1m'):#, asset_type
        self.client = Client(config.API_KEY, config.API_SECRET)
        self.engine = create_engine('sqlite:///prices.db')
        
        self.events_queue = events_queue
        self.continue_backtest = True
        if symbols=='all':
            self.symbols = self.get_all_symbols()
        else:
            self.symbols = symbols
        self.tickers = {}
        self.timeframe = timeframes[0]
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.prices = self._load_prices_dict()
        if start_dt !='':   #Aggiunto per non scaricare i dati con live mode
            #self.prices = self._load_prices_sql()
            self.prices = self._load_prices_dict()
            #self.bar_stream = self._merge_sort_ticker_data()
        self.calc_adj_returns = calc_adj_returns
        if self.calc_adj_returns:
            self.adj_close_returns = []
        if init_tickers is not None:
            for ticker in symbols:
                self.subscribe_ticker(ticker)
        # Live attributes
        self.ticks=0
        self.bar_length = pd.to_timedelta(bar_length)
        self.tick_data = {}
        self.sampled_data = {}
        self.last_bar = pd.to_datetime(dt.datetime.utcnow()).tz_localize("UTC") # UTC time at instantiation
    
    # Live Methods
    def stream_data(self):
        #self.prices = self._load_prices_dict()  #Gia presente in __init__

        def on_message(ws, message):
            msg = json.loads(message)
            self.test=msg
            self.ticks += 1
            print(self.ticks, end=' ')

            for x in msg :
                if x['s'] in self.symbols:
                    # collect and store tick data
                    self._store_tick(x)
                    recent_tick=self.tick_data[x['s']].index[-1]

            # if a time longer than the bar_lenght has elapsed between last full bar and the most recent tick
            #if recent_tick - self.last_bar > self.bar_length:   #OLD
            if recent_tick.minute != self.last_bar.minute:  #NEW
                for symbol in self.tick_data.keys():
                    self._resample_and_join(symbol)
                    print('last='+self.last_bar.minute)
                    print('recent='+recent_tick.minute)
            
        stream = 'wss://stream.binance.com:9443/ws/!miniTicker@arr'
        ws = websocket.WebSocketApp(stream, on_message=on_message)
        ws.run_forever()
    
    def _store_tick(self, x):
        """
        Clean, format and store in a dict the data for each symbol present in the WebSocket message
        """
        df = pd.DataFrame(x, index=[0])[['E','c','v']]
        df = df.rename(columns={'E': 'Date', 'c': 'Price','v': 'Volume'})
        df['Date'] = (pd.to_datetime(df['Date'], unit='ms', utc=True)) # Cambia in DateTime
        df = df.set_index('Date')
        df = df.apply(pd.to_numeric)

        if x['s'] not in self.tick_data.keys():
            #print('init_'+x['s'])
            self.tick_data[x['s']]=df
        else:
            #print('append_'+x['s'])
            _temp=self.tick_data[x['s']]
            self.tick_data[x['s']] = pd.concat([_temp, df])
    
    def _resample_and_join(self, symbol):
        """
        Resample live tick data in a ordered df with an interval of 1m
        """
        print('resample')
        self.ticks = 0
        for symbol in self.tick_data.keys():
            ohlc= { 'Date' : [self.tick_data[symbol].index[0] - dt.timedelta(microseconds = self.tick_data[symbol].index[0].microsecond)],
                    'Open' : [self.tick_data[symbol].Price[0]],
                    'High': [self.tick_data[symbol].Price.max()],
                    'Low': [self.tick_data[symbol].Price.min()],
                    'Close': [self.tick_data[symbol].Price[-1]],
                    'Volume': [self.tick_data[symbol].Volume[-1]]}
            temp = pd.DataFrame(ohlc).set_index('Date')
            #print(temp)
            self.prices[symbol] = pd.concat([self.prices[symbol], temp])
            # Clean tick_data dictionary
            self.tick_data[symbol] = self.tick_data[symbol].iloc[-1:] # Only keep the latest tick (next bar)
        """
        PROVV: usare quando non scarico i dati prima dello stream

        if symbol not in self.sampled_data.keys():
            self.sampled_data[symbol] = temp
            print (symbol+' NEW')
        else:
            self.sampled_data[symbol] = pd.concat([self.sampled_data[symbol], temp])
            print (symbol+' Append')
            # da aggiungere _to_sql
        """
        """
        DEF: da errore!!
        #Check if all the symbpls have recived a tick in the last minute
        not_in_tick = list(set(self.symbols) - set(self.tick_data.keys()))
        if len(not_in_tick) > 0:
            #If not, assign the last close value to the current tick
            #TODO: Testare in live
            for symbol in not_in_tick:
                temp = self.prices[symbol].iloc[-1:].reset_index()
                temp['Date']=temp['Date']+pd.to_timedelta('1m')
                temp.iloc[:,1:5]=float(temp['Close'])
                temp['Volume']=0
                temp.set_index('Date')
                self.prices[symbol] = pd.concat([self.prices[symbol], temp])
        """
        # Assign new last bar timestamp
        #self.last_bar = self.sampled_data[symbol].index[-1]    #OLD
        self.last_bar = pd.to_datetime(dt.datetime.utcnow()).tz_localize("UTC")


    # Backtest Methods
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


    def _transform_data_provv(self,data):
        """
        Clean and format the data downloaded from BINANCE.
        Add the columns ['Adj Close']

        Returns
        -------
        `data [DataFrame]`
            Dataframe with Date-OHLCV-Adj.
        """
        data = data.iloc[:,:6]
        data.columns=['Date','Open','High','Low','Close', 'Volume']
        
        data = data.set_index('Date') 
        
        data.index = pd.to_datetime(data.index, unit='ms', utc=True)
        data = data.astype(float)
        
        data['Adj Close'] = data['Close']
        return data


    def _load_data_binance(self, symbol, start_dt, end_dt):
        tmf = eval('Client.KLINE_INTERVAL_' + self.timeframe)
            
        if self.end_dt == '':
            data = pd.DataFrame(self.client.get_historical_klines(symbol=symbol, interval=tmf, start_str=start_dt))
        else:
            data = pd.DataFrame(self.client.get_historical_klines(symbol=symbol, interval=tmf, start_str=start_dt, end_str=end_dt))
            
        if len(data) > 0 :
            data = self._transform_data_provv(data)
        return data
 
    
    def _load_prices_dict(self):
        """
        Downoal data from BINANCE and store it in a dictionary

        Returns
        -------
        `prices {'ticker' : [DataFrame]}`
            Dataframe with Date-OHLCV-Adj.
        """
        asset_frames = {}
        for symbol in tqdm(self.symbols):
            asset_frames[symbol] = self._load_data_binance(symbol, self.start_dt, self.end_dt)
            asset_frames[symbol]["Ticker"] = symbol
        return asset_frames
    
    def _load_prices_sql(self):
        """
        Downoal data from BINANCE and store it in a SQL .db

        Returns
        -------
        `prices [DataFrame]`
            Dataframe with Date-OHLCV-Adj.
        """
        def _read_last_line_SQL(engine, symbol):
            """
            Get most recent Date stored in prices SQL database

            Return:
                Timestamp
            """
            qry_str = f"""SELECT Date FROM {symbol} ORDER BY Date DESC LIMIT 1""" 
            df = pd.read_sql(qry_str, engine, index_col='Date')
            df.index = pd.to_datetime(df.index)
            return df.index[0]

        symbols_def = [] # Save the ticker of the downloaded data
        for symbol in tqdm(self.symbols):
            df = self._load_data_binance(symbol, self.start_dt, self.end_dt)
            if len(df) > 0 :
                symbols_def.append(symbol)
                df.to_sql(symbol, self.engine, index = True, if_exists='replace')
            self.symbols=symbols_def
        
        def _check_last(self):
            while True: # repeat until we get all historical bars
                update=0
                for symbol in tqdm(self.symbol_def):
                    now = pd.to_datetime(dt.datetime.utcnow())
                    now = now - dt.timedelta(microseconds = now.microsecond)
                    last_bar = _read_last_line_SQL(self.engine, symbol)
                    bar_length= pd.to_timedelta('1m')

                    if now - last_bar > bar_length :
                        update += 1
                        df = self._load_data_binance(symbol, last_bar.strftime("%Y-%m-%d %H:%M"), '')
                        df.to_sql(symbol, self.engine, index = True, if_exists='append')
                print(update)
                if update == 0:
                    break
        
        #self._check_last() !!! Non funziona

       
    def read_prices_SQL(self, TICKER):
        """
        Read prices from a SQL database
        Return:
            df DataFrame
        """
        qry_str = f"""SELECT * FROM {TICKER}""" 
        df = pd.read_sql(qry_str, self.engine, index_col='Date')
        df.index = pd.to_datetime(df.index)
        return df
    
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
        Obtain the list of all pairs prices available in the
        BINANCE server.

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        info = self.client.get_exchange_info()
    
        symbols = [x['symbol'] for x in info['symbols']]
        exclude = ['UP','DOWN','BEAR','BULL','BUSDUSDT','TUSDUSDT','GBPUSDT',
                   'USDPUSDT','USDCUSDT','PAXUSDT','USDSUSDT','USDSBUSDT','USTUSDT',
                   '1INCHUSDT', 'TUSDT', 'PAXGUSDT']

        relevant = [symbol for symbol in symbols if symbol.endswith('USDT')] 
        relevant = [symbol for symbol in relevant if all(excludes not in symbol for excludes in exclude)]
        
        return relevant
    

    def get_symbols_SQL(self):
        """
        Obtain the list of all Pairs prices in the SQL database.
        
        TODO: Not ready!!!

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        return self.engine.table_names()




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