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
from ..event import TickEvent
from .base import AbstractTickPriceHandler


class BINANCE_data_provider(AbstractTickPriceHandler):
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
    
    def __init__(self, events_queue, symbols=[], timeframes=['1DAY'], start_dt='', end_dt='', bar_length='1m'):

        self.client = Client(config.API_KEY, config.API_SECRET)
        #self.engine = create_engine('sqlite:///prices.db')
        self.continue_backtest = True
        self.events_queue = events_queue
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.timeframe = timeframes[0]
        if symbols=='all':
            self.symbols = self.get_all_symbols()
        else:
            self.symbols = symbols

        # Live attributes
        self.ticks=0
        self.bar_length = pd.to_timedelta(bar_length)
        self.tick_data = {}
        self.sampled_data = {}
        self.last_bar = pd.to_datetime(dt.datetime.utcnow()).tz_localize("UTC") # UTC time at instantiation


# ******* Live Methods ***********************************   

    def stream_data(self):
        """
        Start the stream of the tickers data from the BINANCE server
        """
        self.start_dt = (pd.to_datetime(dt.datetime.utcnow()).tz_localize("UTC")-pd.to_timedelta('24h')).strftime("%Y-%m-%d %H:%M")
        self._load_prices_sql()

        def on_message(ws, message):
            msg = json.loads(message)
            self.test=msg
            self.ticks += 1
            print(self.ticks, end=' ')

            for x in msg :
                if x['s'] in self.symbols:
                    # collect and store tick data
                    self._store_tick(x)
                    # get the latest timestamp of the recived tick
                    recent_tick=self.tick_data[x['s']].index[-1]
                    # create tick event
                    """
                    #TODO: creare un evento di eventi (sottoforma di dictionary)
                    tev = self._create_tick_event(self.tick_data[x['s']])
                    self.price_event = tev"""

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
        Used in: stream_data
        """
        # Format the message recived from the BINANCE server
        df = pd.DataFrame(x, index=[0])[['E','c','v']]
        df = df.rename(columns={'E': 'Date', 'c': 'Price','v': 'Volume'})
        df['Date'] = (pd.to_datetime(df['Date'], unit='ms', utc=True)) # Cambia in DateTime
        df = df.set_index('Date')
        df = df.apply(pd.to_numeric)

        # Save the tick in the tick_data dictionary
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
        Used in: stream_data
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
            # Add the new bar to the SQL db
            temp.to_sql(symbol, self.engine, index = True, if_exists='append')
            # Clean tick_data dictionary
            self.tick_data[symbol] = self.tick_data[symbol].iloc[-1:] # Only keep the latest tick (next bar)

        """
        #TODO: da errore!!

        # Check if all the symbols have recived a tick in the last minute
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

    def download_data(self):
        self._load_prices_sql()
    
    def read_data_SQL(self):
        self.prices= self._load_prices_sql_to_dict()

    def _transform_data(self,data):
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
        
        # data['Adj Close'] = data['Close']     #Non Usare con SQL
        return data


    def _load_data_binance(self, symbol, start_dt, end_dt):
        tmf = eval('Client.KLINE_INTERVAL_' + self.timeframe)
            
        if self.end_dt == '':
            data = pd.DataFrame(self.client.get_historical_klines(symbol=symbol, interval=tmf, start_str=start_dt))
        else:
            data = pd.DataFrame(self.client.get_historical_klines(symbol=symbol, interval=tmf, start_str=start_dt, end_str=end_dt))
            
        if len(data) > 0 :
            data = self._transform_data(data)
        return data
 
    
    def _load_prices_sql_to_dict(self):
        """
        Downoal data from BINANCE and store it in a dictionary
        !! NOT USED !!
        Returns
        -------
        `prices {'ticker' : [DataFrame]}`
            Dataframe with Date-OHLCV-Adj.
        """
        asset_frames = {}
        sql_symbols = []
        for symbol in tqdm(self.symbols):
            try:
                asset_frames[symbol] = self._read_prices_SQL(symbol)
                asset_frames[symbol]["Ticker"] = symbol
                sql_symbols.append(symbol)
            except:
                continue
        self.symbols = sql_symbols
        return asset_frames


# ******* SQL manager ******
    def _read_last_line_SQL(engine, symbol):
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
                last_bar = self._read_last_line_SQL(self.engine, symbol)

                if now - last_bar > self.bar_length :
                    update += 1
                    df = self._load_data_binance(symbol, last_bar.strftime("%Y-%m-%d %H:%M"), '')
                    df.to_sql(symbol, self.engine, index = True, if_exists='append')
            print(update)
            if update == 0:
                break

    def _load_prices_sql(self):
        """
        Downoal data from BINANCE and store it in a SQL .db

        Returns
        -------
        `prices [DataFrame]`
            Dataframe with Date-OHLCV-Adj.
        """

        symbols_def = [] # Save the ticker of the downloaded data
        for symbol in tqdm(self.symbols):
            df = self._load_data_binance(symbol, self.start_dt, self.end_dt)
            if len(df) > 0 :
                symbols_def.append(symbol)
                df.to_sql(symbol, self.engine, index = True, if_exists='replace')
            self.symbols = symbols_def
        
        #self._check_last() !!! Non funziona

       
    def _read_prices_SQL(self, TICKER):
        """
        Read prices from a SQL database
        Return:
            df DataFrame
        """
        qry_str = f"""SELECT * FROM {TICKER}""" 
        df = pd.read_sql(qry_str, self.engine, index_col='Date')
        df.index = pd.to_datetime(df.index)
        return df

    def resample_SQL(self, symbols, timeframe):
        """
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
            df = self._read_prices_SQL(symbol)
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
        
        TODO: Not ready!!!

        Returns
        -------
        `list[str]`
            The list of all coins.
        """
        return self.engine.table_names()

# ******* BINANCE methods ******
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
            exclude = ['UP', 'DOWN','BEAR','BULL','BUSDUSDT','TUSDUSDT','GBPUSDT',
                    'USDPUSDT','USDCUSDT','PAXUSDT','USDSUSDT','USDSBUSDT','USTUSDT',
                    '1INCHUSDT', 'TUSDT', 'PAXGUSDT']

            relevant = [symbol for symbol in symbols if symbol.endswith('USDT')] 
            relevant = [symbol for symbol in relevant if all(excludes not in symbol for excludes in exclude)]
            
            return relevant


# ******* Event manager ******
    def _create_bar_event(self, index, period, ticker, row):
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

    def _create_tick_event(self, data):
            ticker = data["name"]
            index = pd.to_datetime(data['Date'])
            bid = PriceParser.parse(data['Price'])
            ask = PriceParser.parse(data['Price'])
            return TickEvent(ticker, index, bid, ask)

    def stream_next(self):
        """
        Place the next PriceEvent (BarEvent or TickEvent) onto the event queue.
        """
        if self.price_event is not None:
            self._store_event(self.price_event)
            self.events_queue.put(self.price_event)
            self.price_event = None