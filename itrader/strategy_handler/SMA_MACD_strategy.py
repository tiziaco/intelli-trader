# import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import BaseStrategy

from ta import trend

import logging
logger = logging.getLogger('TradingSystem')

class SMA_MACD_strategy(BaseStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """
    def __init__(
        self,
        timeframe,
        tickers=[],
        short_window=50,
        long_window=100,
        FAST=6,
        SLOW=12,
        WIN=3,
        long_only=True,
    ):
        
        # Strategy parameters
        self.tickers = tickers
        self.short_window = short_window
        self.long_window = long_window
        self.FAST = FAST
        self.SLOW = SLOW
        self.WIN = WIN
        self.long_only = long_only #TODO: da spostare in order_handler.compliance

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = max([self.long_window, 100])

        self.strategy_id = "SMA_MACD_%s" % self.timeframe
    
    def __str__(self):
        return "SMA_MACD_%s" % self.timeframe

    def __repr__(self):
        return str(self)



    def calculate_signal(self, bars, ticker, time):
        #Check if a stop or limit order is already present in the queue
        # TODO: da spostare in order_handler.compliance
        # for ev in self.global_queue.queue:
        #     if ev.type == EventType.ORDER and ev.ticker == event.ticker:
        #         return


        ### Get data from price handler (last max_window bars from event.time)
        #start_dt = time - self.tf_delta * self.max_window
        #bars = self.price_handler.prices[ticker].loc[start_dt : time, 'close']


        if len(bars) > self.max_window:

            # Calculate the SMA
            start_dt = time - self.tf_delta * self.short_window
            short_sma = trend.SMAIndicator(bars[start_dt:].close, self.short_window, True).sma_indicator().dropna()

            start_dt = time - self.tf_delta * self.long_window
            long_sma = trend.SMAIndicator(bars[start_dt:].close, self.long_window, True).sma_indicator().dropna()


            # Calculate the MACD
            MACD_Indicator = trend.MACD(bars.close, window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN, fillna='False')
            MACDhist = MACD_Indicator.macd_diff().dropna()



            ### LONG signals
            # Entry
            if short_sma[-1] >= long_sma[-1]: # Filter
                if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)): # Buy trigger
                    return (('BOT','ENTRY'))
            # Exit
                elif ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
                    #Sell trigger
                    return (('SLD','EXIT'))


            ### SHORT signals
            # Entry
            if short_sma[-1] <= long_sma[-1]: # Filter
                if ((MACDhist[-1] <= 0) and (MACDhist[-2] > 0)): # Short trigger
                    return (('SLD','ENTRY'))

            # Exit
                elif ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
                    return (('BOT','EXIT'))

