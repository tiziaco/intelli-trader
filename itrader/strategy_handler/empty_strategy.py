# import pandas as pd
# import numpy as np

from itrader.strategy_handler.base import BaseStrategy

from ta import trend

import logging
logger = logging.getLogger('TradingSystem')

class Empty_strategy(BaseStrategy):
    """
    Requires:
    ticker - The ticker symbol being used for moving averages
    short_window - Lookback period for short moving average
    long_window - Lookback period for long moving average
    """
    def __init__(
        self,
        timeframe,
        tickers=['BTCBUSD']
    ):
        # Strategy parameters
        self.tickers = tickers

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = 1

        self.strategy_id = "Empty_%s" % self.timeframe
    
    def __str__(self):
        return "Empty_%s" % self.timeframe

    def __repr__(self):
        return str(self)



    def calculate_signal(self, bars, ticker, time):
        return