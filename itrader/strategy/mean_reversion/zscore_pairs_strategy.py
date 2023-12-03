import pandas as pd
import numpy as np

from itrader.strategy.base import BaseStrategy

import pandas_ta as ta

from statsmodels.tsa.stattools import coint
from statsmodels.api import OLS

import logging
logger = logging.getLogger('TradingSystem')

class ZscorePairs_strategy(BaseStrategy):
    """
    ZscorePairs strategy.
    
    The long entry signal is generated when the slow stochastic oscillator %D line, 
    RSI, and Keltner Channels' upper band are all rising, while the short entry signal 
    is generated when the %D line, RSI, and Keltner Channels' lower band are all falling.

    Overall, this strategy aims to capitalize on short-term market inefficiencies by buying 
    when the market is oversold and selling when the market is overbought.
    """
    def __init__(self, timeframe, tickers=[],

        # Strategy parameters
        ZSCORE_WINDOW = 10,
        ZSCORE_TRESHOLD = 1.1,
        QUANTILE_WINDOW = 20,
        KLINE_LIMIT = 200,

        long_only=True,
    ):
        self.tickers = tickers
        
        # Strategy parameters
        self.ZSCORE_WINDOW = ZSCORE_WINDOW
        self.ZSCORE_TRESHOLD = ZSCORE_TRESHOLD
        self.QUANTILE_WINDOW = QUANTILE_WINDOW
        self.KLINE_LIMIT = KLINE_LIMIT

        self.long_only = long_only

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = self.KLINE_LIMIT

        self.strategy_id = "ZscorePairs_strategy%s" % self.timeframe
    
    def __str__(self):
        return self.strategy_id

    def __repr__(self):
        return str(self)
    
    @staticmethod
    def _calculate_spread(sr1:list, sr2:list, hedge_ratio):
        """
        Calculate spread
        """
        spread = pd.Series(sr1) - pd.Series(sr2) * hedge_ratio
        return spread

    @staticmethod
    def _calculate_zscore(data: pd.Series, window: int):
        # Calculate the rolling mean and standard deviation
        rolling_mean = data.rolling(window).mean()
        rolling_std = data.rolling(window).std()

        # Calculate the z-score with variable window
        z_scores = (data - rolling_mean) / rolling_std
        return z_scores

    @staticmethod
    def _calculate_quantile(data: pd.Series, lookback: int):
        """
        Calculate the rolling quantiles fro a given time-series
        """
        qnt = pd.DataFrame()
        qnt['q05'] = data.rolling(lookback).quantile(0.05)
        qnt['q95'] = data.rolling(lookback).quantile(0.95)
        return qnt

    def _calculate_metrics(self, sr1: list, sr2: list):
        """
        Calculate the statistical metrics of a pairs 
        """
        coin_flag=0
        coin_res = coint(sr1,sr2)
        coin_t = coin_res[0]
        p_value = coin_res[1]
        critical_value = coin_res[2][1]
        model = OLS(sr1,sr2).fit()
        hedge_ratio = model.params[0]
        spread = self._calculate_spread(sr1, sr2, hedge_ratio)

        zscore = self._calculate_zscore(spread, self.ZSCORE_WINDOW)

        if p_value <0.5 and coin_t < critical_value:
            coin_flag = 1
        return (coin_flag, zscore)


    def calculate_signal(self, bars: dict , event, ticker: tuple):

        if len(next(iter(bars.values()))) >= self.max_window:
            # Define traded tickers
            ticker1 = ticker[0]
            ticker2 = ticker[1]

            # Get the close plice of both coins as lists
            close1 = bars[ticker1].close
            close2 = bars[ticker2].close

            # Calculate the statistical metrics
            coin_flag, zscore = self._calculate_metrics(close1, close2)

            # Calculate quantiles of the zscore
            qnt = self._calculate_quantile(zscore, self.QUANTILE_WINDOW)

            # Zscore positive = LONG on ticker2 and SHORT ticker1
            # Zscore negative = SHORT on ticker2 and LONG ticker1

            # Check if the pair is still correlated
            if coin_flag != 1:
                return
            
            ## ENTRY signals based on the treshold
            # if abs(zscore[-1]) >= self.ZSCORE_TRESHOLD:

            #     if zscore[-1] > 0:
            #         # LONG on ticker2 and SHORT ticker1
            #         self._send_signal(ticker2, ('BOT','ENTRY'), event, self.strategy_id)
            #         self._send_signal(ticker1, ('SLD','ENTRY'), event, self.strategy_id)
            #         return
            #     else:
            #         # SHORT on ticker2 and LONG ticker1
            #         self._send_signal(ticker2, ('SLD','ENTRY'), event, self.strategy_id)
            #         self._send_signal(ticker1, ('BOT','ENTRY'), event, self.strategy_id)
            #         return

            ## ENTRY signals based on the quantiles
            if zscore[-1] >= qnt['q95'][-1]:
                # LONG on ticker2 and SHORT ticker1
                    self._send_signal(ticker2, ('BOT','ENTRY'), event, self.strategy_id)
                    self._send_signal(ticker1, ('SLD','ENTRY'), event, self.strategy_id)
                    return
            elif zscore[-1] <= qnt['q05'][-1]:
                # SHORT on ticker2 and LONG ticker1
                    self._send_signal(ticker2, ('SLD','ENTRY'), event, self.strategy_id)
                    self._send_signal(ticker1, ('BOT','ENTRY'), event, self.strategy_id)
                    return
            
            
            ## EXIT Signals
            if self.cross_up(zscore[-1], zscore[-2], 0):
                # Exit SHORT on ticker2 and Exit LONG ticker1
                self._send_signal(ticker2, ('SLD','EXIT'), event, self.strategy_id)
                self._send_signal(ticker1, ('BOT','EXIT'), event, self.strategy_id)
                return
            elif self.cross_down(zscore[-1], zscore[-2], 0):
                # Exit LONG on ticker2 and Exit SHORT ticker1
                self._send_signal(ticker2, ('BOT','EXIT'), event, self.strategy_id)
                self._send_signal(ticker1, ('SLD','EXIT'), event, self.strategy_id)
                return

