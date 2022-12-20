import pandas as pd
import numpy as np

from qstrader.strategy.base import AbstractStrategy
from qstrader.event import SignalEvent, EventType

from ta import trend

import logging
logger = logging.getLogger()

class SMA_MACD_strategy(AbstractStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """
    def __init__(
        self,
        timeframe,
        short_window=50,
        long_window=100,
        FAST=6,
        SLOW=12,
        WIN=3,
        long_only=True
    ):
        logger.info('STRATEGY: SMA-MACD Strategy => OK')
        # Strategy parameters
        self.short_window = short_window
        self.long_window = long_window
        self.FAST = FAST
        self.SLOW = SLOW
        self.WIN = WIN
        self.long_only = long_only

        self.events_queue = None
        self.portfolio = None
        self.price_handler = None

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.timedelta = self._get_delta(timeframe)
        self.max_window = max([self.long_window, 100])



    def calculate_signals(self, event):
        #Check if a stop or limit order is already present in the queue
        for ev in self.events_queue.queue:
            if ev.type == EventType.ORDER and ev.ticker == event.ticker:
                return

        if (
            event.type == EventType.BAR
        ):
            ### Get data from price handler (last max_window bars from event.time)
            start_dt = event.time - self.timedelta * self.max_window
            bars = self.price_handler.prices[event.ticker].loc[start_dt : event.time, 'Close']

            if len(bars) > self.max_window:

                # Calculate the SMA
                start_dt = event.time - self.timedelta * self.short_window
                short_sma = trend.SMAIndicator(bars[start_dt:], self.short_window, True).sma_indicator().dropna()

                start_dt = event.time - self.timedelta * self.long_window
                long_sma = trend.SMAIndicator(bars[start_dt:], self.long_window, True).sma_indicator().dropna()


                # Calculate the MACD
                MACD_Indicator = trend.MACD(bars, window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN, fillna='False')
                MACDhist = MACD_Indicator.macd_diff().dropna()


                # Get list of opened positions
                opened = self.portfolio.positions.keys()


                ### LONG signals
                # Entry
                if event.ticker not in opened: # Check if the ticker has already an opened position
                    if short_sma[-1] >= long_sma[-1]: # Filter
                        if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)): # Buy trigger
                            
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                # Exit
                elif (self.portfolio.positions[event.ticker].action == 'BOT'):
                    # Long position already opened. Sell if it is a LONG position
                    if ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
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
                if not self.long_only:
                    if event.ticker not in opened: # Check if the ticker has already an opened position
                        if short_sma[-1] <= long_sma[-1]: # Filter
                            if ((MACDhist[-1] <= 0) and (MACDhist[-2] > 0)): # Short trigger
                                signal = SignalEvent(
                                    event.time,
                                    event.ticker, "SLD",
                                    suggested_quantity = 0
                                )
                                self.events_queue.put(signal)
                                self.invested = True
                    # Exit
                    elif (self.portfolio.positions[event.ticker].action =='SLD') and not self.long_only:
                        #OLD: short_sma <= long_sma and self.invested and not self.long_only:
                        if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                            self.invested = False
