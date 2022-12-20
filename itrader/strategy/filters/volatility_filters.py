from pandas_ta.volatility import atr
import numpy as np

class ATR_filter():
    """
    ATR volatility filter.
    """
    def calculate(df, window, percent, limit):
        vol = atr(df['High'], df['Low'], df['Close'], length=window, percent=percent).to_frame()
        vol['filter'] = np.where(vol.iloc[:,-1] >= limit, 1, 0)
        return vol
