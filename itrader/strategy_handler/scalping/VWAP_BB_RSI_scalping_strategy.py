# import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import BaseStrategy

import pandas_ta as ta

import logging
logger = logging.getLogger('TradingSystem')

class VWAP_BB_RSI_scalping_strategy(BaseStrategy):
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

        RSI_WINDOW=14,
        BB_WINDOW = 14,
        BB_STD = 2,
        LOOKBACK = 10,

        long_only=False,
    ):
        self.tickers = tickers
        
        # Strategy parameters
        self.RSI_WINDOW = RSI_WINDOW
        self.BB_WINDOW = BB_WINDOW
        self.BB_STD = BB_STD
        self.LOOKBACK = LOOKBACK

        self.long_only = long_only #TODO: da spostare in order_handler.compliance

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = 200

        self.strategy_id = "VWAP_BB_RSI_scalp_%s" % self.timeframe
    
    def __str__(self):
        return self.strategy_id

    def __repr__(self):
        return str(self)



    def calculate_signal(self, bars, ticker, time):
        #Check if a stop or limit order is already present in the queue
        # TODO: da spostare in order_handler.compliance
        # for ev in self.global_queue.queue:
        #     if ev.type == EventType.ORDER and ev.ticker == event.ticker:
        #         return


        if len(bars) >= self.max_window:

            # Calculate the VWAP
            start_dt = time - self.tf_delta * self.max_window
            vwap = ta.vwap(bars.high, bars.low, bars.close, bars.volume) # 30 bars

            # Calculate BB bands
            bbands = ta.bbands(bars.close, length=self.BB_WINDOW, std=self.BB_STD) # 30 bars

            # Calculate the RSI
            rsi = ta.rsi(bars[start_dt:].close, self.RSI_WINDOW).dropna()



            ### LONG signals
            # Entry
            if (bars.tail(self.LOOKBACK).close > vwap.tail(self.LOOKBACK)).all() == True: # Filter
                if (rsi[-1] < 45) and (bars.close[-1] <= bbands.iloc[-1,0]): # Buy trigger
                    return (('BOT','ENTRY'))
                
            # Exit
                # Use SL or TP to exit
                if self.cross_up(rsi[-1], rsi[-2], 70): 
                    return (('SLD','EXIT'))


            ### SHORT signals
            # Entry
            if (bars.tail(self.LOOKBACK).close < vwap.tail(self.LOOKBACK)).all() == True:# Filter
                if (rsi[-1] > 55) and (bars.close[-1] >= bbands.iloc[-1,2]): # Short trigger
                    return (('SLD','ENTRY'))

            # Exit
                # Use SL or TP to exit
                if self.cross_down(rsi[-1], rsi[-2], 30): 
                    return (('BOT','EXIT'))

