# import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import BaseStrategy

import pandas_ta as ta

import logging
logger = logging.getLogger('TradingSystem')

class RSI_scalping_strategy(BaseStrategy):
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

        EMA_WINDOW=100,
        RSI_WINDOW=6,
        LOOKBACK=5,

        long_only=False,
    ):
        
        # Strategy parameters
        self.tickers = tickers
        self.EMA_WINDOW = EMA_WINDOW
        self.RSI_WINDOW = RSI_WINDOW
        self.LOOKBACK = LOOKBACK

        self.long_only = long_only 
        self.last_bars = None

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = EMA_WINDOW*2

        self.strategy_id = "RSI_scalp_%s" % self.timeframe
    
    def __str__(self):
        return self.strategy_id

    def __repr__(self):
        return str(self)



    def calculate_signal(self, bars, event, ticker):
        #Check if a stop or limit order is already present in the queue
        # TODO: da spostare in order_handler.compliance
        # for ev in self.global_queue.queue:
        #     if ev.type == EventType.ORDER and ev.ticker == event.ticker:
        #         return
        #self.last_bars = bars[ticker].close
        time = event.time
        if len(bars) >= self.max_window:
            # Calculate the EMA
            start_dt = time - self.tf_delta * self.max_window
            ema = ta.ema(bars[start_dt:].close, self.EMA_WINDOW).dropna()

            # Calculate the RSI
            rsi = ta.rsi(bars[start_dt:].close, self.RSI_WINDOW).dropna()



            ### LONG signals
            # Entry
            if (bars.tail(self.LOOKBACK).close > ema.tail(self.LOOKBACK)).all() == True: # Filter
                if self.cross_up(rsi[-1], rsi[-2], 10): # Buy trigger
                    return (('BOT','ENTRY'))
                
            # Exit
                # Use SL or TP to exit
                #return (('SLD','EXIT'))


            ### SHORT signals
            # Entry
            if (bars.tail(self.LOOKBACK).close < ema.tail(self.LOOKBACK)).all() and self.long_only:# Filter
                if self.cross_down(rsi[-1], rsi[-2], 90): # Short trigger
                    return (('SLD','ENTRY'))

            # Exit
                # Use SL or TP to exit
                # return (('BOT','EXIT'))

