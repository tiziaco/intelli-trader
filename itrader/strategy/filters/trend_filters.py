from pandas_ta import trend
from pandas_ta import overlap
import numpy as np

from ..custom_indicators.custom_ind import SuperSmoother
from  qstrader.strategy.custom_indicators.custom_ind import PolynomialReg

class aroon_filter():
    """
    Aroon attempts to identify if a security is trending and how strong.
    """
    def calculate(df, window, limit):
        aroon = trend.aroon(df['High'], df['Low'], length=window)
        aroon['filter'] = np.where(aroon.iloc[:,2] >= limit, 1, 0)
        aroon['filter'] = np.where(aroon.iloc[:,2] <= -limit, -1, aroon.iloc[:,-1])
        return aroon

class supertrend_filter():
    """
    Identify market regime with SuperTrend filter.
    """
    def calculate(df, window, multiplier):
        supert = overlap.supertrend(df['High'], df['Low'], df['Close'],  window, multiplier)
        supert['filter'] = supert.iloc[:,1]
        supert.drop(supert.columns[1], axis=1)
        return supert

class supersmoother_filter():
    """
    Identify market regime with SuperTrend filter.
    """
    def _calculate_slope(sf):
        pred, slope = PolynomialReg.calculate(sf, 2)
        return slope[-1]

    def calculate(sf, window, pole, limit):
        """
        Parameters
        ----------
        sf: Series
            time_series to bi filtered (ex. Close)
        window: int
            Lookback window for SuperSmoother
        pole: int
            number of poles for SuperSmoother
        limit: int
            treashold min. slope (0 : 0.5)

        """
        filter = SuperSmoother.calculate(sf, window, pole)
        filter['slope'] = filter['ss'].rolling(window=window).apply(supersmoother_filter._calculate_slope)

        # Apply filter
        filter['filter'] = np.where(filter['slope'] >= 0, 1, 0)
        filter['filter'] = np.where(filter['slope'] <= 0, -1, filter['filter'])
        filter['filter'] = np.where(abs(filter['slope']) <= limit, 0, filter['filter'])
        
        return filter