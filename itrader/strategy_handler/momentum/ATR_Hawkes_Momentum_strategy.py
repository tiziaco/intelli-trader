import pandas as pd
import numpy as np

from itrader.strategy_handler.base import BaseStrategy

import pandas_ta as ta

import logging
logger = logging.getLogger('TradingSystem')

class ATR_Hawkes_Momentum_strategy(BaseStrategy):
    """
    Volatility-Momentum strategy.
    
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

        # Strategy parameters
        NORM_LOOKBACK = 200, #336*4
        QUANT_LOOKBACK = 300, #168*4
        KAPPA = 0.1,

        long_only=True,
    ):
        self.tickers = tickers
        
        # Strategy parameters
        self.NORM_LOOKBACK = NORM_LOOKBACK
        self.QUANT_LOOKBACK = QUANT_LOOKBACK
        self.KAPPA = KAPPA
        self._last_below = {}

        self.long_only = long_only

        # Define Timedelta object according to the timeframe
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.max_window = self.NORM_LOOKBACK + self. QUANT_LOOKBACK + 100

        self.strategy_id = "ATR_Hawkes_Momentum_%s" % self.timeframe
    
    def __str__(self):
        return self.strategy_id

    def __repr__(self):
        return str(self)
    

    # def _initialise_last_below(self):
    #     for ticker in self.tickers:
    #         if ticker in self.tickers and ticker not in self._last_below.keys():
    #             # New ticker detected, initialise with None
    #             self._last_below = {key: None for key in self.tickers}
    #         elif ticker in self._last_below.keys() and ticker not in self.tickers:
    #             # Ticker not traded anymore
    #             del self._last_below[ticker]

    def _initialise_last_below(self):
        for ticker in self.tickers:
            if ticker not in self._last_below.keys():
                # New ticker detected, initialise with None
                self._last_below[ticker] = None
                #print('new ticker added: '+ticker)
            
        for ticker in list(self._last_below.keys()):
            if ticker not in self.tickers:
                # Ticker not traded anymore, remove
                del self._last_below[ticker]
                #print('ticker removed: '+ticker)
    
    # Calculate Hawkes self exciting behavior
    @staticmethod
    def _hawkes_process(data: pd.Series, kappa: float):
        """
        Calculate Hawkes self exciting behavior

        Parameters
        ----------
        data: pd.Series
            Time series (indicator or close price)
        kappa: float
            Decay value of the Hwkes process 
            (The lower the longer the decay time )
        """
        assert(kappa > 0.0)
        alpha = np.exp(-kappa)
        arr = data.to_numpy()
        output = np.zeros(len(data))
        output[:] = np.nan
        for i in range(1, len(data)):
            if np.isnan(output[i - 1]):
                output[i] = arr[i]
            else:
                output[i] = output[i - 1] * alpha + arr[i]
        return pd.Series(output, index=data.index) * kappa
    
    @staticmethod
    def _normalized_range(bars: pd.DataFrame, lookback: int):
        """
        Calculate the normalized range of the ATR
        """
        data = pd.DataFrame()
        data['atr'] = ta.atr(bars['high'], bars['low'], bars['close'], length=lookback)
        data['norm_range'] = (np.log (bars['high']) - np.log(bars['low'])) / data['atr']
        return data['norm_range']

    @staticmethod
    def _calculate_quantile(data: pd.Series, lookback: int):
        """
        Calculate the rolling quantiles fro a given time-series
        """
        qnt = pd.DataFrame()
        qnt['q05'] = data.rolling(lookback).quantile(0.05)
        qnt['q95'] = data.rolling(lookback).quantile(0.95)
        return qnt


    def calculate_signal(self, bars, event, ticker):
        #Check if a stop or limit order is already present in the queue
        # TODO: da spostare in order_handler.compliance
        # for ev in self.global_queue.queue:
        #     if ev.type == EventType.ORDER and ev.ticker == event.ticker:
        #         return

        if len(bars) >= self.max_window:
            # Adjust the last below dictionary for new or removed tickers
            self._initialise_last_below()

            # Calculate the normalized ATR
            atr_norm = self._normalized_range(bars, self.NORM_LOOKBACK)
            
            # Calculate Hawkes self excitement
            vol_hawkes = self._hawkes_process(atr_norm, self.KAPPA)

            # Calculate the quantiles
            qnt = self._calculate_quantile(vol_hawkes, self.QUANT_LOOKBACK)

            #print(vol_hawkes[-1])
            #print(qnt['q05'].iloc[-1])


            # Last date Hawkes was below the 5% quantile
            if vol_hawkes[-1] < qnt['q05'].iloc[-1]:
                self._last_below[ticker] = event.time
                #print(self._last_below)

            ## ENTRY signals
            #print(self._last_below)
            if (vol_hawkes.iloc[-1] > qnt['q95'].iloc[-1]) and \
                (vol_hawkes.iloc[-2] <= qnt['q95'].iloc[-2]) and \
                self._last_below[ticker] is not None :

                change = bars.close[-1] - bars.close[self._last_below[ticker]]
                if change > 0.0:
                    return (('BOT','ENTRY'))
                # else:
                #     return (('SLD','ENTRY'))
            
            
            ## EXIT Signals
            if vol_hawkes.iloc[-1] < qnt['q05'].iloc[-1]:
                return (('SLD','EXIT'))

