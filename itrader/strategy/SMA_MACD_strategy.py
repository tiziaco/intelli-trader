from collections import deque
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
        self, ticker,
        short_window=20,
        long_window=40,
        FAST=6,
        SLOW=12,
        WIN=3,
        base_quantity=100,
        long_only=True
    ):
        logger.info('STRATEGY: SMA-MACD Strategy => OK')
        self.ticker = ticker
        self.short_window = short_window
        self.long_window = long_window
        self.FAST = FAST
        self.SLOW = SLOW
        self.WIN = WIN
        self.base_quantity = base_quantity
        self.bars = 0
        self.invested = False
        self.sw_bars = deque(maxlen=self.short_window)
        self.lw_bars = deque(maxlen=self.long_window)
        self.macd_bars = deque(maxlen=100)
        self.long_only = long_only

        self.events_queue = None
        self.portfolio = None

    def calculate_signals(self, event):
        if (
            event.type == EventType.BAR and
            event.ticker == self.ticker
        ):
            #print(self.invested) TEST
            

            # Add latest adjusted closing price to the
            # short and long window bars

            self.lw_bars.append(event.adj_close_price)
            self.macd_bars.append(event.adj_close_price)
            if self.bars > self.long_window - self.short_window:
                self.sw_bars.append(event.adj_close_price)

            ### CHeck if enough bars are present for trading
            if ((self.bars > self.long_window) and (self.bars > 100)):
                # Calculate the simple moving averages

                logger.debug('   Opened positions: %s', self.portfolio.positions.keys()) #TEST

                short_sma = np.mean(self.sw_bars)
                long_sma = np.mean(self.lw_bars)

                # Calculate the MACD
                MACD_Indicator = trend.MACD(pd.Series(list(self.macd_bars)), window_fast=self.FAST, window_slow=self.SLOW, window_sign=self.WIN, fillna='False')
                MACDhist = MACD_Indicator.macd_diff()
                MACDhist = MACDhist.dropna()



                ### LONG signals
                # Entry
                if short_sma >= long_sma and not self.invested:
                    if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
                        signal = SignalEvent(
                            event.time,
                            self.ticker, "BOT",
                            suggested_quantity=self.base_quantity
                        )
                        self.events_queue.put(signal)
                        self.invested = True
                # Exit
                elif ((self.invested) and (self.portfolio.positions[self.ticker].action =='BOT')):
                    #OLD: short_sma >= long_sma and self.invested:
                    if ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
                        signal = SignalEvent(
                            event.time,
                            self.ticker, "SLD",
                            suggested_quantity=self.base_quantity #Da cambiare probabilmente
                        )
                        self.events_queue.put(signal)
                        self.invested = False

                ### SHORT signals
                # Entry
                elif short_sma <= long_sma and not self.invested and not self.long_only:
                    if ((MACDhist.iloc[-1] <= 0) and (MACDhist.iloc[-2] > 0)):
                        signal = SignalEvent(
                            event.time,
                            self.ticker, "SLD",
                            suggested_quantity=self.base_quantity
                        )
                        self.events_queue.put(signal)
                        self.invested = True
                # Exit
                elif ((self.invested)and (self.portfolio.positions[self.ticker].action =='SLD')):
                    #OLD: short_sma <= long_sma and self.invested and not self.long_only:
                    if ((MACDhist.iloc[-1] >= 0) and (MACDhist.iloc[-2] < 0)):
                        signal = SignalEvent(
                            event.time,
                            self.ticker, "BOT",
                            suggested_quantity=self.base_quantity #Da cambiare probabilmente
                        )
                        self.events_queue.put(signal)
                        self.invested = False

            self.bars += 1