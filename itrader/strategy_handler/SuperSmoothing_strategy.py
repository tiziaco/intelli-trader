import pandas as pd
import numpy as np

from qstrader.strategy.base import AbstractStrategy
from qstrader.event import SignalEvent, EventType
from qstrader.price_parser import PriceParser

from ta import trend
import pandas_ta as ta

import logging
logger = logging.getLogger()

class SuperSmoothing_strategy(AbstractStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """
    def __init__(
        self,
        timeframe,
        short_window=5,
        long_window=10,
        smooth_win = 100,
        poly_order = 2,
        long_only=True
    ):
        logger.info('STRATEGY: SuperSmoother Strategy => OK')
        # Strategy parameters
        self.short_window = short_window
        self.long_window = long_window
        self.smooth_win = smooth_win
        self.SLOW = poly_order
        #self.WIN = WIN
        self.long_only = long_only

        self.pulldown = {}

        self.events_queue = None
        self.portfolio = None
        self.price_handler = None

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.timedelta = self._get_delta(timeframe)
        self.max_window = max([self.long_window*4, self.smooth_win*2])



    def calculate_signals(self, event):
        #Check if a stop or limit order is already present in the queue
        for ev in self.events_queue.queue:
            if ev.type == EventType.ORDER and ev.ticker == event.ticker:
                return

        if (
            event.type == EventType.BAR
        ):
            ### Initialize strategy variables
            # Get data from price handler (last max_window bars from event.time)
            start_dt = event.time - self.timedelta * self.max_window
            bars = self.price_handler.prices[event.ticker].loc[start_dt : event.time]

            # Get list of opened positions
            opened = self.portfolio.positions.keys()


            if len(bars) > self.max_window:

                # Calculate the Volume Oscillator
                short_sma = trend.EMAIndicator(bars['Volume'], self.short_window, True).ema_indicator().dropna()
                long_sma = trend.EMAIndicator(bars['Volume'], self.long_window, True).ema_indicator().dropna()

                vo = round((short_sma-long_sma)/long_sma,4)


                # Calculate the SuperSmoothing bands
                ss = ta.ssf(bars['Close'], 100, 2).to_frame('ss')
                ss['sdev'] = ss.rolling(window=100).std()
                ss['hband'] = ss.iloc[:,0] + ss.loc[:,'sdev']
                ss['lband'] = ss.iloc[:,0] - ss.loc[:,'sdev']

                # Calculate the slope of the ss
                slope = ss['ss'].iat[-1] - ss['ss'].iat[-2]
                close = PriceParser.display(event.close_price)

                ### LONG signals
                # Entry
                if event.ticker not in opened: # Check if the ticker has already an opened position
                    if slope >= 0: # Filter
                        if ((self.cross_up(bars.tail(1), ss['hband'])) and (event.ticker not in self.pulldown.keys())): # Buy trigger
                            self.pulldown[event.ticker] = 1
                            logger.info('STRATEGY: First Cross LONG')

                        elif ((self.cross_down(bars.tail(1), ss['hband'])) and (event.ticker in self.pulldown.keys())):
                            if (self.pulldown[event.ticker] == 1):
                                self.pulldown[event.ticker] += 1
                                logger.info('STRATEGY: Second Cross LONG')


                        elif ((self.cross_up(bars.tail(1), ss['hband'])) and (event.ticker in self.pulldown.keys())):
                            if (vo[-1]>=0) and (self.pulldown[event.ticker] == 2):

                                signal = SignalEvent(
                                    event.time,
                                    event.ticker, "BOT",
                                    suggested_quantity = 0
                                )
                                self.events_queue.put(signal)
                                self.pulldown.pop(event.ticker)
                    else:
                        if event.ticker in self.pulldown.keys():
                            self.pulldown.pop(event.ticker)

                # Exit
                elif (self.portfolio.positions[event.ticker].action == 'BOT'):
                    # Long position already opened. Sell if it is a LONG position
                    if (slope <= 0):
                        #Sell trigger
                        signal = SignalEvent(
                            event.time,
                            event.ticker, "SLD",
                            suggested_quantity = 0
                        )
                        self.events_queue.put(signal)


                ### SHORT signals
                # Entry
                if not self.long_only:
                    if event.ticker not in opened: # Check if the ticker has already an opened position
                        if slope <= 0: # Filter
                            if ((self.cross_down(bars.tail(1), ss['lband'])) and (event.ticker not in self.pulldown.keys())):
                                self.pulldown[event.ticker] = -1
                                logger.info('STRATEGY: First Cross SHORT')

                            elif ((self.cross_up(bars.tail(1), ss['lband'])) and (event.ticker in self.pulldown.keys())):
                                if (self.pulldown[event.ticker] == -1):
                                    self.pulldown[event.ticker] -= 1
                                    logger.info('STRATEGY: First Cross SHORT')

                            elif ((self.cross_down(bars.tail(1), ss['lband'])) and (event.ticker in self.pulldown.keys())):
                                if (vo[-1]>=0) and (self.pulldown[event.ticker] == -2):
                                    signal = SignalEvent(
                                        event.time,
                                        event.ticker, "SLD",
                                        suggested_quantity = 0
                                    )
                                    self.events_queue.put(signal)
                                    self.pulldown.pop(event.ticker)
                        else:
                            if event.ticker in self.pulldown.keys():
                                self.pulldown.pop(event.ticker)
                    # Exit
                    elif (self.portfolio.positions[event.ticker].action =='SLD') and not self.long_only:
                        if (slope >= 0):
                            #Sell trigger
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                            self.pulldown.pop(event.ticker)
