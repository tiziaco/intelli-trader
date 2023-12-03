import numpy as np
from itrader.strategy.custom_indicators.custom_ind import pdensity
from itrader.strategy.custom_indicators.custom_ind import efficiency_ratio


class PriceDensity_filter():
    """
    Price Density noise filter.
    """
    def calculate(df, window, limit):
        """
        Calculate the PD filter.
        
        Parameters
        ----------
        df[['high','low'] : DataFrame with High, Low columns
        window : int loockback window
        limit : limit value where the series is considered noisy

        """
        filt = pdensity.calculate(df[['high','low']], window).to_frame()
        filt['filter'] = np.where(filt['pdensity'] > limit, 1, 0)
        return filt

class EfficiencyRatio_filter():
    """
    Kaufman Efficiency Ratio noise filter.
    """
    def calculate(df, window, limit):
        """
        Calculate the PD filter.
        
        Parameters
        ----------
        df['Close'] : Series with Close column
        window : int loockback window
        limit : limit value where the series is considered noisy

        """
        filt = efficiency_ratio.calculate(df['close'], window).to_frame()
        filt['filter'] = np.where(filt.iloc[:,0] > limit, 1, 0)
        return filt