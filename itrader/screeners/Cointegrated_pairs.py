import pandas as pd
import numpy as np

from statsmodels.tsa.stattools import coint
from statsmodels.api import OLS

from tqdm import tqdm

from qstrader.event import SignalEvent, EventType # Da vedere se serve

class Cointagrated_pairs():
    def __init__(self, price_handler):
        self.price_handler = price_handler
        self.prices = self.price_handler.prices
        self.coint_pair = []
        self.included_list = []
        self.universe=[] #TODO Da integrare


    def _calculate_spread(self, sr1, sr2, hedge_ratio):
        """
        Calculate spread
        """
        spread = pd.Series(sr1) - pd.Series(sr2) * hedge_ratio
        return spread

    def _calculate_cointegration(self, sr1, sr2):
        """
        Calculate co-integration
        """
        coin_flag=0
        #print(len(sr1),len(sr2))
        coin_res = coint(sr1,sr2)
        coin_t = coin_res[0]
        p_value = coin_res[1]
        critical_value = coin_res[2][1]
        model = OLS(sr1,sr2).fit()
        hedge_ratio = model.params[0]
        spread = self._calculate_spread(sr1, sr2, hedge_ratio)

        zero_crossing = len(np.where(np.diff(np.sign(spread)))[0])
        if p_value <0.5 and coin_t < critical_value:
            coin_flag = 1
        return (coin_flag, round(p_value,2), round(coin_t,2), round(critical_value,2), round(hedge_ratio,2), zero_crossing)

    def apply_screener(self):
        """
        Get cointagrated pairs
        """
        included_list = []
        coint_pair = []
        #print(self.prices.keys())
        for sym_1 in tqdm(self.prices.keys()):
            # Check ech coin against the first
            for sym_2 in self.prices.keys():
                if sym_2 != sym_1:
                    #print(sym_1, sym_2)
                    # Get unique combination id and ensure one off check
                    sorted_characters = sorted(sym_1 + sym_2)
                    unique = ''.join(sorted_characters)
        
                    if unique in included_list:
                        break

                    # Get close prices OK
                    sr1 = self.prices[sym_1]['Close'].to_list()
                    sr2 = self.prices[sym_2]['Close'].to_list()

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
        self.results = pd.DataFrame(coint_pair)
        self.results = self.results.sort_values(['zero_crossing'], ascending=False) #, axis=1 , ignore_index=True

    
    