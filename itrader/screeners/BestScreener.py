import pandas as pd
import numpy as np
from tqdm import tqdm

from qstrader.event import SignalEvent, EventType # Da vedere se serve

class MostPerforming_screener():
    def __init__(self, price_handler,):
        self.price_handler = price_handler
        self.prices = self._prepare_data()
        self.results = {}
        self.universe=[] #TODO Da integrare

    '*** Create megaFrame with all Close price from all symbols'
    #TODO: Da migliorare: creare dataFrame multi_index con tutti i dati
    #TODO: inserire possibilita di fare un resample sui dati caricati dal db.
    def _prepare_data(self):
        df_list=[]
        for symbol in tqdm(self.price_handler.symbols):
            df=self.price_handler.read_prices_SQL(symbol)
            #df=read_SQL(symbol, engine)
            df=df['Close']
            df.name = symbol
            df_list.append(df)
        frame = pd.concat(df_list, axis=1)
        return frame

    def apply_screener(self):
        '*** Analysis'
        ret = self.pct_change()
        cumret = (ret + 1).cumprod() - 1

        self.results = {'gainers' : cumret.iloc[-1].nlargest(10),
                        'loosers' : cumret.iloc[-1].nsmallest(10)}