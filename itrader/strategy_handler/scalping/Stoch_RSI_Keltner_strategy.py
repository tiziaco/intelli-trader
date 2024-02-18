# import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import BaseStrategy

import pandas_ta as ta

import logging
logger = logging.getLogger('TradingSystem')

class Stoch_RSI_Keltner_strategy(BaseStrategy):
    """
    Mean reversion strategy.
    
    The long entry signal is generated when the slow stochastic oscillator %D line, 
    RSI, and Keltner Channels' upper band are all rising, while the short entry signal 
    is generated when the %D line, RSI, and Keltner Channels' lower band are all falling.

    Overall, this strategy aims to capitalize on short-term market inefficiencies by buying 
    when the market is oversold and selling when the market is overbought.
    """
    def __init__(
        self,
        timeframe,
        tickers=[],

        RSI_WINDOW=47,
        KELT_WINDOW=20,
        KELT_MULT=0.4,
        K_PERIOD = 14,
        D_PERIOD = 3,
        D_SLOW = 3,
        LOOKBACK = 10,

        long_only=False,
    ):
        self.tickers = tickers
        
        # Strategy parameters
        self.KELT_WINDOW = KELT_WINDOW
        self.KELT_MULT = KELT_MULT
        self.RSI_WINDOW = RSI_WINDOW
        self.D_SLOW= D_SLOW
        self.K_PERIOD = K_PERIOD
        self.D_PERIOD = D_PERIOD
        self.LOOKBACK = LOOKBACK

        self.long_only = long_only

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = 150

        self.strategy_id = "Stoch_RSI_Keltner_%s" % self.timeframe
    
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

            """
            import pandas_ta as ta

            # Technical indicator parameters
            StochSlowDKPeriod1 = 14
            StochSlowDDPeriod1 = 3
            StochSlowDSlowing1 = 3
            RSIPeriod1 = 14
            KCerPeriod1 = 20
            KCerMultiplier = 0.4

            # Define long entry signal
            long_entry_signal = (
                (
                    (ta.stoch(high=Main_chart, low=Main_chart, k=StochSlowDKPeriod1, d=StochSlowDDPeriod1, slowing=StochSlowDSlowing1).slowd().shift(8).diff() > 0)
                    & (ta.rsi(close=Main_chart, length=RSIPeriod1) > 65).shift(3)
                    & (ta.kc(high=Main_chart, low=Main_chart, length=KCerPeriod1, mult=KCerMultiplier).upperband().shift(8).diff() > 0)
                )
            )

            # Define short entry signal
            short_entry_signal = (
                (
                    (ta.stoch(high=Main_chart, low=Main_chart, k=StochSlowDKPeriod1, d=StochSlowDDPeriod1, slowing=StochSlowDSlowing1).slowd().shift(8).diff() < 0)
                    & (ta.rsi(close=Main_chart, length=RSIPeriod1) < 35).shift(3)
                    & (ta.kc(high=Main_chart, low=Main_chart, length=KCerPeriod1, mult=KCerMultiplier).lowerband().shift(8).diff() < 0)
                )
            )

            """
            
            start_dt = time - self.tf_delta * self.max_window

            # Calculate the Stochastic indicator
            stoch = ta.stoch(bars.high, bars.low, bars.close, self.K_PERIOD, self.D_PERIOD, self.D_SLOW)

            # Calculate the RSI
            rsi = ta.rsi(bars[start_dt:].close, self.RSI_WINDOW).dropna()

            # Calculate Kaltner channel
            kc = ta.kc(bars.high, bars.low, bars.close, self.KELT_WINDOW, self.KELT_MULT)



            ### LONG signals
            long_entry_signal = (
                (
                    (stoch.iloc[:,1].shift(8).diff()[-1] > 0)
                    & (rsi > 65).shift(3)[-1]
                    & (kc.iloc[:,2].shift(8).diff()[-1] > 0)
                )
            )


            # Entry
            if long_entry_signal:
                return (('BOT','ENTRY'))
                
            # Exit
                # Use SL or TP to exit


            ### SHORT signals
            short_entry_signal = (
                (
                    (stoch.iloc[:,1].shift(8).diff()[-1] < 0)
                    & (rsi < 35).shift(3)[-1]
                    & (kc.iloc[:,0].shift(8).diff()[-1] < 0)
                )
            )

            # Entry
            if short_entry_signal and not self.long_only:
                return (('SLD','ENTRY'))

            # Exit
                # Use SL or TP to exit

