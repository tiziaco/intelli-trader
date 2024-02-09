import datetime as dt
from tqdm import tqdm

import websocket, json
from sqlalchemy import create_engine

import pandas as pd

from ..base import PriceHandler
from ...events_handler.event import PingEvent

import logging
logger = logging.getLogger('TradingSystem')


class BINANCELiveStreamer(PriceHandler):
    """
    BINANCE_data_provider is designed to download data from the
    BINANCE server. It contains Open-High-Low-Close-Volume (OHLCV) data
    for each pair and streams those to the provided events queue as BarEvents.
    """
    
    def __init__(self, global_queue = None):
        """
        Parameters
        ----------
        symbols: `list`
                The list of symbols to be downloaded.
        timeframes: 'list'
            The time frame for the analysis
        global_queue: `object`
            The queue of the trading_system
        """
        self.global_queue = global_queue
        self.klines_stream = None
        self.websocket = self._initialise_websocket()
        self.ws_connected = None
        self.ticks=0
        self.max_prices_length = 2200
        self.tick_data = {}
        self.completed_bars = []
        self._closed = 0
        self._send_ping = False


    def _initialise_websocket(self):
        """
        Initialise the websocket object
        """
        return websocket.WebSocketApp(self.klines_stream, on_open=self._on_open, on_close=self._on_close,
                                    on_error=self._on_error, on_message=self._on_message)


# ******* Live Methods ***********************************   

    def stream_data(self):
        """
        Start the stream of the tickers data from the BINANCE server.
        It streams the klines for a defined timeframe.

        Parameters
        ----------
        klines_stream: 'str'
            String containing the list of coin to stream
        """
        self.set_klines_stream()
        self.websocket.url = self.klines_stream
        self.websocket.run_forever()
    
    def stop_streaming(self):
        """
        Close the websocket connection.
        """
        self.websocket.close()
    
    def _on_message(self, ws, message):
        """
        Process the data recived from the websocket.

        Parameters
        ----------
        ws: 'websocket'
            Not used
        message: 'str'
            The data package sended from the websocket
        """
        msg = json.loads(message)['data']
        self.test = msg
        self.ticks += 1
        #print(self.ticks, end=' ')

        if msg['s'] in self.symbols:
            #self._store_tick(msg)
            if msg['k']['x']:
                # Store the bar when it is closed
                self._store_bar(msg['k'])
                #print('')

                # TEST:
                self._closed += 1
                self._send_ping = True

                if self._closed == 5:
                    now = dt.datetime.now()
                    #print(f'\nTotal closed 1: ' + str(self._closed) + ' ' + dt.datetime.strftime(now, '%Y-%m-%d %H:%M:%S'))
                    # Send ping event Method 1
                    if self.global_queue is not None:
                        # Generate ping event
                        ping = PingEvent(self.time)
                        self.global_queue.put(ping)
            else:
                # Send ping event Method 2
                # Funziona ma troppo lag: devo aspettare il tick successivo la closed bar, troppo tempo.
                if self._send_ping:
                    now = dt.datetime.now()
                    #print(f'\nTotal closed 2: ' + str(self._closed) + ' '  + dt.datetime.strftime(now, '%Y-%m-%d %H:%M:%S'))
                    self._send_ping = False
                    self.ticks=0
                    self._closed = 0

                    # if self.global_queue is not None:
                    #     # Generate ping event
                    #     ping = PingEvent(self.time)
                    #     self.global_queue.put(ping)

                
    
    def _on_open(self, ws):
        """
        Callback method triggered when the connection is opened
        """
        logger.info("PRICE HANDLER: Binance Websocket connection opened. Data streaming started.")
        self.ws_connected = True

    def _on_close(self, ws, *kwargs):
        """
        Callback method triggered when the connection drops
        """

        logger.warning("PRICE HANDLER: Binance Websocket connection closed")
        self.ws_connected = False

    def _on_error(self, ws, msg: str, *kwargs):
        """
        Callback method triggered in case of error
        :param msg:
        :return:
        """

        logger.error("Binance connection error: %s", msg)

    def _store_bar(self, msg):
        """
        Store the last completed bar in the prices DataFrame.

        Parameters
        ----------
        msg: 'json'
            the data recived from the websocket
        """
        # Save bar time
        self.time = pd.to_datetime(msg['t'], unit='ms', utc=True).tz_convert('Europe/Paris')
        # Create a dictionary with the completed bar
        bar_dict={self.time :
                    {'open': msg['o'],
                    'high': msg['h'],
                    'low': msg['l'],
                    'close': msg['c'],
                    'volume':msg['v']
                    }
                }
        # Save the ticker who got the data
        self.completed_bars=[]
        self.completed_bars.append(msg['s'])

        # Add the bar in the ticker DataFrame
        df = pd.DataFrame.from_dict(bar_dict, orient='index', dtype=float)

        # Add the bar in the ticker DataFrame
        PriceHandler.prices[msg['s']] = pd.concat([PriceHandler.prices[msg['s']], df])

        # Slice the dataframe to the last max_prices_length bars
        PriceHandler.prices[msg['s']] = PriceHandler.prices[msg['s']].tail(self.max_prices_length)

        self.ticks = 0
    
    def _store_tick(self, x):
        """
        Clean, format and store in a dict the data for each symbol present in the WebSocket message
        
        Not used yet.
        """
        # Format the message recived from the BINANCE server
        self.tick_data.setdefault(x['s'], {}).setdefault(
            pd.to_datetime(x['E'], unit='ms', utc=True), {'price':x['k']['c']})

    def set_klines_stream(self):
        klines_stream = 'wss://stream.binance.com:9443/stream?streams='
        
        low = list(map(lambda x: x.lower(), PriceHandler.symbols))
        for sym in low:
            klines_stream += sym+'@kline_'+PriceHandler.timeframe+'/'
        self.klines_stream = klines_stream[:-1]

