import pandas as pd
import numpy as np

import statsmodels.tsa.stattools as ts
from statsmodels.tsa.stattools import coint
from statsmodels.api import OLS

from tqdm import tqdm

from itrader.screeners_handler.screeners.base import Screener



class CointegratedPairsScreener(Screener):
    def __init__(self, tickers = 'all', frequency = '1h', timeframe = '1h', WINDOW = 200):
        self.tickers = tickers
        self.timeframe = timeframe
        self.tf_delta = self._get_delta(timeframe)
        self.frequency = self._get_delta(frequency)

        self.max_window = WINDOW+2

        self.coint_pair = []
        self.included_list = []
        self.last_proposed = []

        self.screener_id = "CointegratedPairs"
    
    def __str__(self):
        return self.screener_id

    def __repr__(self):
        return str(self)

    @staticmethod
    def _calculate_spread(sr1: list, sr2: list, hedge_ratio):
        """
        Calculate spread
        """
        spread = pd.Series(sr1) - pd.Series(sr2) * hedge_ratio
        return spread
    
    @staticmethod
    def ADFtest(sr: pd.Series):
        """
        Compute the Augmented Dickey-Fuller (ADF) Test

        Returns
        -------
        p-value: float
            (if < 0.05 -> time series is stationary)
        """
        return ts.adfuller(sr)[1]

    def _calculate_cointegration(self, sr1: list, sr2: list):
        """
        Calculate co-integration
        """
        coin_flag=0
        coin_res = coint(sr1,sr2)
        coin_t = coin_res[0]
        p_value = coin_res[1]
        critical_value = coin_res[2][1]
        model = OLS(sr1,sr2).fit()
        hedge_ratio = model.params[0]

        spread = self._calculate_spread(sr1, sr2, hedge_ratio)
        p_value_spread = self.ADFtest(spread)

        zero_crossing = len(np.where(np.diff(np.sign(spread)))[0])
        if p_value < 0.05 and p_value_spread < 0.05 and coin_t < critical_value:
            coin_flag = 1
        return (coin_flag, round(p_value,2), round(coin_t,2), round(critical_value,2), round(hedge_ratio,2), zero_crossing)


    def apply_screener(self, mdf:pd.DataFrame, time):
        """
        Get cointagrated pairs
        """
        # TEMPORARY: drop columns containing NaN
        mdf.dropna(axis=1, inplace=True)

        if len(mdf) < self.max_window:
            return

        # Get the list of unique symbols in the MegaFrame
        symbols = list(set([item[0] for item in mdf.columns]))

        included_list = []
        coint_pair = []

        for sym_1 in ['BTCBUSD']: #symbols ['BTCBUSD']

            # Check each coin against the first
            for sym_2 in symbols:
                if sym_2 != sym_1:
                    #print(sym_1, sym_2)
                    # Get unique combination id and ensure one off check
                    sorted_characters = sorted(sym_1 + sym_2)
                    unique = ''.join(sorted_characters)
        
                    if unique in included_list:
                        break

                    # Get close prices lists OK
                    sr1 = mdf.loc[:, (sym_1, 'close')].to_list()
                    sr2 = mdf.loc[:, (sym_2, 'close')].to_list()

                    # Check for cointegration OK
                    if len(sr1)==len(sr2):
                        coin_flag, p_value, t_value, c_value, hedge_ratio, zero_crossing = self._calculate_cointegration(sr1, sr2)
                        if coin_flag == 1:
                            included_list.append(unique)
                            coint_pair.append({
                                'sym_1': sym_1,
                                'sym_2': sym_2,
                                'p_value': p_value,
                                't_value': t_value,
                                'c_value': c_value,
                                'hedge_ratio': hedge_ratio,
                                'zero_crossing': zero_crossing,})
        #Output results
        results = pd.DataFrame(coint_pair)
        results = results.sort_values(['zero_crossing'], ascending=False) #, axis=1 , ignore_index=True
        #return results

        # Create list of tuples with the first 10 pairs
        proposed = list(zip(results['sym_1'].head(10), results['sym_2'].head(10)))
        self.last_proposed = proposed
        return proposed

