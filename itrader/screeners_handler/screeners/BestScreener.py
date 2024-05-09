import pandas as pd
import numpy as np

from itrader.screeners_handler.screeners.base import Screener

class MostPerformingScreener(Screener):
    def __init__(self, timeframe = '5m', frequency = '24h'):
        self.timeframe = timeframe
        self.frequency = frequency
        self.max_window = (self._get_delta(frequency) / self._get_delta(timeframe)) + 1
        self.results = {}


    def apply_screener(self, prices, time):

        # Slice MegaFrame selecting only the 'close' columns for every symbol
        close = prices.xs('close', level=1, axis=1)

        # Calculate returns
        ret = close.pct_change()
        cumret = (ret + 1).cumprod() - 1

        self.results = {'gainers' : cumret.iloc[-1].nlargest(10),
                        'loosers' : cumret.iloc[-1].nsmallest(10)}
        return self.results#['gainers']