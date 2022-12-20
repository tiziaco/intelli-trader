import numpy as np
import pandas as pd
import pandas_ta as ta

from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

### Noise indicators

class pdensity():
    """
    Calculate the Price Density of a time series
    """
    def _calculate_pdensity(df):
        sum_hl = np.sum(df['High'].to_numpy() - df['Low'].to_numpy())
        pdensity = np.divide(sum_hl,(max(df['High'] - min(df['Low']))))
        return pdensity
    
    def calculate(df, window):
        temp = list(map(pdensity._calculate_pdensity, df.loc[:,['High','Low']].rolling(window)))
        df.insert(2, 'pdensity',temp)
        df.iloc[:window,-1] = np.nan
        return df.iloc[:,-1]

class efficiency_ratio():
    """
    Calculate the Kaufman Efficency Ratio
    """
    def _calculate_kratio(df):
        up = np.absolute(df[0] - df[-1])
        down = np.sum(np.absolute(np.diff(df.to_numpy())))
        return (up / down)*100

    def calculate(df, window):
        return df.rolling(window).apply(efficiency_ratio._calculate_kratio)
    



###Smoothers

class SuperSmoother():
    """
    Calculate the smoothed line of a time-series
    """
    def calculate(sf, window, pole):
        ss = ta.ssf(sf, window, pole).to_frame('ss')
        ss['sdev'] = ss.rolling(window=window).std()
        ss['hband'] = ss.iloc[:,0] + ss.loc[:,'sdev']
        ss['lband'] = ss.iloc[:,0] - ss.loc[:,'sdev']
        # Slope
        return ss

class PolynomialReg():
    """
    Calculate the polinomial regression of a time series
    """
    def calculate (sf, order):
        x = np.arange(0,len(sf))
        y = sf.values
        poly_reg = PolynomialFeatures(degree=order, include_bias=False)
        X_poly = poly_reg.fit_transform(x.reshape(-1,1))
        pol_reg = LinearRegression()
        pol_reg.fit(X_poly, y)
        poly = pd.Series(pol_reg.predict(X_poly), sf.index)
        return poly, pol_reg.coef_