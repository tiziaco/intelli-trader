import numpy as np
from qstrader.strategy.custom_indicators.custom_ind import pdensity
from qstrader.strategy.custom_indicators.custom_ind import efficiency_ratio


class PriceDensity_filter():
    """
    Price Density noise filter.
    """
    def calculate(df, window, limit):
        """
        Calculate the PD filter.
        
        Parameters
        ----------
        df[['High','Low'] : DataFrame with High, Low columns
        window : int loockback window
        limit : limit value where the series is considered noisy

        """
        filt = pdensity.calculate(df[['High','Low']], window).to_frame()
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
        filt = efficiency_ratio.calculate(df['Close'], window).to_frame()
        filt['filter'] = np.where(filt.iloc[:,0] > limit, 1, 0)
        return filt