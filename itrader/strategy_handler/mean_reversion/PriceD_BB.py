import pandas as pd
import numpy as np

from ta import trend
from ta import volatility
import pandas_ta as ta

import logging
logger = logging.getLogger()

from qstrader.strategy.base import AbstractStrategy
from qstrader.event import SignalEvent, EventType
from qstrader.price_parser import PriceParser

from qstrader.strategy.filters.noise_filters import PriceDensity_filter




class PriceD_BB(AbstractStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """
    def __init__(
        self,
        timeframe,

        NOISE_win = 20,
        noise_treshold = 4,
        bb_win = 20,
        bb_std = 2,
        dds_win = 5,

        long_only=True
    ):
        self.timeframe = timeframe
        
        # FILTER PARAMETER
        self.noise_win = NOISE_win
        self.noise_treshold = noise_treshold
        # TRIGGER PARAMETERS
        self.bb_win = bb_win
        self.bb_std = bb_std
        self.dds_win = dds_win

        self.long_only = long_only
        self.test = {'Date':['Strend', 'trend_flt', 'atr','vol_flt']}

        # Input system modules
        self.events_queue = None
        self.portfolio = None
        self.price_handler = None

        # Define Timedelta object according to the timeframe
        self.timedelta = self._get_delta(timeframe)
        self.max_window = max([
            self.noise_win,
            bb_win,
            self.dds_win])*4

        logger.info('STRATEGY: PriceD_Bolinger Strategy => OK')



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
                
                # Calculate the SuperTrenf filrer
                noise = PriceDensity_filter.calculate(bars, self.noise_win, self.noise_treshold)


                # Test indicators
                #self.test[event.time] = [noise.iloc[-1,0], noise.iloc[-1,-1], vol.iloc[-1,0], vol.iloc[-1,1]]

                ## Trigger
                BB_Long = volatility.BollingerBands(bars.loc[start_dt:,'Close'], window=self.bb_win, window_dev=self.bb_std, fillna=False)
                BB_mean = BB_Long.bollinger_mavg().dropna()
                BB_Long_H = BB_Long.bollinger_hband().dropna()
                BB_Long_L = BB_Long.bollinger_lband().dropna()

                # DDS = volatility.DonchianChannel(bars['High'], bars['Low'], bars['Close'], window=self.dds_win, fillna=False)
                # short_ddh = DDS.donchian_channel_hband().dropna()
                # short_ddl = DDS.donchian_channel_lband().dropna()

                ### LONG signals
                # Entry
                if event.ticker not in opened: # Check if the ticker has already an opened position

                    #print (''+str(trend['filter'][-1])+' '+str(vol['filter'][-1])) # Test

                    # Filter check
                    if (noise['filter'][-1] == 1): # Filter

                    # Trigger check
                        if ((self.cross_up(bars.tail(1), BB_Long_L, -1))): # Buy trigger

                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
                            #logger.info('STRATEGY: cross long DD LONG')

                # Exit
                elif (self.portfolio.positions[event.ticker].action == 'BOT'):
                    # Long position already opened. Sell if it is a LONG position

                    # Trend check
                    if (self.cross_up(bars.tail(1), BB_mean, -1)):

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
                        # Filter check
                        if (noise['filter'][-1] == 1):

                        # Short Trigger 
                            if ((self.cross_down(bars.tail(1), BB_Long_H, -1))):
                                
                                signal = SignalEvent(
                                    event.time,
                                    event.ticker, "SLD",
                                    suggested_quantity = 0
                                )
                                self.events_queue.put(signal)

                    # Exit
                    elif (self.portfolio.positions[event.ticker].action =='SLD') and not self.long_only:

                        # Trend check
                        if (self.cross_down(bars.tail(1), BB_mean, -1)):

                            #Exit trigger
                            signal = SignalEvent(
                                event.time,
                                event.ticker, "BOT",
                                suggested_quantity = 0
                            )
                            self.events_queue.put(signal)
