import pandas as pd
import numpy as np

from pandas_ta import overlap

from itrader.screeners_handler.base import BaseScreener

class VolumeSpykeScreener(BaseScreener):
    def __init__(self, tickers = 'all', frequency = '15m', timeframe = '15m', window = 20):
        self.tickers = tickers
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.frequency = self._get_delta(frequency)
        self.window = window
        self.max_window = window+1
        self.results = {}
        self.last_proposed = []

        self.screener_id = "VolumeSpyke"
    
    def __str__(self):
        return self.screener_id

    def __repr__(self):
        return str(self)


    def apply_screener(self, prices, time):

        if len(prices) >= self.max_window:
            # Calculate the return of the last row
            last_open = prices.xs('open', level=1, axis=1).tail(1)
            last_close = prices.xs('close', level=1, axis=1).tail(1)
            pct_return = (last_close.tail(1) - last_open.tail(1)) / last_close.tail(1)

            positive_ret = list(pct_return[pct_return>0].dropna(axis=1).columns)
            negative_ret = list(pct_return[pct_return<0].dropna(axis=1).columns)

            # Slice MegaFrame selecting only the 'close' columns for every symbol
            volume = prices.xs('volume', level=1, axis=1)
            # Calculate the SMA of the volume
            sma = volume.apply(overlap.sma, length=self.window) # TODO: non prende window come argomento

            # Calculate the pct difference between the last volume and the SMA
            pct_diff = (volume.tail(1) - sma.tail(1)) / volume.tail(1)
            pct_diff = pct_diff[positive_ret].copy()

            # Filter only tickers with a volume increase greather than 5x
            pct_diff = pct_diff[pct_diff>0.8].dropna(axis=1).copy()

            proposed = list(pct_diff.iloc[-1].nlargest(10).index)
            self.last_proposed = proposed
            return proposed