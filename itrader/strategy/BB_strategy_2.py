import datetime # DONT DELETE: Used with eval
import pandas as pd
import numpy as np
import re

from qstrader.strategy.base import AbstractStrategy
from qstrader.price_parser import PriceParser
from qstrader.event import SignalEvent, EventType

from ta import trend
from ta import volatility

import logging
logger = logging.getLogger()



class BB_strategy(AbstractStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """


    def __init__(
        self,
        timeframe,
        WIN_L=20,
        WIN_S = 5,
        WIN_STD = 2,
        long_only=True
    ):
        logger.info('STRATEGY: BB Strategy => OK')
        # Strategy parameters

        self.WIN_L = WIN_L
        self.WIN_S = WIN_S
        self.WIN_STD = WIN_STD
        self.long_only = long_only

        self.events_queue = None
        self.portfolio = None
        self.price_handler = None

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.timedelta = self._get_delta(timeframe)
        self.max_window = max([WIN_L])
    

    def calculate_signals(self, event):
        if (event.type == EventType.BAR):

            ### Get data from price handler (last max_window bars from event.time)
            start_dt = event.time - self.timedelta * self.max_window
            bars = self.price_handler.prices[event.ticker].loc[start_dt : event.time, 'Close']

            if len(bars) > self.max_window:

                # Calculate long Bollinger Band
                start_dt = event.time - self.timedelta * self.WIN_L
                BB_Long = volatility.BollingerBands(bars[start_dt:], window=self.WIN_L, window_dev=self.WIN_STD, fillna=False)
                BB_Long_H = BB_Long.bollinger_hband().dropna()
                BB_Long_L = BB_Long.bollinger_lband().dropna()

                start_dt = event.time - self.timedelta * self.WIN_S
                BB_Short = volatility.BollingerBands(bars[start_dt:], window=self.WIN_S, window_dev=self.WIN_STD, fillna=False)
                BB_Short_SMA = BB_Short.bollinger_mavg().dropna()



                # Get list of opened positions
                opened = self.portfolio.positions.keys()
                close = PriceParser.display(event.close_price)


                ### LONG signals
                # Entry
                if event.ticker not in opened: # Check if the ticker has already an opened position
                        if (self.cross_up(close, BB_Long_H, -1)): # Buy trigger 
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                # Exit
                elif (self.portfolio.positions[event.ticker].action == 'BOT'):
                    # Long position already opened. Sell if it is a LONG position
                    if self.cross_down(close, BB_Short_SMA, -1):
                        #Sell trigger
                        signal = SignalEvent(
                            event.time,
                            event.ticker, "SLD",
                            suggested_quantity = 0
                        )
                        self.events_queue.put(signal)
                        self.invested = False

                ### SHORT signals
                # Entry
                if event.ticker not in opened and not self.long_only: # Check if the ticker has already an opened position
                        if self.cross_down(close, BB_Long_L, -1): # Short trigger
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "SLD",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                            self.invested = True
                # Exit
                elif (self.portfolio.positions[event.ticker].action =='SLD'):
                    if self.cross_up(close, BB_Short_SMA, -1):
                        signal = SignalEvent(
                            event.time,
                            event.ticker, "BOT",
                            suggested_quantity = 0
                        )
                        self.events_queue.put(signal)
                        self.invested = False

    
    