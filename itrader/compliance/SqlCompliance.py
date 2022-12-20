import pandas as pd

from itrader.outils.price_parser import PriceParser
from .base import AbstractCompliance

import logging
logger = logging.getLogger()


class SqlCompliance(AbstractCompliance):
    """
    A basic compliance module which writes trades into a
    SQL database in the output directory.
    """

    def __init__(self, config, engine):
        """
        It allows for multiple backtests to be run
        in a simple way, but quite likely makes it unsuitable for
        a production environment that requires strict record-keeping.
        """
        self.config = config
        self.engine = engine
        # Remove the exhisting table from the SQL db
        self._remove_table_SQL(engine)
        logger.info('COMPLIANCE: To Sql => OK')
    
    
    def _remove_table_SQL(self, engine):
        qry_str = f'DROP TABLE IF EXISTS trades;'
        engine.execute(qry_str)

    def record_trade(self, fill):
        """
        Record all details about the FillEvent into the trade log 
        table in the SQL .db.
        """
        mydict={'timestamp':[fill.timestamp],
                'exchange':[fill.exchange], 
                'ticker':[fill.ticker],
                'action':[fill.action], 
                'quantity':[fill.quantity], 
                'price':[PriceParser.display(fill.price, 4)],
                'commission':[PriceParser.display(fill.commission, 4)]}
        df = pd.DataFrame(mydict, index=[0])
        df.to_sql('trades', self.engine, index = False, if_exists='append')
    
    def record_portfolio(self, timestamp, report):
        """
        Record the details of the portfolio in the the SQL .db 
        """
        portfolio={
            'Date': timestamp,
            'positions': report[0],
            'invested' : report[1],
            'equity' : report[2],
            'realised_pnl' : report[3],
            'cash' : report[4],
        }
        df = pd.DataFrame(portfolio, index=[0])
        df.to_sql('portfolio', self.engine, index = False, if_exists='append')
